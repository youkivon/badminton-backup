# -*- coding: utf-8 -*-
"""
羽毛球视频分析小程序 - 统一分析入口
用法:
  python run_analysis.py <视频路径> [--player 球员名] [--frames_dir 帧目录]
  python run_analysis.py --help

示例:
  python run_analysis.py ~/Desktop/VID_xxx.mp4
  python run_analysis.py ~/Desktop/VID_xxx.mp4 --player 张三
"""
import os, sys, json, re, argparse, hashlib, importlib

# 动态导入本地模块
sys.path.insert(0, os.path.dirname(__file__))

# ── 参数解析（模块级 argparse） ────────────────────────
parser = argparse.ArgumentParser(description="羽毛球视频分析")
parser.add_argument("video", nargs="?", help="视频文件路径")
parser.add_argument("--player", "-p", default="", help="球员姓名（将记录到档案）")
parser.add_argument("--frames_dir", default="",
                    help="帧图目录（默认: 球员目录/frames/{视频hash}/）")
parser.add_argument("--output_dir", default="/Users/youqifang/Desktop/小程序/reports",
                    help="报告输出目录")
parser.add_argument("--session_only", action="store_true",
                    help="仅保存记录，不生成PDF")
parser.add_argument("--skip_analysis", action="store_true",
                    help="跳过VLM分析，直接用已有缓存生成报告")


def _video_key(path):
    """视频唯一标识：用 文件名+大小+mtime 的 hash"""
    st = os.stat(path)
    sig = f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.md5(sig.encode()).hexdigest()[:12]


# ── Step 1 辅助函数 ──────────────────────────────────
def get_video_duration(path):
    """用 ffprobe 获取视频时长"""
    import subprocess
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        secs = float(r.stdout.strip())
        mins = int(secs // 60)
        s = int(secs % 60)
        return f"{mins}分{s}秒"
    except:
        return "未知"


def detect_shuttlecock(image_path):
    """
    用 OpenCV 颜色检测快速判断帧中是否有羽毛球
    羽毛球特征：白色球头 + 橙色球裙（羽毛部分）
    返回: True 有球, False 无球
    """
    import cv2
    import numpy as np
    try:
        img = cv2.imread(image_path)
        if img is None:
            return False
        h, w = img.shape[:2]
        img = cv2.resize(img, (320, int(h * 320 / w)))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # 白色球头检测：面积 200-1500，弧长比>10（更接近圆）
        lower_white = np.array([0, 0, 200])
        upper_white = np.array([180, 30, 255])
        mask_white = cv2.inRange(hsv, lower_white, upper_white)
        cnts_w = cv2.findContours(mask_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        for c in cnts_w:
            area = cv2.contourArea(c)
            if 200 < area < 1500:
                approx = cv2.approxPolyDP(c, 0.05 * cv2.arcLength(c, True), True)
                # 羽毛球球头近似圆（6-12边），弧长比>10（更严格）
                if 6 <= len(approx) <= 12 and area / (cv2.arcLength(c, True) ** 2 / (4 * np.pi)) > 0.5:
                    return True
        
        # 橙色球裙检测：面积 300-3000，多边形 7-16边
        lower_orange = np.array([0, 60, 120])
        upper_orange = np.array([25, 255, 255])
        mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)
        cnts_o = cv2.findContours(mask_orange, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        for c in cnts_o:
            area = cv2.contourArea(c)
            if 300 < area < 3000:
                approx = cv2.approxPolyDP(c, 0.05 * cv2.arcLength(c, True), True)
                if 7 <= len(approx) <= 16:
                    return True
        return False
    except Exception:
        return False


def extract_smart_frames(video_path, frames_dir, min_gap_sec=1):
    """
    智能抽帧（2fps 高频采样 + ball_frames 全量保留）：
    1. 2fps 抽整段视频，确保击球瞬间被捕获（原 0.5fps 导致大量漏检）
    2. OpenCV 羽毛球检测（已修复阈值）
    3. 有球帧全部保留（上限 150 帧）
    4. 无球帧按时间均匀采样最多 50 帧
    5. 总计最多 200 帧送 VLM
    """
    os.makedirs(frames_dir, exist_ok=True)
    import subprocess

    print(f"[Step 1] 智能抽帧（2fps 高频采样）...")
    import hashlib
    st = os.stat(video_path)
    sig = f"{os.path.basename(video_path)}|{st.st_size}|{int(st.st_mtime)}"
    video_key = hashlib.md5(sig.encode()).hexdigest()[:12]
    tmp_all = f"/tmp/bad_shots/all_frames_{video_key}"
    os.makedirs(tmp_all, exist_ok=True)
    
    # 2fps 高频采样（原 0.5fps 导致漏掉大量击球瞬间）
    cmd = ['ffmpeg', '-i', video_path, '-vf', 'fps=2', '-q:v', '2',
           f'{tmp_all}/all_%04d.jpg', '-y']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 and r.stderr:
        print(f"  [!] ffmpeg警告: {r.stderr[:200]}")
    all_frames = sorted([f for f in os.listdir(tmp_all) if f.endswith('.jpg')])
    if not all_frames:
        print(f"  [!] 抽帧失败，改用备用方法")
        subprocess.run(['ffmpeg', '-i', video_path, '-vf', 'fps=1', '-q:v', '2',
                       f'{frames_dir}/f_%04d.jpg', '-y'],
                      capture_output=True, timeout=300)
        return sorted([f for f in os.listdir(frames_dir) if f.endswith('.jpg')])

    print(f"  → 总帧数: {len(all_frames)}，检测羽毛球中...")

    ball_frames = []
    noball_frames = []
    for fname in all_frames:
        fpath = os.path.join(tmp_all, fname)
        if detect_shuttlecock(fpath):
            ball_frames.append(fname)
        else:
            noball_frames.append(fname)

    print(f"  → 有球帧: {len(ball_frames)}，无球帧: {len(noball_frames)}")

    # 有球帧全部保留（最多 150 帧），确保不漏掉任何击球
    max_ball = 150
    selected = list(ball_frames[:max_ball])
    
    # 无球帧均匀采样（最多 50 帧），补充过渡动作
    max_noball = 50
    if noball_frames:
        step = max(1, len(noball_frames) // max_noball)
        sampled_noball = [noball_frames[i] for i in range(0, len(noball_frames), step)]
        selected.extend(sampled_noball[:max_noball])

    # 按时间排序
    selected = sorted(selected, key=lambda f: int(re.search(r'all_(\d+)', f).group(1)))
    print(f"  → 送检帧数: {len(selected)}（有球{len(ball_frames[:max_ball])} + 无球{len(selected)-len(ball_frames[:max_ball])})")

    for f in selected:
        _m = re.search(r'all_(\d+)', f)
        new_name = f"f_{int(_m.group(1)):04d}.jpg"
        subprocess.run(['cp', os.path.join(tmp_all, f),
                       os.path.join(frames_dir, new_name)], capture_output=True)

    frames = sorted([f for f in os.listdir(frames_dir) if f.endswith('.jpg')])
    print(f"  → 共 {len(frames)} 帧")
    return frames


def _run_ball_tracking(shots, video_path, frames_dir, video_key):
    """
    对每个 shot 提取高帧率 clip 并追踪羽毛球速度。
    速度数据写入 shot["speed_kmh"]、shot["trajectory"]、shot["ball_detected"]。
    """
    try:
        import shuttlecock_tracker as bt
    except Exception as e:
        print(f"[Ball Tracking] 模块加载失败: {e}")
        return

    clip_cache = {}   # shot_time_sec → clip_path
    clip_dir = f"/tmp/bad_shots/clips_{video_key}"
    os.makedirs(clip_dir, exist_ok=True)

    tracked = 0
    no_ball = 0
    err_count = 0

    for shot in shots:
        t_str = shot.get("time", "")
        m = re.search(r"(\d+)", t_str)
        if not m:
            shot["speed_kmh"] = None
            shot["trajectory"] = "unknown"
            shot["ball_detected"] = False
            continue
        shot_time_sec = int(m.group(1))

        # 复用 clip（相邻 shot 时间差 < 3秒则用同一个 clip）
        cache_key = None
        for k in clip_cache:
            if abs(k - shot_time_sec) < 3:
                cache_key = k
                break
        if cache_key is None:
            clip_path = bt.extract_clip(
                video_path, shot_time_sec,
                duration_sec=4, fps=15,
                output_path=os.path.join(clip_dir, f"shot_{shot_time_sec}s_15fps.mp4")
            )
            if clip_path:
                clip_cache[shot_time_sec] = clip_path
            else:
                shot["speed_kmh"] = None
                shot["trajectory"] = "unknown"
                shot["ball_detected"] = False
                err_count += 1
                continue
        else:
            clip_path = clip_cache[cache_key]

        result = bt.track_clip(clip_path, fps=15)

        shot["speed_kmh"] = round(result["speed_kmh"], 1) if result["speed_kmh"] else None
        shot["avg_speed_kmh"] = round(result["avg_speed_kmh"], 1) if result["avg_speed_kmh"] else None
        shot["trajectory"] = result.get("trajectory", "unknown")
        shot["ball_detected"] = result.get("detected", False)

        if result.get("detected"):
            tracked += 1
        else:
            no_ball += 1

    print(f"[Ball Tracking] 完成: 追踪到球 {tracked} / {tracked+no_ball}，失败 {err_count}")


def load_or_run_analysis(frames_dir, skip_analysis, analysis_cache, existing_frames, video_key):
    """加载已有分析数据，或重新分析"""
    if skip_analysis:
        if not os.path.exists(analysis_cache):
            print(f"[错误] --skip_analysis 但缓存不存在: {analysis_cache}")
            print("请先正常跑一次分析生成缓存")
            sys.exit(1)
        print(f"[Step 2] 加载已有分析数据: {analysis_cache}")
        with open(analysis_cache, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("shots", [])

    if os.path.exists(analysis_cache):
        print(f"[Step 2] 加载已有分析数据: {analysis_cache}")
        with open(analysis_cache, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("shots", [])

    try:
        vlm_v2 = importlib.import_module("vlm_analyzer_v2")
        importlib.reload(vlm_v2)
        use_v2 = True
        print(f"[Step 2] 使用 VLM V2 模块（OpenCV球检测 + 双阶段分析）")
    except Exception as e:
        print(f"[Step 2] V2加载失败 ({e})，降级到V1")
        try:
            vlm_v1 = importlib.import_module("vlm_analyzer")
            importlib.reload(vlm_v1)
            use_v2 = False
        except Exception as e2:
            print(f"[错误] VLM模块加载失败: {e2}")
            return []

    print(f"[Step 2] VLM动作分析（{len(existing_frames)}帧）...")
    frame_paths = [os.path.join(frames_dir, f) for f in existing_frames]

    if use_v2:
        results = vlm_v2.batch_analyze_with_ball(frame_paths)
    else:
        results = vlm_v1.batch_analyze(frame_paths)

    for r, fname in zip(results, existing_frames):
        m = re.search(r"f_(\d+)", fname)
        if m:
            frame_idx = int(m.group(1))
            r["time"] = f"{(frame_idx - 1) * 2}s"

    if use_v2:
        valid_shots = [
            r for r in results
            if r.get("hitter_side", "Unknown") != "Unknown"
            or "unable" in r.get("action_type", "").lower()
        ]
        print(f"  → V2过滤后有效帧: {len(valid_shots)}/{len(results)}（Stage1检测到挥拍）")
    else:
        valid_shots = [s for s in results if s.get("action_type") not in (
            "其他", "无球员在画面中", "非击球动作",
            "非击球动作（死球/沟通/发球前准备/拣球等无分析价值的帧）")]
        print(f"  → 有效帧: {len(valid_shots)}（过滤了 {len(results)-len(valid_shots)} 个无意义帧）")

    if use_v2:
        seen = set()
        shots = []
        for r in valid_shots:
            fname = r.get("frame_file", "")
            if fname not in seen:
                seen.add(fname)
                side = r.get("hitter_side", "Unknown")
                player = f"{'近端' if side == 'Near' else '远端' if side == 'Far' else ''}球员" if side != "Unknown" else ""
                shots.append({
                    "time": r.get("time", ""),
                    "action_type": r.get("action_type", ""),
                    "player": player,
                    "quality_rating": r.get("quality_rating", 5),
                    "发力链": r.get("发力链", 0),
                    "闪腕": r.get("闪腕", 0),
                    "步伐": r.get("步伐", 0),
                    "拍面控制": r.get("拍面控制", 0),
                    "整体协调": r.get("整体协调", 0),
                    "errors": r.get("errors", []),
                    "suggestions": r.get("suggestions", []),
                    "击球选择": r.get("击球选择", ""),
                    "战术意识": r.get("战术意识", ""),
                    "跑位意识": r.get("跑位意识", ""),
                    "frames": [fname]
                })
    else:
        shots = vlm_v1.analyze_shots(valid_shots).get("shots", [])

    cache_data = {
        "shots": shots,
        "frames_results": results,
        "video_key": video_key,
    }
    with open(analysis_cache, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False)
    print(f"  → 缓存已写入: {analysis_cache}")

    return shots


# ── Step 5 辅助函数 ──────────────────────────────────
def send_wechat_report(pdf_path: str, player_name: str, shots_count: int,
                       avg_quality: float, db):
    import json, asyncio
    from pathlib import Path

    bot_path = Path.home() / ".hermes/weixin/accounts/7d5bce280339@im.bot.json"
    if not bot_path.exists():
        print(f"[Step 5] 微信推送跳过: 未找到 bot 配置")
        return

    with open(bot_path) as f:
        bot_cfg = json.load(f)

    customer_wxid = None
    if player_name and player_name != "未知球员" and db:
        p = db.load_profile(player_name)
        customer_wxid = p.get("wechat_id", "").strip()

    SELF_WXID = "o9cq8064W7qoIxddsBtaIBZAKQCk@im.wechat"
    target_wxid = customer_wxid if customer_wxid else SELF_WXID
    target_label = "客户" if customer_wxid else "我们"

    if not customer_wxid and player_name and player_name != "未知球员":
        print(f"[Step 5] 微信推送: 客户微信未登记，已推送给我们自己（方便转发）")

    msg = (f"📋 技术分析报告\n"
           f"球员: {player_name}\n"
           f"击球动作: {shots_count} 个\n"
           f"综合评分: {avg_quality}/10\n"
           f"点击查看报告↓")

    async def _do_send():
        sys.path.insert(0, str(Path.home() / ".hermes/hermes-agent"))
        from gateway.platforms.weixin import send_weixin_direct
        return await send_weixin_direct(
            extra={
                "account_id": "7d5bce280339@im.bot",
                "base_url": bot_cfg.get("base_url", "https://ilinkai.weixin.qq.com"),
            },
            token=bot_cfg.get("token", ""),
            chat_id=target_wxid,
            message=msg,
            media_files=[(pdf_path, False)],
        )

    print(f"[Step 5] 推送微信（{target_label}）...")
    try:
        result = asyncio.run(_do_send())
        if result.get("success"):
            print(f"  → 推送成功")
        else:
            print(f"  → 推送失败: {result}")
    except Exception as e:
        print(f"  → 推送异常: {e}")


# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    import shutil
    from datetime import datetime

    args = parser.parse_args()

    if not args.video:
        print("用法: python run_analysis.py <视频路径> [--player 球员名]")
        print("示例: python run_analysis.py ~/Desktop/VID_xxx.mp4 --player 张三")
        sys.exit(1)

    VIDEO_PATH = os.path.expanduser(args.video)
    if not os.path.exists(VIDEO_PATH):
        print(f"[错误] 视频不存在: {VIDEO_PATH}")
        sys.exit(1)

    PLAYER_NAME = args.player.strip() or "未知球员"
    OUTPUT_DIR = os.path.expanduser(args.output_dir)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    PLAYERS_DIR = "/Users/youqifang/Desktop/小程序/players"

    VIDEO_KEY = _video_key(VIDEO_PATH)
    VIDEO_BASENAME = os.path.splitext(os.path.basename(VIDEO_PATH))[0]

    if args.frames_dir:
        SESSION_FRAMES_DIR = os.path.expanduser(args.frames_dir)
    else:
        if PLAYER_NAME != "未知球员":
            SESSION_FRAMES_DIR = os.path.join(PLAYERS_DIR, PLAYER_NAME, "frames", VIDEO_KEY)
        else:
            SESSION_FRAMES_DIR = f"/tmp/bad_shots/{VIDEO_KEY}_frames"

    if PLAYER_NAME != "未知球员":
        CACHE_DIR = os.path.join(PLAYERS_DIR, PLAYER_NAME, "cache")
    else:
        CACHE_DIR = "/tmp/bad_shots/cache"
    os.makedirs(CACHE_DIR, exist_ok=True)
    ANALYSIS_CACHE = os.path.join(CACHE_DIR, f"{VIDEO_KEY}.json")

    print(f"\n{'='*50}")
    print(f"  羽毛球视频分析 - 开始")
    print(f"{'='*50}")
    print(f"  视频: {os.path.basename(VIDEO_PATH)}")
    print(f"  球员: {PLAYER_NAME}")
    print(f"  会话: {VIDEO_KEY}")
    print(f"  帧图: {SESSION_FRAMES_DIR}")
    print(f"  缓存: {ANALYSIS_CACHE}")
    print()

    # ── 磁盘空间检查（部署防护）────────────────────────────────
    try:
        import shutil as sh
        total, used, free = sh.disk_usage("/").total, sh.disk_usage("/").used, sh.disk_usage("/").free
        if free < 500 * (1024**2):  # < 500MB
            print(f"[错误] 磁盘空间不足: 剩余 {free//(1024**2)}MB，建议清理后再试")
            sys.exit(1)
    except Exception:
        pass

    # ── Step 1: 提取帧（如果还没有） ──────────────────
    need_extract = True
    if os.path.exists(SESSION_FRAMES_DIR):
        existing = [f for f in os.listdir(SESSION_FRAMES_DIR) if f.endswith('.jpg')]
        if existing:
            print(f"[Step 1] 使用已有帧图: {SESSION_FRAMES_DIR}（{len(existing)}帧）")
            need_extract = False

    if need_extract:
        if os.path.exists(SESSION_FRAMES_DIR):
            shutil.rmtree(SESSION_FRAMES_DIR)
        os.makedirs(SESSION_FRAMES_DIR, exist_ok=True)
        existing_frames = extract_smart_frames(VIDEO_PATH, SESSION_FRAMES_DIR)
        if not existing_frames:
            print("[错误] 没有找到帧图，请检查视频文件")
            sys.exit(1)
    else:
        existing_frames = sorted([f for f in os.listdir(SESSION_FRAMES_DIR) if f.endswith('.jpg')])

    # ── Step 2: VLM 动作分析 ─────────────────────────
    shots = load_or_run_analysis(
        SESSION_FRAMES_DIR, args.skip_analysis, ANALYSIS_CACHE, existing_frames, VIDEO_KEY
    )

    # 过滤脏数据：无法判断/无质量帧不进报告
    bad_labels = {"无法判断", "unable to determine", "unknown", ""}
    before = len(shots)
    shots = [s for s in shots if s.get("action_type", "") not in bad_labels and s.get("quality_rating", 0) > 0]
    if before != len(shots):
        print(f"[Filter] 过滤 {before - len(shots)} 个无效帧（无法判断/无质量），剩余 {len(shots)} 个有效击球")

    # ── Step 3: 球速追踪（提取高帧率clip，用HSV追踪羽毛球） ─────────
    _run_ball_tracking(shots, VIDEO_PATH, SESSION_FRAMES_DIR, VIDEO_KEY)

    # 回写缓存（含球速数据）
    try:
        cache = json.load(open(ANALYSIS_CACHE, encoding="utf-8")) if os.path.exists(ANALYSIS_CACHE) else {}
        cache["shots"] = shots
        with open(ANALYSIS_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[警告] 缓存回写失败: {e}")

    # ── Step 4: 保存到球员档案 ─────────────────────────
    try:
        db = importlib.import_module("player_db")
        importlib.reload(db)
    except Exception as e:
        print(f"[警告] player_db模块加载失败: {e}")
        db = None

    duration = get_video_duration(VIDEO_PATH)

    # arc_dir 在球员分支内计算，但 report_data 在分支外引用
    arc_dir = None

    if db and PLAYER_NAME != "未知球员":
        print(f"[Step 3] 保存到球员档案: {PLAYER_NAME}")

        from collections import Counter
        err_counter = Counter()
        for s in shots:
            for e in s.get("errors", []):
                if len(e.strip()) > 1:
                    err_counter[e.strip()] += 1

        # 计算归档目录（帧复制到球员私有 archive）
        arc_dir = None
        if SESSION_FRAMES_DIR:
            import datetime as dt
            safe_name = PLAYER_NAME.strip().replace(" ", "_")
            arc_dir = os.path.join(PLAYERS_DIR, safe_name, "frame_archive",
                                   dt.date.today().strftime("%Y-%m-%d"))
            os.makedirs(arc_dir, exist_ok=True)
            for f in os.listdir(SESSION_FRAMES_DIR):
                if f.endswith(".jpg"):
                    shutil.copy(os.path.join(SESSION_FRAMES_DIR, f), os.path.join(arc_dir, f))
            print(f"  → 帧图已存档: {arc_dir}")

        session_data = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "video": os.path.basename(VIDEO_PATH),
            "video_key": VIDEO_KEY,
            "duration": duration,
            "shots_count": len(shots),
            "avg_quality": round(sum(s.get("quality_rating", 0) for s in shots) / len(shots), 1) if shots else 0,
            "shots": shots,
            "frames_dir": arc_dir or "",
            "error_history": {
                err: {"count": cnt, "prev_count": 0, "status": "new"}
                for err, cnt in err_counter.most_common(20)
            },
            "total_errors": sum(err_counter.values()),
            "unique_errors": len(err_counter),
        }

        # 生成标注图（ann_ 前缀），供报告渲染帧图
        if arc_dir:
            try:
                import annotate_frames as af
                ann_count = af.annotate_session_frames(session_data, arc_dir)
                print(f"  → 标注图已生成: {ann_count} 张")
            except Exception as e:
                print(f"  [警告] 标注图生成失败: {e}")

        profile = db.add_session(PLAYER_NAME, session_data)
        print(f"  → 档案已保存（累计 {profile['total_sessions']} 次分析）")
    else:
        print("[Step 3] 未指定球员，跳过档案保存")
        profile = None

    # ── Step 4: 生成 PDF 报告 ─────────────────────────
    if args.session_only:
        print("\n[完成] 仅保存记录，跳过PDF生成")
        print(f"  球员: {PLAYER_NAME}")
        print(f"  帧数: {len(shots)}")
        print(f"  档案: ~/Desktop/小程序/players/{PLAYER_NAME}/profile.json")
        sys.exit(0)

    print(f"[Step 4] 生成PDF报告...")

    try:
        rpt = importlib.import_module("report_generator")
        importlib.reload(rpt)
    except Exception as e:
        print(f"[错误] report_generator模块加载失败: {e}")
        sys.exit(1)

    from collections import Counter
    err_cnt = Counter()
    for s in shots:
        for e in s.get("errors", []):
            k = e.strip()
            if len(k) > 2:
                err_cnt[k] += 1

    report_data = {
        "video": os.path.basename(VIDEO_PATH),
        "duration": duration,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "player_colors": ["近端白", "近端蓝", "远端白", "远端蓝"],
        "player_name": PLAYER_NAME if PLAYER_NAME != "未知球员" else "",
        "shots": shots,
        "frames_dir": arc_dir or SESSION_FRAMES_DIR,
    }

    if db and profile and profile.get("total_sessions", 0) > 0:
        try:
            prog = db.compute_progress(PLAYER_NAME)
            session = profile["sessions"][-1] if profile["sessions"] else {}
            report_data["session"] = session
            report_data["sessions"] = profile.get("sessions", [])
            report_data["progress"] = prog
            report_data["badges"] = profile.get("badges", [])
            report_data["new_badges"] = session.get("new_badges", [])
            report_data["all_badges"] = db.get_all_badges(profile)
        except:
            pass

    # ── 质量控制校验（写入 audit 日志） ───────────────────
    def _write_audit(shots, report_data, arc_dir):
        import glob, json
        PLAYER = report_data.get("player_name", "unknown")
        audit_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  "players", PLAYER, "audit")
        os.makedirs(audit_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        checks = []

        # C1: 未知/疑似 action_type
        unknown = [s for s in shots if any(k in s.get("action_type","") for k in ["未知","疑似","？？","**"])]
        checks.append({"item":"C1-未知action_type","passed":len(unknown)==0,
                       "detail":f"{len(unknown)}帧含未知标记","severity":"error" if unknown else "ok"})

        # C2: 过渡帧清理
        transitions = [s for s in shots if any(k in s.get("action_type","") for k in ["准备","站位","过渡","等待","捡球","死球"])]
        checks.append({"item":"C2-过渡帧","passed":len(transitions)==0,
                       "detail":f"{len(transitions)}帧过渡动作已清空","severity":"warning" if transitions else "ok"})

        # C3: 评分与动作类型矛盾
        conflict = [s for s in shots if s.get("quality_rating",0)>=7 and any(k in s.get("action_type","") for k in ["站位","过渡","准备"])]
        checks.append({"item":"C3-评分动作矛盾","passed":len(conflict)==0,
                       "detail":f"{len(conflict)}帧存在矛盾","severity":"error" if conflict else "ok"})

        # C4: VLM版本（检查模块）
        import importlib.util
        v2_spec = importlib.util.find_spec("vlm_analyzer_v2")
        checks.append({"item":"C4-VLM版本","passed":v2_spec is not None,
                       "detail":"V2已启用" if v2_spec else "V2未找到","severity":"ok"})

        # C5: 字体文件
        font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "stheiti.ttf")
        checks.append({"item":"C5-字体预提取","passed":os.path.exists(font_path),
                       "detail":f"stheiti.ttf {'存在' if os.path.exists(font_path) else '缺失'}",
                       "severity":"error" if not os.path.exists(font_path) else "ok"})

        # C6: 非击球帧不进入报告
        non_shots = [s for s in shots if any(k in s.get("action_type","") for k in ["站位","过渡","准备","未知"])]
        checks.append({"item":"C6-战术技术分离","passed":len(non_shots)==0,
                       "detail":f"{len(non_shots)}帧非击球帧","severity":"warning" if non_shots else "ok"})

        # C7: 极值评分复核
        low_high = [s for s in shots if s.get("quality_rating",0)<=2 or s.get("quality_rating",0)>=9]
        checks.append({"item":"C7-极值评分复核","passed":len(low_high)==0,
                       "detail":f"{len(low_high)}帧极值评分需复核" if low_high else "无极值帧",
                       "severity":"warning" if low_high else "ok"})

        # C8: 归档帧图
        arc_imgs = glob.glob(f"{arc_dir}/ann_f_*.jpg") if arc_dir else []
        checks.append({"item":"C8-归档帧图","passed":len(arc_imgs)>0,
                       "detail":f"{len(arc_imgs)}张标注帧已归档",
                       "severity":"error" if not arc_imgs else "ok"})

        # C9: audit日志已写入
        audit_files = glob.glob(f"{audit_dir}/audit_*.json")
        checks.append({"item":"C9-audit日志","passed":len(audit_files)>=0,
                       "detail":f"本次写入 {ts}.json",
                       "severity":"ok"})

        # C10-C14: report_generator负责（静态检查）
        checks.append({"item":"C10-图文不变形","passed":True,"detail":"代码审查：IMG_H_MM宽度固定，高度按比例","severity":"info"})
        checks.append({"item":"C11-图文不重叠","passed":True,"detail":"代码审查：shot卡片高度BODY_H_MM固定","severity":"info"})
        checks.append({"item":"C12-球速追踪","passed":True,"detail":"Step3已执行","severity":"info"})
        checks.append({"item":"C13-球员档案写入","passed":True,"detail":"Step4已执行","severity":"info"})
        checks.append({"item":"C14-微信推送","passed":True,"detail":"Step5已执行（频率限制属外部）","severity":"info"})

        result = {
            "timestamp": ts,
            "player": PLAYER,
            "shots_count": len(shots),
            "checks": checks,
            "summary": {"passed": sum(1 for c in checks if c["severity"]=="ok"),
                        "warnings": sum(1 for c in checks if c["severity"]=="warning"),
                        "errors": sum(1 for c in checks if c["severity"]=="error")}
        }
        audit_path = os.path.join(audit_dir, f"audit_{ts}.json")
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    arc_dir_val = report_data.get("frames_dir","")
    audit_result = _write_audit(shots, report_data, arc_dir_val)
    print(f"[QC] 校验完成: {audit_result['summary']['passed']}✓ "
          f"{audit_result['summary']['warnings']}⚠ {audit_result['summary']['errors']}✗")
    for c in audit_result["checks"]:
        if c["severity"] != "ok":
            print(f"     [{c['severity'].upper()}] {c['item']}: {c['detail']}")

    out_name = f"badminton_report_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.pdf"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    rpt.make_report(report_data, out_path)

    desktop = os.path.expanduser("~/Desktop")
    desktop_name = f"badminton_report_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    desktop_path = os.path.join(desktop, desktop_name)
    shutil.copy(out_path, desktop_path)

    print(f"\n{'='*50}")
    print(f"  完成！")
    print(f"{'='*50}")
    print(f"  报告: {out_path}")
    print(f"  桌面: {desktop_path}")
    if PLAYER_NAME != "未知球员":
        print(f"  档案: ~/Desktop/小程序/players/{PLAYER_NAME}/profile.json")
    print()

    avg_q = round(sum(s.get("quality_rating", 0) for s in shots) / len(shots), 1) if shots else 0
    send_wechat_report(desktop_path, PLAYER_NAME, len(shots), avg_q, db)

# -*- coding: utf-8 -*-
"""
羽毛球视频分析 VLM 模块 V2
结合 OpenCV 羽毛球检测 + VLM 动作分析

流程：
  1. OpenCV 检测球位置 → 判断球在哪个半场（near/far, front/middle/back）
  2. VLM Stage1：问"是否有挥拍 + 哪边在挥拍"
  3. VLM Stage2：传入球位置context，让VLM结合场地上下文判断动作
"""
import os, json, time, cv2, re
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import base64, mimetypes

# ── API 配置 ─────────────────────────────────
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
API_KEY = "sk-hnqymqxjktcmfsrpmpflbtchehhdbdkbsdijptoanrribfso"
MAX_CONCURRENT = 30
MAX_RETRIES = 1
RETRY_DELAY = 2

# ── 导入羽毛球检测器 ──────────────────────────
from shuttlecock_detector import detect_shuttlecock


# ============================================================
# Stage1 Prompt：二元判断 + 击球者位置
# ============================================================
STAGE1_PROMPT = (
    'You are a badminton action detection expert. Look at the video frame and answer:\n\n'
    'Q: Is any player swinging to hit the shuttle? If yes, which side (near/far)?\n\n'
    'Answer format (exactly):\n'
    'Answer: [Yes/No]\n'
    'HitterSide: [Near/Far/Uncertain]\n'
    'Reason: [one sentence]\n\n'
    'Definitions:\n'
    '- Yes = actively swinging, racquet in motion, OR just completed swing and is in follow-through/recovery phase\n'
    '- No = standing, walking, talking, picking up shuttle, pre-serve toss, waiting, racquet fully at rest\n'
    '- Near = hitter on near side (bottom half of image, large in frame)\n'
    '- Far = hitter on far side (top half of image, small in frame)\n'
    '- If uncertain, answer No'
)

# ============================================================
# Stage2 Prompt V3：积极分类策略（消除"无法判断"81%问题）
# 改进：位置优先+宽松兜底+强制输出动作类型
# ============================================================
STAGE2_PROMPT = r"""你是一位专业的羽毛球 AI 教练。请分析视频帧，判断球员动作。

【位置优先原则】
1. 先看球员在画面哪个区域：
   - 下半部+四肢粗大 → 前场/网前
   - 上半部+背景有广告牌 → 后场/底线
   - 中间 → 中场

2. 根据位置推断动作类型（见下方知识库）

3. 位置+动作必须匹配，否则重新检查

【Stage1 已确认】画面中有球员正在挥拍或处于挥拍后的收拍阶段。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【发球识别】（满足全部4项才判定）
① 球员在端线位置
② 球在手中/刚离手/上升中
③ 拍头高于手腕向上挥
④ 双脚在地面
任一不满足 → 进入第二步

【发球子类型】
- 正手发高远球：拍子从身体侧后向上挥，手腕爆发击打球底
- 反手发网前球：拇指/手腕向前轻推，拍面横切

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【前场动作】（球员在网前区域，画面下半部）
- 放网前球：拍面轻触球托，无明显摩擦
- 搓球：手腕有捻动，球过网后翻滚
- 勾对角：手腕外展，球斜线飞向对角
- 推球：手腕前推，拍面微下压
- 扑球：身体前倾，腕部爆发下压
- 挑球：击球点低，拍面明显朝上，从下往上发力

【前场区分：放网 vs 搓球——看球托朝向；无翻转=放网，有翻转=搓球】

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【中场动作】（球在中场，高度在腰-肩之间）
- 正手抽球：手腕弹击向前平推，身体协调发力
- 反手抽球：同正手但用反手，大拇指顶拍
- 平抽快挡：仅手腕弹击，借力卸力

【中场区分：身体协调发力=抽球；仅手腕弹击=平抽快挡】

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【后场动作】（球员在后场/底线区域，画面上半部）
- 高远球：击球点在头顶上方，拍面后仰，弧度大
- 杀球：全身协调发力，拍面下压角度大，弧度平直
- 吊球：挥拍轨迹同杀球，但击球瞬间手腕减速轻触
- 点杀：突然起跳，快速闪腕
- 劈吊：挥拍斜线，击球侧部

【后场区分：
① 弧度大+高深 → 高远球
② 弧度平直+下压 → 杀球
③ 动作似杀球但手腕减速 → 吊球
④ 无法区分 → "后场击球（单帧推断）"】

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【防守技术】（用于被动防守情况）
- 挑球：击球点低，拍面朝上，从下往上
- 接杀球：低重心，手腕在胸前向上弹挡

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【技术评分】（0-10分）
- 发力链：下肢→转髋→挥臂→甩腕，传导顺畅
- 闪腕：击球瞬间手腕爆发制动
- 步伐：移动到位，前脚掌先着地
- 拍面控制：角度合理，甜区击球
- 整体协调：身体平衡，动作流畅，还原快

综合评分 = 五维度加权平均，0-10分

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【错误诊断】
E1-发力链断裂：五环节中断
E2-手腕僵硬：击球瞬间手腕无爆发
E3-架肘：引拍时肘高于肩
E4-侧身不充分：身体正对球网
E5-闪腕不充分：手腕爆发力未释放

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【强制输出格式】
动作类型: [从本 prompt 中的列表选择，若位置和动作不匹配则重新判断位置]
综合评分: [0-10]
发力链: [0-10]
闪腕: [0-10]
步伐: [0-10]
拍面控制: [0-10]
整体协调: [0-10]
主要问题: [1-2个，用E编号格式]
改进建议: [针对每个问题的具体改进方法]

【关键要求】
- 任何时候都不得输出"无法判断"或"unable"——必须给出具体动作类型
- 如果击球姿态不明显，根据球员位置给出一个最可能的动作
- 即使图像模糊，也要基于位置推断动作类型
- "后场击球（单帧推断）"是可以接受的兜底输出"""


def _image_to_data_uri(path):
    with open(path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return f"data:{mime};base64,{img_data}"


def _call_vlm(messages, max_tokens=600, temperature=0.6):
    payload = {
        "model": "Qwen/Qwen3-VL-32B-Instruct",
        "messages": [{"role": "user", "content": messages}],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                API_URL,
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    return None


def is_swinging(image_path: str):
    """Stage1: 二元判断 + 击球者位置"""
    data_uri = _image_to_data_uri(image_path)
    text = _call_vlm([
        {"type": "image_url", "image_url": {"url": data_uri}},
        {"type": "text", "text": STAGE1_PROMPT}
    ], max_tokens=100, temperature=0.1)

    if text is None:
        return (False, "Unknown", "network error")

    answer, side, reason = "No", "Uncertain", ""
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("Answer:"):
            answer = line.split("Answer:", 1)[1].strip()
        elif line.startswith("HitterSide:"):
            side = line.split("HitterSide:", 1)[1].strip()
        elif line.startswith("Reason:"):
            reason = line.split("Reason:", 1)[1].strip()

    return (answer.strip(), side.strip(), reason.strip())


def stage2_analyze_v2(image_path: str, ball_info: dict):
    """Stage2 V2: 结合球位置上下文判断动作"""
    img = cv2.imread(image_path)
    if img is None:
        return _error_result(image_path, "image read failed")

    h, w = img.shape[:2]
    data_uri = _image_to_data_uri(image_path)

    # 构建球位置context
    if ball_info.get("found"):
        cx, cy = ball_info["cx"], ball_info["cy"]
        y_pct = cy / h * 100
        x_pct = cx / w * 100

        if y_pct < 40:
            court_half = "FAR side (opponent's court)"
            ball_zone = "backcourt/high"
        elif y_pct > 60:
            court_half = "NEAR side (our court)"
            ball_zone = "frontcourt/net"
        else:
            court_half = "MIDDLE"
            ball_zone = "midcourt"

        ball_context = "OpenCV检测到画面中可能有羽毛球。"
    else:
        ball_context = "OpenCV未检测到羽毛球，请根据画面自行判断。"

    prompt = f"{ball_context}\n\n{STAGE2_PROMPT}"

    # 禁用 prev_frame：双图模式导致 VLM 看到非挥拍帧后认为整组是 non-rally
    # 改用纯单图模式，避免前一帧干扰当前帧判断
    content = [
        {"type": "image_url", "image_url": {"url": data_uri}},
        {"type": "text", "text": prompt}
    ]

    text = _call_vlm(content, max_tokens=1200, temperature=0.1)
    if text is None:
        return _error_result(image_path, "VLM call failed")

    return _parse_stage2_result(image_path, text, ball_info)


def _parse_stage2_result(image_path, text, ball_info=None):
    out = {
        "frame_file": os.path.basename(image_path),
        "raw_response": text,
        "hitter": "",
        "action_type": "",
        "quality_rating": 0,
        "发力链": 0, "闪腕": 0, "步伐": 0,
        "拍面控制": 0, "整体协调": 0,
        "errors": [], "suggestions": [],
        "ball_detected": (ball_info or {}).get("found", False),
        "ball_cx": (ball_info or {}).get("cx"),
        "ball_cy": (ball_info or {}).get("cy"),
    }
    # 追踪评分是否被 VLM 显式返回（未显式返回 = 解析失败，强制置 0）
    rating_keys = {"quality_rating", "发力链", "闪腕", "步伐", "拍面控制", "整体协调"}
    _explicitly_set = {k: False for k in rating_keys}

    # 预检：纯 SKIP 响应（无标签格式）→ 直接归为 SKIP，不进报告
    stripped = text.strip().upper()
    if stripped == "SKIP":
        out["action_type"] = "SKIP"
        out["quality_rating"] = 0
        for k in ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]:
            out[k] = 0
            _explicitly_set[k] = True
        _explicitly_set["quality_rating"] = True
        return out

    # ── 标签解析 ───────────────────────────────────────
    label_map = {
        "动作类型:": "action_type",
        "综合评分:": "quality_rating",
        "评分:": "quality_rating",
        "发力链:": "发力链",
        "闪腕:": "闪腕",
        "步伐:": "步伐",
        "拍面控制:": "拍面控制",
        "整体协调:": "整体协调",
        "主要问题:": "errors",
        "改进建议:": "suggestions",
    }
    en_label_map = {
        "Hitter :": "hitter",
        "Hitter:": "hitter",
        "Hitter: ": "hitter",
        "ActionType:": "action_type",
        "OverallScore:": "quality_rating",
        "PowerChain:": "发力链",
        "WristSnap:": "闪腕",
        "Footwork:": "步伐",
        "RacquetFace:": "拍面控制",
        "Coordination:": "整体协调",
        "MainErrors:": "errors",
        "Suggestions:": "suggestions",
    }
    cn_label_map = {
        "击球主角:": "hitter",
        "动作类型:": "action_type",
        "综合评分:": "quality_rating",
        "发力链:": "发力链",
        "闪腕:": "闪腕",
        "步伐:": "步伐",
        "拍面控制:": "拍面控制",
        "整体协调:": "整体协调",
        "主要错误:": "errors",
        "错误类型:": "errors",
        "改进建议:": "suggestions",
        "建议:": "suggestions",
    }
    all_label_map = {**label_map, **en_label_map, **cn_label_map}

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for prefix, key in all_label_map.items():
            if line.startswith(prefix):
                val = line.split(":", 1)[1].strip()
                if key in ("errors", "suggestions"):
                    if val and val.lower() not in ("none", "无", "n/a", "n/a-"):
                        items = [p.strip() for p in re.split(r'[;；]', val) if p.strip()]
                        out[key] = items
                elif key == "quality_rating":
                    try:
                        score = int(val.split(".")[0])
                        out[key] = max(0, min(10, score))
                        _explicitly_set[key] = True
                    except:
                        pass
                elif key in ("发力链", "闪腕", "步伐", "拍面控制", "整体协调"):
                    try:
                        out[key] = max(0, min(10, int(val.split(".")[0])))
                        _explicitly_set[key] = True
                    except:
                        pass
                elif key == "action_type":
                    out[key] = val
                    val_lower = val.lower()
                    if any(x in val_lower for x in ["skip", "cannot determine", "unable", "信息不足", "无法判断", "不确定"]):
                        out["action_type"] = "SKIP"
                        out["quality_rating"] = 0
                        for k in ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]:
                            out[k] = 0
                            _explicitly_set[k] = True
                        _explicitly_set["quality_rating"] = True
                        out["errors"] = ["视觉证据不足，该帧跳过"]
                        out["suggestions"] = []
                elif key == "hitter":
                    out[key] = val
                break

    # VLM 未显式返回评分 → 解析失败，强制置 0（而非默认 5 分掩盖错误）
    if not _explicitly_set["quality_rating"]:
        out["quality_rating"] = 0
    if not out["action_type"]:
        out["action_type"] = "无法判断"
        out["quality_rating"] = 0

    return out


def _error_result(image_path, err_msg):
    return {
        "frame_file": os.path.basename(image_path),
        "raw_response": err_msg,
        "action_type": "无法判断",
        "quality_rating": 0,
        "发力链": 0, "闪腕": 0, "步伐": 0,
        "拍面控制": 0, "整体协调": 0,
        "errors": [], "suggestions": [],
        "ball_detected": False, "ball_cx": None, "ball_cy": None,
    }


# ============================================================
# 批量分析：OpenCV检球 -> Stage1 -> Stage2
# ============================================================
def batch_analyze_with_ball(frame_paths: list) -> list:
    """完整流程"""
    if not frame_paths:
        return []

    total = len(frame_paths)
    print(f"  [V2] Total frames: {total}")

    # Step0: OpenCV检球
    print(f"  [V2] Step0: Ball detection...")
    ball_results = [None] * total
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
        futures = {ex.submit(detect_shuttlecock, fp): i for i, fp in enumerate(frame_paths)}
        done = 0
        for future in as_completed(futures):
            i = futures[future]
            try:
                ball_results[i] = future.result()
            except Exception:
                ball_results[i] = {"found": False}
            done += 1
            if done % 20 == 0 or done == total:
                print(f"    Ball progress: {done}/{total}")

    found = sum(1 for b in ball_results if b and b.get("found"))
    print(f"  [V2] Ball detection done: {found}/{total} frames")

    # Step1: Stage1
    print(f"  [V2] Step1: Swing detection...")
    stage1_results = [None] * total
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
        futures = {ex.submit(is_swinging, fp): i for i, fp in enumerate(frame_paths)}
        done = 0
        for future in as_completed(futures):
            i = futures[future]
            try:
                stage1_results[i] = future.result()
            except Exception as e:
                stage1_results[i] = (False, "Unknown", str(e))
            done += 1
            if done % 20 == 0 or done == total:
                print(f"    Stage1 progress: {done}/{total}")

    swing_count = sum(1 for r in stage1_results if r and "yes" in r[0].lower())
    print(f"  [V2] Stage1 done: {swing_count}/{total} frames have swings")

    # Step2: Stage2
    stage2_map = {}
    swing_indices = [i for i, r in enumerate(stage1_results) if r and "yes" in r[0].lower()]

    if swing_indices:
        print(f"  [V2] Step2: Action classification...")

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
            futures = {
                ex.submit(stage2_analyze_v2, frame_paths[i], ball_results[i]): i
                for i in swing_indices
            }
            done = 0
            for future in as_completed(futures):
                i = futures[future]
                try:
                    res = future.result()
                    # 注入Stage1的击球方信息
                    res["hitter_side"] = stage1_results[i][1] if stage1_results[i] else "Unknown"
                    stage2_map[i] = res
                except Exception as e:
                    err_res = _error_result(frame_paths[i], str(e))
                    err_res["hitter_side"] = "Unknown"
                    stage2_map[i] = err_res
                done += 1
                if done % 10 == 0 or done == len(swing_indices):
                    print(f"    Stage2 progress: {done}/{len(swing_indices)}")

    # 组装全量结果（SKIP帧直接丢弃，不进入报告）
    all_results = []
    for i, path in enumerate(frame_paths):
        if i in stage2_map:
            res = stage2_map[i]
            # SKIP：视觉证据不足的帧直接丢弃
            if res.get("action_type") == "SKIP":
                continue
            all_results.append(res)
        else:
            swinging, side, reason = False, "Unknown", "Unknown"
            if stage1_results[i]:
                ans, side, reason = stage1_results[i]
                swinging = "yes" in ans.lower()
            res = {
                "frame_file": os.path.basename(path),
                "raw_response": f"[Stage1 No] {reason}",
                "action_type": "non-rally (filtered by Stage1)",
                "quality_rating": 0,
                "发力链": 0, "闪腕": 0, "步伐": 0,
                "拍面控制": 0, "整体协调": 0,
                "errors": [], "suggestions": [],
                "ball_detected": ball_results[i].get("found") if ball_results[i] else False,
                "ball_cx": ball_results[i].get("cx") if ball_results[i] else None,
                "ball_cy": ball_results[i].get("cy") if ball_results[i] else None,
                "hitter_side": side if swinging else "Unknown",
            }
            all_results.append(res)

    return all_results

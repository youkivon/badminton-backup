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
MAX_CONCURRENT = 5
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
# Stage2 Prompt：使用 V1 分类体系式 prompt（VLM 能正常分类）
# V2 的 OpenCV 球检测 context 逻辑保留，但换掉导致 SKIP 的排除式 prompt
# ============================================================
STAGE2_PROMPT = r"""你是一位专业的羽毛球 AI 教练。请严格按"位置优先"策略分析视频帧：

【核心原则：位置决定动作，不允许矛盾判断】
Step 1→ 先看球员站在哪里（前场/中场/后场）
Step 2→ 再根据位置约束确定动作类型
违反以上原则的判断视为错误。

已知信息：Stage1 已确认画面中有球员正在挥拍或准备击球。

⚠️ 【重要提醒】：
- 球员没有真实的挥拍动作（拍子静止、仅手持拍站立、正在走路/拣球/闲聊）→ 直接输出"non-rally (unable to analyze)"
- 位置判断是所有动作判断的前提，位置和动作类型必须匹配

以下为分析知识库：

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第一步：发球识别——严格的四项同时满足】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
必须同时满足以下全部四项，才判定为发球（任一不满足→进入第二步）：
① 球员在端线/近端线位置
② 羽毛球在球员手中/刚离手/球在抛物线上升段（未到达高点）
③ 拍子正在向上挥动（手腕/前臂向上刷），拍头高于手腕
④ 球员双脚在地面上（无明显蹬地起跳）

【第一步补充：无效帧一票否决】
在完成任何动作判断之前，先检查以下否决条件（满足则直接输出"non-rally (unable to analyze)"，不继续往下判断）：
❌ 球员没有真实的挥拍动作（拍子静止、仅手持拍站立、正在走路/拣球/闲聊）

注意：若图像模糊、部分身体被遮挡或判断困难，应尽力推断动作类型，不得直接输出 non-rally。

【发球子类型】
- 正手发高远球：拍子从身体侧后向上挥至最高点，手腕爆发力击打球底
- 反手发网前球：拇指/手腕向前轻推，拍面横切，球弧度平

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第二步：击球分类——先定位球员位置，再判断动作】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ 【最关键的约束：位置决定动作范围】

在判断动作类型之前，必须先看球员站在哪里：

判断方法（视觉线索）：
- 球员在画面**下半部、占画面比例大**、四肢较粗 → **前场/网前**
- 球员在画面**上半部、占画面比例小**、背景有完整广告牌/墙壁 → **后场/底线**
- 介于两者之间 → **中场**

重要约束（违反则判断必错）：
- 球员在前场（靠近球网）→ 不可能是：高远球、杀球、吊球、点杀、劈杀
- 球员在后场（靠近底线）→ 不可能是：放网前球、搓球、勾对角、扑球
- 如果你判断的位置和动作类型矛盾 → 立即重新检查！

■ 前场技术（球员在**网前/靠近球网**，画面下半部）
- 放网前球：击球点略高于网顶，拍面极轻触球托，无明显摩擦
- 搓球：手指/手腕有前后捻动，球过网后翻滚或不转
- 滑拍：触球瞬间拍面横向滑动，球产生侧旋
- 勾对角：手腕外展，球斜线飞向对角网边
- 推球：手腕前推，拍面微下压，球速快弧线平
- 扑球：身体前倾压网，腕部爆发下压，力量最大
- 拦吊：网前借力轻挡，手腕弹击
- 挑球：击球点低（膝以下），拍面明显朝上，从下往上发力

【前场区分：放网 vs 搓球——看相邻帧；球托朝向无翻转=放网，有翻转=搓球】

■ 中场技术（球在中场区域，高度在肩以下/腰以上）
- 正手抽球：击球点平或偏低，拍面正对球网，手腕弹击向前平推
- 反手抽球：同正手抽球但用反手，大拇指顶拍
- 平抽快挡：中场近身球，拍面快速平挡，借力卸力

【中场区分：身体有蹬地转髋协调发力=抽球；身体基本静止仅手腕弹击=平抽快挡】

■ 后场技术（球员在**后场/底线**，靠近画面背景上半部）
- 正手高远球：击球点在头顶上方，手臂伸直向上挥，拍面后仰
- 反手高远球：同正手高远球但用反手
- 正手杀球：全身协调发力，蹬腿+转髋+挥臂+甩腕，拍面下压角度大
- 反手杀球：同正手杀球但用反手
- 点杀：突然起跳，快速闪腕
- 劈吊：挥拍斜线，击球侧部
- 吊球：杀球挥拍轨迹，但击球瞬间手腕减速轻触

【后场区分：
① 球弧度：直线/小抛物线下坠=杀球；大抛物线=吊球；更高更深=高远球
② 若无法区分，输出"后场击球（单帧推断）"】

■ 防守技术
- 挑球：击球点低（膝以下），拍面明显朝上，从下往上发力
- 接杀球：低重心，手腕在胸前/身侧向上或向前弹挡

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第三步：技术评分】（0-10分）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 发力链：下肢蹬地→转髋→送肩→挥臂→甩腕，力量传导顺畅无断层
2. 闪腕：击球瞬间手腕甩鞭制动充分，爆发力集中
3. 步伐：移动到位及时，最后一步前脚掌先着地
4. 拍面控制：击球拍面角度合理，甜区击球率高
5. 整体协调：身体平衡、动作流畅、发力时机准确、还原快

综合评分：五维度加权平均，0-10分。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第四步：错误诊断】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【杀球/正手杀球/反手杀球】
E1-杀球发力链断层：蹬腿→转髋→送肩→挥臂→甩腕五环节中断
E3-杀球架肘：引拍时肘关节高于肩关节
E5-点杀闪腕不充分：手腕爆发力未释放

【高远球】
E1-高远球发力不充分：仅用手臂发力，下肢力量未上传
E4-侧身引拍不充分：身体正对球网

【吊球】
E1-吊球击球瞬间减速不够：动作接近杀球

【平抽快挡/抽球】
E1-平抽大臂发力：仅大臂抡拍
E5-反手抽球大拇指顶拍不足

【放网前球】
E1-放网手腕僵硬
E2-放网拍面上仰
E3-放网击球点过低

【搓球】
E1-搓球旋转不够
E2-搓球击球点偏后

【扑球】
E1-扑球击球点偏后
E2-扑球过于用力

【挑球】
E1-挑球仅手臂发力
E2-挑球击球点太低

【接杀球】
E1-接杀全身发力：借力不足

【发球】
E1-发球挥拍轨迹不完整
E2-发球击球点偏低

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式】（严格按此顺序）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
动作类型: [从以上列表选择]
综合评分: [0-10]
发力链: [0-10]
闪腕: [0-10]
步伐: [0-10]
拍面控制: [0-10]
整体协调: [0-10]
主要问题: [1-2个，格式：E编号+错误名称]
改进建议: [针对每个问题的具体改进方法]"""


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
        "quality_rating": 5,
        "发力链": 5, "闪腕": 5, "步伐": 5,
        "拍面控制": 5, "整体协调": 5,
        "errors": [], "suggestions": [],
        "ball_detected": ball_info.get("found") if ball_info else False,
        "ball_cx": ball_info.get("cx") if ball_info else None,
        "ball_cy": ball_info.get("cy") if ball_info else None,
    }

    # 预检：纯SKIP响应（无标签格式）→ 归为无法判断，不丢弃
    stripped = text.strip().upper()
    if stripped == "SKIP":
        out["action_type"] = "无法判断"
        out["quality_rating"] = 0
        for k in ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]:
            out[k] = 0
        out["errors"] = ["视觉证据不足，无法确定动作类型"]
        out["suggestions"] = []
        return out

    # 中文
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

    # 英文备用
    # 英文标签（含空格变体，Hitter: 有时带空格）
    en_label_map = {
        "Hitter :": "hitter",  # 带空格版本
        "Hitter:": "hitter",
        "Hitter: ": "hitter",  # 尾部空格
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
    # 中文标签
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

    current_key = None
    current_list = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # 检查是否是新字段开头
        matched = False
        for prefix, key in all_label_map.items():
            if line.startswith(prefix):
                val = line.split(":", 1)[1].strip()

                if key in ("errors", "suggestions"):
                    if val and val.lower() not in ("none", "无", "n/a", "n/a-"):
                        # 兼容中英文分隔符
                        items = [p.strip() for p in re.split(r'[;；]', val) if p.strip()]
                        out[key] = items
                elif key == "quality_rating":
                    try:
                        score = int(val.split(".")[0])
                        out[key] = max(0, min(10, score))
                    except:
                        pass
                elif key in ("发力链", "闪腕", "步伐", "拍面控制", "整体协调"):
                    try:
                        out[key] = max(0, min(10, int(val.split(".")[0])))
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
                        out["errors"] = ["视觉证据不足，该帧跳过"]
                        out["suggestions"] = []
                elif key == "hitter":
                    out[key] = val

                matched = True
                break

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
                stage1_results[i] = (False, "Unknown", str(e), "")
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

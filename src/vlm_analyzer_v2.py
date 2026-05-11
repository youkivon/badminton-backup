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
    '- Yes = actively swinging, racquet in motion, follow-through\n'
    '- No = standing, walking, talking, picking up shuttle, pre-serve toss, waiting\n'
    '- Near = hitter on near side (bottom half of image, large in frame)\n'
    '- Far = hitter on far side (top half of image, small in frame)\n'
    '- If uncertain, answer No'
)

# ============================================================
# Stage2 Prompt V4：严格动作分类 + 位置约束 + 发球识别
# ============================================================
STAGE2_PROMPT_V2 = r"""你是一位专业的羽毛球教练。请分析图片中球员的击球动作。

【核心原则：宁可漏判，不能误判】
如果图片中球不可见、挥拍轨迹不清晰、或动作存在明显疑义无法判断，必须直接输出 SKIP，不得擅自编造动作类型。
严禁在没有足够视觉证据的情况下输出任何击球动作描述。
【重要：判断前先排除法】
在输出动作类型之前，必须依次问自己：
1. 发球？→ 击球手在端线后，拍头向上或向后倾斜，双脚在地面，球刚离手或即将离手
2. 杀球？→ 拍面明显朝下（朝地面），挥拍轨迹从上往下，身体有蹬地/跳跃发力感
3. 高远球？→ 拍面朝后（背对球网方向），球在击球手身后或头顶上方
4. 吊球？→ 挥拍向下但柔和，拍面有切动，力量轻
5. 平抽？→ 挥拍基本水平，拍面正对球网，身体站直
6. 挑球？→ 拍面从下往上挥，力量轻
7. 放网/搓球？→ 挥拍轻柔，身体弯腰前倾，拍面接近球网
8. 推球？→ 挥拍短促向前，力量轻

【发球识别标准——必须同时满足以下全部条件才判发球】：
① 击球手位于端线附近或发球线后
② 球刚离手或仍在手上（可见手持羽毛球）
③ 拍头向上或明显朝后
④ 双脚都在地面上（无跳跃）
若有任何一条不满足，即使其他条件符合也不判为发球。

【位置约束——违反以下任一条，动作类型必须重新判断】：
- 近端球员（画面底部/大尺寸）不可能打出杀球（除非他明显跳起且拍面朝下）
- 球员身体弯腰前倾、大臂抬起举拍 → 不可能是杀球/高远球
- 拍面明显朝上 → 可能是挑球/高远球/放网，不是杀球
- 击球手在网前（画面下半部分且靠近球网）→ 不可能是杀球/高远球，最可能是放网/搓球/扑球

【输出格式】（严格按此顺序，中文输出）
Hitter: [Near/Far] [颜色+性别]
ActionType: [动作类型]
OverallScore: [0-10整数]
PowerChain: [0-10整数]
WristSnap: [0-10整数]
Footwork: [0-10整数]
RacquetFace: [0-10整数]
Coordination: [0-10整数]
MainErrors: [错误代码，无则写：无明显错误]
Suggestions: [中文改进建议]"""


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


def stage2_analyze_v2(image_path: str, ball_info: dict, prev_frame_path: str = ""):
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

    prompt = f"{ball_context}\n\n{STAGE2_PROMPT_V2}"

    if prev_frame_path and os.path.exists(prev_frame_path):
        prev_uri = _image_to_data_uri(prev_frame_path)
        content = [
            {"type": "image_url", "image_url": {"url": prev_uri}},
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": prompt}
        ]
    else:
        content = [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": prompt}
        ]

    text = _call_vlm(content, max_tokens=1200, temperature=0.6)
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

    # 预检：纯SKIP响应（无标签格式）→ 归为unable to determine，不丢弃
    stripped = text.strip().upper()
    if stripped == "SKIP":
        out["action_type"] = "unable to determine"
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
        out["action_type"] = "unable to determine"
        out["quality_rating"] = 0

    return out


def _error_result(image_path, err_msg):
    return {
        "frame_file": os.path.basename(image_path),
        "raw_response": err_msg,
        "action_type": "unable to determine",
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
        prev_map = {i: frame_paths[i - 1] if i > 0 else "" for i in swing_indices}

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
            futures = {
                ex.submit(stage2_analyze_v2, frame_paths[i], ball_results[i], prev_map[i]): i
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

# -*- coding: utf-8 -*-
"""
羽毛球视频分析 VLM 模块 V2
结合 OpenCV 羽毛球检测 + VLM 动作分析

流程：
  1. OpenCV 检测球位置 → 判断球在哪个半场（near/far, front/middle/back）
  2. VLM Stage1：问"是否有挥拍 + 哪边在挥拍"
  3. VLM Stage2：传入球位置context，让VLM结合场地上下文判断动作
"""
import os, json, time, cv2
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
# Stage2 Prompt V2：结合球位置上下文
# ============================================================
STAGE2_PROMPT_V2 = r"""You are a professional badminton AI coach. Analyze this video frame with court context.

KNOWN INFO from OpenCV ball detection:
- Ball pixel position: (cx, cy)
- If cy < 40% of image height -> ball is on FAR side (opponent's court)
- If cy > 60% of image height -> ball is on NEAR side (our court)
- If 40% < cy < 60% -> ball at MIDDLE

CRITICAL RULE: The hitter MUST be on the same side as the ball. If ball is far side (cy small), hitter is also on far side -> only BACKCOURT techniques are possible.

【Position Rules】
- Player in bottom half of image, large, thick limbs -> FRONTCOURT/NEAR
- Player in top half of image, small, ads/background visible -> BACKCOURT/FAR
- Between -> MIDDLE

【CRITICAL CONSTRAINTS - Violate these and your answer is wrong】
- Hitter at FRONTCOURT (near net) -> CANNOT be: smash, clear, drive, drop shot
- Hitter at BACKCOURT (far baseline) -> CANNOT be: net shot, drop, push, block
- Ball at FAR side (cy < 40%) + hitter at FAR -> MUST be BACKCOURT technique (smash/clear/drive/drop)
- Ball at NEAR side (cy > 60%) + hitter at NEAR -> frontcourt technique possible

【Backcourt Techniques (hitter at backcourt / far side)】
- Smash: full body coordination, leg drive + hip rotation + arm swing + wrist snap, large downward angle
- Clear: high arc, overhead, arm extended upward
- Drive: flat, fast, horizontal trajectory
- Drop shot: same swing as smash but decelerate at impact, gentle touch

【Frontcourt Techniques (hitter at net / near side)】
- Net shot: tap ball just above net, minimal spin
- Slice/net shot: wrist/finger rotation, ball tumbles
- Push: wrist forward, slight downward face, fast
- Lift/clear: low contact point, under-the-ball, lift upward
- Block: deflect at net with minimal swing

【Serve】(only if cy > 60% AND player near baseline AND ball in hand/upward)
- Short serve: flick or push forward
- High serve: overhead lift to backcourt

━━━━━━━━━━━━━━━━━━━━━━━━━━
【Scoring (0-10)】
1. Power chain: leg drive -> hip -> shoulder -> arm -> wrist, smooth transfer
2. Wrist snap: explosive wrist deceleration at impact
3. Footwork: quick recovery, toes first landing
4. Racquet face: correct angle, sweet spot contact
5. Overall: balance, flow, timing, quick recovery

━━━━━━━━━━━━━━━━━━━━━━━━━━
【Error Codes】
Smash: E1-power chain break, E3-raised elbow, E5-insufficient wrist snap
Clear: E1-insufficient power, E4-poor body rotation
Net shot: E1-stiff wrist, E2-racquet face open, E3-low contact point
Slice: E1-insufficient rotation, E2-back contact point
Lift: E1-arm only, E2-too low contact
Serve: E1-incomplete swing, E2-low contact point

━━━━━━━━━━━━━━━━━━━━━━━━━━
【Output Format (strict order)】
ActionType: [from above list]
OverallScore: [0-10]
PowerChain: [0-10]
WristSnap: [0-10]
Footwork: [0-10]
RacquetFace: [0-10]
Coordination: [0-10]
MainErrors: [1-2 errors, format: Ecode-description]
Suggestions: [specific improvement methods]"""


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

    return ("Yes" in answer or "yes" in answer.lower(), side, reason, text)


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

        ball_context = (
            f"OpenCV Ball Detection: pixel=({cx},{cy}), relative=({x_pct:.0f}%,{y_pct:.0f}%), "
            f"Ball on {court_half}, {ball_zone}."
        )
    else:
        ball_context = "Ball NOT detected in frame."

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

    text = _call_vlm(content, max_tokens=600, temperature=0.6)
    if text is None:
        return _error_result(image_path, "VLM call failed")

    return _parse_stage2_result(image_path, text, ball_info)


def _parse_stage2_result(image_path, text, ball_info=None):
    out = {
        "frame_file": os.path.basename(image_path),
        "raw_response": text,
        "action_type": "",
        "quality_rating": 5,
        "发力链": 5, "闪腕": 5, "步伐": 5,
        "拍面控制": 5, "整体协调": 5,
        "errors": [], "suggestions": [],
        "ball_detected": ball_info.get("found") if ball_info else False,
        "ball_cx": ball_info.get("cx"),
        "ball_cy": ball_info.get("cy"),
    }

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
    en_label_map = {
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

    all_label_map = {**label_map, **en_label_map}

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
                        items = [p.strip() for p in val.split(";") if p.strip()]
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
                    if any(x in val for x in ["cannot determine", "unable", "信息不足"]):
                        out["quality_rating"] = 0
                        for k in ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]:
                            out[k] = 0

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

    swing_count = sum(1 for r in stage1_results if r and r[0])
    print(f"  [V2] Stage1 done: {swing_count}/{total} frames have swings")

    # Step2: Stage2
    stage2_map = {}
    swing_indices = [i for i, r in enumerate(stage1_results) if r and r[0]]

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

    # 组装全量结果
    all_results = []
    for i, path in enumerate(frame_paths):
        if i in stage2_map:
            all_results.append(stage2_map[i])
        else:
            swinging, side, reason = False, "Unknown", "Unknown"
            if stage1_results[i]:
                swinging, side, reason, _ = stage1_results[i]
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

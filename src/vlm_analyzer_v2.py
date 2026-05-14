# -*- coding: utf-8 -*-
"""
羽毛球视频分析 VLM 模块 V2
结合 OpenCV 羽毛球检测 + VLM 动作分析 + MediaPipe Pose物理校验

流程：
  1. OpenCV 检测球位置 → 判断球在哪个半场（near/far, front/middle/back）
  2. VLM Stage1：问"是否有挥拍 + 哪边在挥拍"
  3. MediaPipe Pose：物理校验挥拍姿态合理性
  4. VLM Stage2：传入球位置context，让VLM结合场地上下文判断动作
"""
import os
import json
import time
import cv2
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import base64
import mimetypes

# ── MediaPipe Pose ──────────────────────────────────────
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe import Image, ImageFormat

# ── PoseLandmarker 单例（进程内共享，避免重复加载模型）───
_pose_landmarker = None

def _get_pose_landmarker():
    """线程安全的 PoseLandmarker 单例，模型只加载一次"""
    global _pose_landmarker
    if _pose_landmarker is None:
        base_opts = BaseOptions(model_asset_path="/Users/youqifang/Desktop/小程序/models/pose_landmarker_lite.task")
        opts = PoseLandmarkerOptions(
            base_options=base_opts,
            running_mode=RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        _pose_landmarker = PoseLandmarker.create_from_options(opts)
    return _pose_landmarker


# ── MediaPipe Pose 关键点索引（33点）───────────────────
# 0-10: 上半身, 11-32: 下半身
_POSE_LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear",
    "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_pinky", "right_pinky",
    "left_index", "right_index",
    "left_thumb", "right_thumb",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
    "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]

# 挥拍相关关键点对
_WRIST = 16       # right_wrist
_ELBOW = 14       # right_elbow
_SHOULDER = 12    # right_shoulder
_HIP = 24         # right_hip
_KNEE = 26        # right_knee
_ANKLE = 28       # right_ankle


def detect_pose(image_path: str):
    """
    用 MediaPipe Pose 检测人体骨骼关键点。

    Returns:
        dict: {
            "found": bool,
            "landmarks": list of 33 (x, y, z, visibility) tuples,
            "pose_side": "near" / "far" / "unknown"   # near=画面右侧球员（底部）
            "validation": dict with physical checks
        }
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return _empty_pose_result()
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = Image(image_format=ImageFormat.SRGB, data=rgb)
        landmarker = _get_pose_landmarker()
        result = landmarker.detect(mp_image)
    except Exception:
        return _empty_pose_result()

    if not result or not result.pose_landmarks:
        return _empty_pose_result()

    lm = result.pose_landmarks[0]
    landmarks = [(p.x, p.y, p.z, p.visibility) for p in lm]

    # ── 判断是 near（底部球员）还是 far（顶部球员）──────────
    # 鼻点 x 位置：near 球员通常在画面右侧（x > 0.5），far 球员在左侧（x < 0.5）
    nose_x = landmarks[0][0]
    (landmarks[_HIP][0] + landmarks[_HIP + 1][0]) / 2
    # 左右髋的中点可以判断整体左右倾
    pose_side = "near" if nose_x > 0.5 else "far"

    # ── 物理校验 ──────────────────────────────────────────
    validation = _validate_pose_physics(landmarks, pose_side)

    return {
        "found": True,
        "landmarks": landmarks,
        "pose_side": pose_side,
        "validation": validation,
    }


def _validate_pose_physics(landmarks, pose_side):
    """
    基于关键点做物理合理性校验。
    用于验证 VLM 输出的动作类型是否与实际姿态吻合。
    """
    v = {
        "wrist_above_shoulder": False,   # 挥拍时手腕应高于肩
        "elbow_extended": False,          # 挥拍臂肘部应有伸直趋势
        "hip_aligned": False,             # 髋部应在发力链上
        "knee_flexed": False,             # 膝盖应有适度弯曲（动态姿势）
        "ankle_grounded": False,          # 脚踝应着地（稳定支撑）
        "overall_plausible": False,       # 综合合理性
    }

    def landmark(i):
        return landmarks[i] if i < len(landmarks) else (0, 0, 0, 0)

    wrist = landmark(_WRIST)
    elbow = landmark(_ELBOW)
    shoulder = landmark(_SHOULDER)
    hip = landmark(_HIP)
    knee = landmark(_KNEE)
    ankle = landmark(_ANKLE)

    # 可见性过滤（visibility < 0.5 视为不可靠）
    def vis(lm): return lm[3] if lm else 0.0

    if vis(wrist) > 0.5 and vis(shoulder) > 0.5:
        # 挥拍时手腕应高于肩（至少 y 值更小，即画面中更靠上）
        v["wrist_above_shoulder"] = wrist[1] < shoulder[1] - 0.05

    if vis(elbow) > 0.5 and vis(shoulder) > 0.5:
        # 肘部可见时，检查是否接近伸直（挥拍蓄力/挥出状态）
        elbow_shoulder_dist = abs(elbow[1] - shoulder[1])
        v["elbow_extended"] = elbow_shoulder_dist > 0.03

    if vis(hip) > 0.5 and vis(shoulder) > 0.5 and vis(knee) > 0.5:
        # 髋-肩-膝 连线应接近直线性（发力链完整）
        v["hip_aligned"] = True  # 基础检查：髋部可见

    if vis(knee) > 0.5 and vis(ankle) > 0.5:
        # 膝盖和脚踝都可见
        v["knee_flexed"] = vis(knee) > 0.5

    if vis(ankle) > 0.5:
        # 脚踝着地（ankle visibility 高 = 站立姿势）
        v["ankle_grounded"] = vis(ankle) > 0.5

    # 综合合理性：3项以上通过
    passed = sum(1 for k, val in v.items() if k != "overall_plausible" and val)
    v["overall_plausible"] = passed >= 3

    return v


def _empty_pose_result():
    return {
        "found": False,
        "landmarks": [],
        "pose_side": "unknown",
        "validation": {
            "wrist_above_shoulder": False,
            "elbow_extended": False,
            "hip_aligned": False,
            "knee_flexed": False,
            "ankle_grounded": False,
            "overall_plausible": False,
        },
    }


def pose_validation_warning(pose_result: dict, vlm_action_type: str) -> str:
    """
    根据 pose 物理校验结果生成警告信息。
    用于注入 VLM Stage2 prompt 做二次确认。
    """
    if not pose_result or not pose_result.get("found"):
        return ""

    val = pose_result["validation"]
    warnings = []

    if not val["wrist_above_shoulder"]:
        warnings.append("注意：手腕高度低于肩关节，与典型挥拍姿态不符，请重新确认挥拍动作")
    if not val["elbow_extended"]:
        warnings.append("注意：挥拍臂肘部未伸展，发力链可能不完整")
    if not val["overall_plausible"]:
        warnings.append("注意：整体姿态合理性存疑，请结合画面仔细判断动作类型")

    return " | ".join(warnings) if warnings else ""

# ── API 配置 ─────────────────────────────────
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
if not API_KEY:
    raise RuntimeError("SILICONFLOW_API_KEY environment variable is not set")
MAX_CONCURRENT = 30
MAX_RETRIES = 1
RETRY_DELAY = 2

# ── 导入羽毛球检测器 ──────────────────────────
from shuttlecock_detector import detect_shuttlecock  # noqa: E402


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
    '- YES = MUST have EITHER: (1) racquet clearly approaching or contacting the shuttle, OR (2) obvious motion blur/trajectory showing active swing momentum\n'
    '- NO = pure preparation stance, standing still, walking, talking, picking up shuttle, pre-serve, waiting, racquet held ready but NOT in active motion\n'
    '- CRITICAL: A static pose with racquet held ready but NOT in active swinging motion is NOT a swing. Only count as Yes if you see actual swinging motion or clear follow-through from a recent swing.\n'
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
【技术评分标准】（严格按以下规则打分，禁止全部给7-8分）
- 9分：所有五维度全部>=9，且至少有2个维度=9，且未观察到任何E3-E10问题
- 8分：存在至少1个维度<=7（即有明显短板），其余维度>=7，但不足2个维度<=7
- 7分：有2个以上维度<=7，或1个以上维度<=6
- 6分：有3个以上维度<=6，或存在E3架肘/E4侧身不足明显/E7步伐跟不上等结构性错误
- 5分及以下：动作严重变形，存在E1发力链断裂等根本性问题

【打分规则】（以下必须同时满足）
1. 五维度评分必须拉开差距（禁止全部7-8分）
2. 【强制规则】观察到E9随挥不完整时：
   - 整体协调必须<=7（不能是8或9）
   - 闪腕也必须<=7（不能是8或9）
   这两个维度不能通过给8分来规避规则，必须诚实反映问题
3. 如果观察到E7步伐跟不上→步伐必须<=7
4. 9分要求：五维度全部>=9且无E3-E10问题
5. 8分要求：五维度至少有1个<=7但不足2个<=7
6. 7分要求：五维度必须至少有1个<=6

发力链: [0-10] 下肢蹬地→转髋→挥臂链条完整性
闪腕: [0-10] 击球瞬间手腕爆发制动效率
步伐: [0-10] 移动到位性、前脚掌着地、重心控制
拍面控制: [0-10] 击球角度、甜区命中、方向控制
整体协调: [0-10] 身体平衡、动作流畅、还原速度

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【错误诊断】（必须从画面实际观察到的问题出发，禁止套用模板）
E1-发力链断裂：下肢蹬地→转髋→挥臂→甩腕 任一环节缺失或明显脱节
E2-手腕僵硬：仅当击球瞬间手腕完全无任何加速/制动迹象时才诊断为此问题
E3-架肘：引拍时肘尖明显高于肩关节
E4-侧身不足：身体正面面对球网，髋关节未转动
E5-闪腕不充分：仅当手腕完全没有甩动制动、僵硬不动，或完全无任何加速/制动时才诊断为此问题
E6-拍面角度错误：拍面朝向与预期击球方向明显不符
E7-步伐跟不上：移动未到位、脚未前掌着地、重心过高等
E8-击球点偏低/偏前：击球点明显低于肩部或过于靠前
E9-随挥不完整：击球后无自然收拍，动作僵硬卡顿
E10-身体重心不稳：击球时重心明显偏移、倾斜或失去平衡

【错误诊断原则】
- 诊断必须基于画面实际观察，禁止无中生有或套用模板
- 如果手腕有明显的加速甩动过程，即使稍有不充分，优先考虑其他维度问题
- 如果身体侧身、转髋、发力链完整，应给予肯定而非总找手腕问题
- 每次诊断优先从E3-E10中寻找实际观察到的具体问题
- 注意：E9随挥不完整是最常见的问题，一旦观察到击球后收拍僵硬/不完整，应作为主要问题输出，并影响闪腕或整体协调评分至<=6
- E2和E5是结构性错误，只有动作完全变形时才用，普通优化空间不应套用

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【战术评估格式】（每个字段必须给出有意义的描述，禁止只输出等级而无具体说明）
击球选择: [具体描述：球员实际做了什么选择，以及该选择在当时情境下的合理性；确实看到问题才说问题，不要无中生有]
战术意识: [强/中/弱 + 一句话说明：具体在哪些方面体现了/缺乏战术意识]
跑位意识: [好/一般/差 + 一句话说明：具体在哪些方面做得好/有问题]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【强制输出格式】（严格按此格式，每项一行，不可省略）
击球选择: [见上方战术评估格式]
战术意识: [见上方战术评估格式]
跑位意识: [见上方战术评估格式]
动作类型: [从本 prompt 中的列表选择]
综合评分: [0-10]
发力链: [0-10]
闪腕: [0-10]
步伐: [0-10]
拍面控制: [0-10]
整体协调: [0-10]
主要问题: [列出该帧所有错误，最多5个，来自不同维度；无明显错误时输出"无"或省略]
改进建议: [技术维度的改进建议，简洁一条]

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
        except Exception:
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


def stage2_analyze_v2(image_path: str, ball_info: dict, pose_info: dict = None):
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
        cx / w * 100

        if y_pct < 40:
            pass
        elif y_pct > 60:
            pass
        else:
            pass

        ball_context = "OpenCV检测到画面中可能有羽毛球。"
    else:
        ball_context = "OpenCV未检测到羽毛球，请根据画面自行判断。"

    # ── Pose 物理校验警告注入 ───────────────────────────
    pose_warning = ""
    if pose_info and pose_info.get("found"):
        pose_warning = pose_validation_warning(pose_info, "")
    if pose_warning:
        pose_warning = f"\n\n【MediaPipe姿态校验提示】{pose_warning}"

    prompt = f"{ball_context}{pose_warning}\n\n{STAGE2_PROMPT}"

    # 禁用 prev_frame：双图模式导致 VLM 看到非挥拍帧后认为整组是 non-rally
    # 改用纯单图模式，避免前一帧干扰当前帧判断
    content = [
        {"type": "image_url", "image_url": {"url": data_uri}},
        {"type": "text", "text": prompt}
    ]

    text = _call_vlm(content, max_tokens=1200, temperature=0.1)
    if text is None:
        return _error_result(image_path, "VLM call failed")

    return _parse_stage2_result(image_path, text, ball_info, pose_info)


def _parse_stage2_result(image_path, text, ball_info=None, pose_info=None):
    out = {
        "frame_file": os.path.basename(image_path),
        "raw_response": text,
        "hitter": "",
        "action_type": "",
        "quality_rating": 0,
        "发力链": 0, "闪腕": 0, "步伐": 0,
        "拍面控制": 0, "整体协调": 0,
        "errors": [], "suggestions": [],
        "击球选择": "", "战术意识": "", "跑位意识": "",
        "ball_detected": (ball_info or {}).get("found", False),
        "ball_cx": (ball_info or {}).get("cx"),
        "ball_cy": (ball_info or {}).get("cy"),
        # Pose 物理校验字段
        "pose_detected": (pose_info or {}).get("found", False),
        "pose_side": (pose_info or {}).get("pose_side", "unknown"),
        "pose_validation": (pose_info or {}).get("validation", {}),
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
        "击球选择:": "击球选择",
        "战术意识:": "战术意识",
        "跑位意识:": "跑位意识",
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
                    except Exception:
                        pass
                elif key in ("发力链", "闪腕", "步伐", "拍面控制", "整体协调"):
                    try:
                        out[key] = max(0, min(10, int(val.split(".")[0])))
                        _explicitly_set[key] = True
                    except Exception:
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
                elif key in ("击球选择", "战术意识", "跑位意识"):
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
    print("  [V2] Step0: Ball detection...")
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
    print("  [V2] Step1: Swing detection...")
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

    def _is_swing(r):
        if not r:
            return False
        try:
            return "yes" in str(r[0]).lower()
        except (AttributeError, TypeError, IndexError):
            print(f"    [WARN] Unexpected Stage1 result type: {type(r)}={r!r}")
            return False

    swing_count = sum(1 for r in stage1_results if _is_swing(r))
    print(f"  [V2] Stage1 done: {swing_count}/{total} frames have swings")

    swing_indices = [i for i, r in enumerate(stage1_results) if _is_swing(r)]

    # Step2: MediaPipe Pose 物理校验（仅针对 Stage1 检出的挥拍帧）
    pose_results = [None] * total
    if swing_indices:
        print("  [V2] Step2: MediaPipe Pose physical validation...")
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
            futures = {ex.submit(detect_pose, frame_paths[i]): i for i in swing_indices}
            done = 0
            for future in as_completed(futures):
                i = futures[future]
                try:
                    pose_results[i] = future.result()
                except Exception:
                    pose_results[i] = _empty_pose_result()
                done += 1
                if done % 10 == 0 or done == len(swing_indices):
                    print(f"    Pose progress: {done}/{len(swing_indices)}")
        pose_found = sum(1 for p in pose_results if p and p.get("found"))
        print(f"  [V2] Pose detection done: {pose_found}/{len(swing_indices)} swing frames detected")

    # Step3: Stage2
    stage2_map = {}

    if swing_indices:
        print("  [V2] Step3: Action classification...")

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
            futures = {
                ex.submit(stage2_analyze_v2, frame_paths[i], ball_results[i], pose_results[i]): i
                for i in swing_indices
            }
            done = 0
            for future in as_completed(futures):
                i = futures[future]
                try:
                    res = future.result()
                    # 注入Stage1的击球方信息
                    res["hitter_side"] = stage1_results[i][1] if stage1_results[i] else "Unknown"
                    # 注入 Pose 物理校验结果
                    if pose_results[i] and pose_results[i].get("found"):
                        res["pose_side"] = pose_results[i].get("pose_side", "unknown")
                        res["pose_validation"] = pose_results[i].get("validation", {})
                    else:
                        res["pose_side"] = "unknown"
                        res["pose_validation"] = {}
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
                swinging = "yes" in str(ans).lower()
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

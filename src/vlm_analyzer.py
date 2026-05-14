# -*- coding: utf-8 -*-
"""
羽毛球视频分析小程序 - VLM 动作分析模块
调用 Qwen/VLM 模型分析视频帧

两阶段策略：
  Stage1 - 二元判断：是否有挥拍？（快速过滤）
  Stage2 - 动作分类：击球类型+评分+诊断（只对 Stage1=是 的帧运行）
"""
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

# VLM 分析用硅基流动 API
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
if not API_KEY:
    raise RuntimeError("SILICONFLOW_API_KEY environment variable is not set")

MAX_CONCURRENT = 5
MAX_RETRIES = 1
RETRY_DELAY = 2


# ============================================================
# Stage1 Prompt：极简二元判断（是否有挥拍）
# ============================================================
STAGE1_PROMPT = """你是一位严谨的羽毛球动作检测专家。请看下面这张视频截图，只回答一个问题：

"画面中是否有球员正在挥拍击球？"

请严格按以下格式回答（不输出其他内容）：
答案：[是/否]
理由：[一句话简短理由]

定义说明：
- "是"：正在挥拍、拍子在空中运动、刚完成挥拍动作仍在收拍
- "否"：站立不动、走路、与同伴说话、拣球/捡球、发球前抛球、仅手持拍等待
- 不确定时必须选"否" """


# ============================================================
# Stage2 Prompt：动作分类（只对 Stage1=是 的帧运行）
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

⚠️ 【多样化强制要求——同一 shot 的连续多帧不得重复相同错误】：
- 当一个错误代码（如 E2）在连续多帧中出现，只在最末帧标记，前帧不重复
- 前场动作不得只输出手腕类错误（E1/E2），必须覆盖步伐到位和击球点问题
- 后场动作不得只输出发力链问题，必须覆盖架肘和闪腕
- 每个 shot 至少尝试覆盖 2 种不同维度的错误（发力/手腕/步伐/拍面/协调）

⚠️ 【动作类型 → 典型错误映射】：先识别动作类型，再针对性查找：

【杀球/正手杀球/反手杀球】→ 必查：发力链(E1)、架肘(E3)、闪腕(E5)
E1-杀球发力链断层：蹬腿→转髋→送肩→挥臂→甩腕五环节中断
E3-杀球架肘：引拍时肘关节高于肩关节
E5-点杀闪腕不充分：手腕爆发力未释放

【高远球】→ 必查：发力链(E1)、侧身(E4)
E1-高远球发力不充分：仅用手臂发力，下肢力量未上传
E4-侧身引拍不充分：身体正对球网

【吊球】→ 必查：减速(E1)
E1-吊球击球瞬间减速不够：动作接近杀球

【平抽快挡/抽球】→ 必查：大臂发力(E1)、拇指顶拍(E5)
E1-平抽大臂发力：仅大臂抡拍
E5-反手抽球大拇指顶拍不足

【放网前球】→ 必查：手腕(E1/E2)、步伐(E6)、击球点(E3)
E1-放网手腕僵硬
E2-放网拍面上仰
E3-放网击球点过低
E6-放网步伐不到位：移动不充分

【搓球】→ 必查：旋转(E1)、击球点(E2)
E1-搓球旋转不够
E2-搓球击球点偏后

【扑球】→ 必查：击球点(E1)、力量(E2)
E1-扑球击球点偏后
E2-扑球过于用力

【挑球】→ 必查：发力(E1)、击球点(E2)
E1-挑球仅手臂发力
E2-挑球击球点太低

【接杀球】→ 必查：借力(E1)
E1-接杀全身发力：借力不足

【发球】→ 必查：轨迹(E1)、击球点(E2)
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
主要问题: [2-3个，来自不同维度的错误，格式：E编号+错误名称]
改进建议: [针对每个问题的具体改进方法]"""


# ============================================================
# Stage1: 二元判断——是否有挥拍？
# ============================================================
def is_swinging(image_path: str) -> tuple:
    """
    极简二元判断：是否有球员在挥拍？
    返回 (is_swinging: bool, reason: str, raw_response: str)
    """
    import base64
    import mimetypes

    with open(image_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()

    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    data_uri = f"data:{mime};base64,{img_data}"

    payload = {
        "model": "Qwen/Qwen3-VL-32B-Instruct",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": STAGE1_PROMPT}
        ]}],
        "temperature": 0.1,
        "max_tokens": 80
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
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()

            answer = "否"
            reason = ""
            for line in text.split("\n"):
                if line.startswith("答案："):
                    answer = line.split("答案：")[1].strip()
                elif line.startswith("理由："):
                    reason = line.split("理由：")[1].strip()

            return ("是" in answer, reason, text)

        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    return (False, f"网络错误:{last_err}", "")


# ============================================================
# Stage2: 动作分类（只对 Stage1=是 的帧运行）
# ============================================================
def stage2_analyze(image_path: str, prev_frame_path: str = "") -> dict:
    """
    动作分类：只对 Stage1 确认有挥拍的帧运行
    prev_frame_path: 可选，前一帧图片路径，用于搓球 vs 放网 的区分
    """
    import base64
    import mimetypes

    with open(image_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()

    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    data_uri = f"data:{mime};base64,{img_data}"

    prompt = STAGE2_PROMPT
    if prev_frame_path and os.path.exists(prev_frame_path):
        with open(prev_frame_path, "rb") as f:
            prev_data = base64.b64encode(f.read()).decode()
        prev_mime = mimetypes.guess_type(prev_frame_path)[0] or "image/jpeg"
        prev_uri = f"data:{prev_mime};base64,{prev_data}"
        compare_note = (
            "【相邻帧比对】前一帧→当前帧。"
            "放网前球：球托朝向基本不变；搓球：球托朝向明显翻转（≥90°）。"
        )
        prompt = f"{compare_note}\n\n{prompt}"
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

    payload = {
        "model": "Qwen/Qwen3-VL-32B-Instruct",
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.6,
        "max_tokens": 600
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
            text = result["choices"][0]["message"]["content"]
            break
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                return _error_result(image_path, f"网络错误 {attempt}次后放弃: {last_err}")

    return _parse_stage2_result(image_path, text)


def _parse_stage2_result(image_path: str, text: str) -> dict:
    out = {
        "frame_file": os.path.basename(image_path),
        "raw_response": text,
        "action_type": "",
        "quality_rating": 0,
        "发力链": 0, "闪腕": 0, "步伐": 0,
        "拍面控制": 0, "整体协调": 0,
        "errors": [], "suggestions": []
    }
    # 追踪评分是否被 VLM 显式返回（未显式返回 = 解析失败，强制置0）
    rating_keys = {"quality_rating", "发力链", "闪腕", "步伐", "拍面控制", "整体协调"}
    _explicitly_set = {k: False for k in rating_keys}

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("动作类型:"):
            out["action_type"] = line.split(":", 1)[1].strip()
            if "无法判断" in out["action_type"] or "信息不足" in out["action_type"]:
                out["quality_rating"] = 0
                for k in ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]:
                    out[k] = 0
                    _explicitly_set[k] = True
                _explicitly_set["quality_rating"] = True
        elif line.startswith("综合评分:") or line.startswith("评分:"):
            try:
                score = int(line.split(":")[1].strip().split(".")[0])
                out["quality_rating"] = max(0, min(10, score))
                _explicitly_set["quality_rating"] = True
            except Exception:
                pass

        elif line.startswith("发力链:"):
            try:
                out["发力链"] = max(0, min(10, int(line.split(":")[1].strip().split(".")[0])))
                _explicitly_set["发力链"] = True
            except Exception:
                pass
        elif line.startswith("闪腕:"):
            try:
                out["闪腕"] = max(0, min(10, int(line.split(":")[1].strip().split(".")[0])))
                _explicitly_set["闪腕"] = True
            except Exception:
                pass
        elif line.startswith("步伐:"):
            try:
                out["步伐"] = max(0, min(10, int(line.split(":")[1].strip().split(".")[0])))
                _explicitly_set["步伐"] = True
            except Exception:
                pass
        elif line.startswith("拍面控制:"):
            try:
                out["拍面控制"] = max(0, min(10, int(line.split(":")[1].strip().split(".")[0])))
                _explicitly_set["拍面控制"] = True
            except Exception:
                pass
        elif line.startswith("整体协调:"):
            try:
                out["整体协调"] = max(0, min(10, int(line.split(":")[1].strip().split(".")[0])))
                _explicitly_set["整体协调"] = True
            except Exception:
                pass
        elif line.startswith("主要问题:"):
            problems = line.split(":", 1)[1].strip()
            if problems and problems not in ["无", "无（", "无（当前帧中球员未处于击球状态"]:
                out["errors"] = [p.strip() for p in problems.split("；") if p.strip()]
        elif line.startswith("改进建议:"):
            out["suggestions"] = [s.strip() for s in line.split(":", 1)[1].strip().split("；") if s.strip()]

    # VLM 未显式返回评分 → 解析失败，强制置 0（而非默认 5 分掩盖错误）
    if not _explicitly_set["quality_rating"]:
        out["quality_rating"] = 0
    if not out["action_type"]:
        out["action_type"] = "无法判断（解析异常）"

    return out


def _error_result(image_path: str, err_msg: str) -> dict:
    return {
        "frame_file": os.path.basename(image_path),
        "raw_response": err_msg,
        "action_type": "无法判断（信息不足）",
        "quality_rating": 0,
        "发力链": 0, "闪腕": 0, "步伐": 0,
        "拍面控制": 0, "整体协调": 0,
        "errors": [], "suggestions": []
    }


# ============================================================
# 旧接口（保留，调用方无需改动）
# ============================================================
def analyze_frame_quick(image_path: str) -> dict:
    """
    前置质检用：快速判断场地可见性和球员数量。
    只做描述，不做动作分析，轻量级调用。
    """
    if not os.path.exists(image_path):
        return {"court_visible": False, "player_count": 0, "error": "file not found"}

    import base64
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = """描述这张图片：
1. 是否能看到羽毛球场地线（边线/端线/中线）？回答"可见"或"不可见"。
2. 图中有几个人？直接说数字。
3. 简要说明场地情况（俯拍/侧拍/斜拍/看不清）。

格式：
场地：可见/不可见
球员：N人
角度：XXX"""

    payload = {
        "model": "Qwen/Qwen3-VL-32B-Instruct",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            {"type": "text", "text": prompt}
        ]}],
        "max_tokens": 100,
        "temperature": 0.1,
    }

    try:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        text = result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return {"court_visible": False, "player_count": 0, "error": str(e)}

    court_visible = "场地：可见" in text or "场地可见" in text
    player_count = 0
    for line in text.split("\n"):
        if "球员：" in line or "球员：" in line:
            import re
            m = re.search(r"(\d+)人", line)
            if m:
                player_count = int(m.group(1))

    return {"court_visible": court_visible, "player_count": player_count, "raw": text}


def analyze_frame_image(image_path: str, player_hint: str = "", prev_frame_path: str = "") -> dict:
    """旧接口：先 Stage1 再 Stage2，等同于 batch_analyze_two_stage 的单帧版"""
    swinging, reason, raw = is_swinging(image_path)
    if not swinging:
        return {
            "frame_file": os.path.basename(image_path),
            "raw_response": f"[Stage1否] {reason}",
            "action_type": "非击球动作（Stage1过滤）",
            "quality_rating": 0,
            "发力链": 0, "闪腕": 0, "步伐": 0,
            "拍面控制": 0, "整体协调": 0,
            "errors": [], "suggestions": []
        }
    return stage2_analyze(image_path, prev_frame_path)


# ============================================================
# 两阶段批量分析
# ============================================================
def batch_analyze_two_stage(frame_paths: list) -> list:
    """
    两阶段分析全流程：
      Stage1：全量帧并行二元判断（是否挥拍）
      Stage2：Stage1=是 的帧并行做动作分类
    返回全量帧结果（顺序与输入一致），stage1=否 的帧标记为"非击球"
    """
    if not frame_paths:
        return []

    total = len(frame_paths)
    print(f"  Stage1 启动（{total}帧二元判断）...")

    # Stage1：全量帧并行
    stage1_results = [None] * total
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        futures = {
            executor.submit(is_swinging, path): i
            for i, path in enumerate(frame_paths)
        }
        done = 0
        for future in as_completed(futures):
            i = futures[future]
            try:
                swinging, reason, raw = future.result()
                stage1_results[i] = (swinging, reason)
            except Exception as e:
                stage1_results[i] = (False, f"异常:{e}")
            done += 1
            if done % 20 == 0 or done == total:
                print(f"  Stage1 进度 {done}/{total}")

    # 统计
    swing_count = sum(1 for r in stage1_results if r and r[0])
    print(f"  Stage1 完毕：{swing_count}/{total} 帧有挥拍，进入 Stage2")

    # Stage2：只对 Stage1=是 的帧分析
    stage2_map = {}  # idx -> result
    swing_indices = [i for i, r in enumerate(stage1_results) if r and r[0]]

    if swing_indices:
        print(f"  Stage2 启动（{len(swing_indices)}帧动作分类）...")
        prev_map = {i: frame_paths[i - 1] if i > 0 else "" for i in swing_indices}

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
            futures = {
                executor.submit(stage2_analyze, frame_paths[i], prev_map[i]): i
                for i in swing_indices
            }
            done = 0
            for future in as_completed(futures):
                i = futures[future]
                try:
                    stage2_map[i] = future.result()
                except Exception as e:
                    stage2_map[i] = _error_result(frame_paths[i], f"Stage2异常:{e}")
                done += 1
                if done % 10 == 0 or done == len(swing_indices):
                    print(f"  Stage2 进度 {done}/{len(swing_indices)}")

    # 组装全量结果
    results = []
    for i, path in enumerate(frame_paths):
        if i in stage2_map:
            results.append(stage2_map[i])
        else:
            swinging, reason = stage1_results[i] or (False, "未知")
            results.append({
                "frame_file": os.path.basename(path),
                "raw_response": f"[Stage1否] {reason}",
                "action_type": "非击球动作（Stage1过滤）",
                "quality_rating": 0,
                "发力链": 0, "闪腕": 0, "步伐": 0,
                "拍面控制": 0, "整体协调": 0,
                "errors": [], "suggestions": []
            })

    return results


# 保留旧接口别名
batch_analyze = batch_analyze_two_stage


def analyze_shots(frames_results: list) -> dict:
    """
    将帧级分析结果聚合为击球序列。
    相邻帧（同球员 + 同动作类型）去重：只保留评分最高的帧，避免同一击球被重复点评。
    """
    NON_SHOT_TYPES = {
        "非击球动作（捡球/死球）",
        "非击球动作（走动/等待/沟通）",
        "非击球动作（准备姿态）",
        "非击球动作",
        "非击球动作（Stage1过滤）",
        "无法判断（信息不足）",
        "无球员在画面中",
        "准备发球",
        "正在发球",
        "non-rally (unable to analyze)",
    }

    # 按时间顺序排列
    sorted_frames = sorted(frames_results, key=lambda r: r.get("time", ""))

    shots = []
    i = 0
    while i < len(sorted_frames):
        r = sorted_frames[i]
        action = r.get("action_type", "")

        if action in NON_SHOT_TYPES or not action:
            i += 1
            continue

        hitter = r.get("hitter_side", "Unknown")
        # 找同球员、同动作类型的连续帧，只保留评分最高的
        group = [r]
        j = i + 1
        while j < len(sorted_frames):
            nr = sorted_frames[j]
            if (nr.get("hitter_side") == hitter
                    and nr.get("action_type") == action
                    and nr.get("action_type") not in NON_SHOT_TYPES):
                group.append(nr)
                j += 1
            else:
                break
        # 取评分最高的帧作为代表
        best = max(group, key=lambda x: x.get("quality_rating", 0))

        shot = {
            "time": best.get("time", ""),
            "action_type": best.get("action_type", ""),
            "quality_rating": best.get("quality_rating", 5),
            "发力链": best.get("发力链", 5),
            "闪腕": best.get("闪腕", 5),
            "步伐": best.get("步伐", 5),
            "拍面控制": best.get("拍面控制", 5),
            "整体协调": best.get("整体协调", 5),
            "errors": best.get("errors", []),
            "suggestions": best.get("suggestions", []),
            "frames": [best["frame_file"]]
        }
        shots.append(shot)
        i = j  # 跳到下一组

    return {"shots": shots}

# -*- coding: utf-8 -*-
"""
羽毛球视频分析小程序 - PDF 报告生成模块
基于 fpdf2，支持球员历史进步对比
"""
import os
import datetime
import re
from collections import Counter

# ── 全局风格配置（字体/颜色/间距全部统一定义，禁止散落数值）────────────
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
ASSETS_FONT = os.path.join(_ASSETS_DIR, "stheiti.ttf")

STYLE = dict(
    # ── 颜色 ───────────────────────────────────────
    C_DARK   = ( 26,  26,  46),
    C_MID    = ( 22,  33,  62),
    C_GREY   = ( 60,  60,  60),
    C_LIGHT  = (100, 100, 100),
    C_RED    = (198,  40,  40),
    C_GREEN  = ( 39, 174,  96),
    C_ORG    = (239, 108,   0),
    C_BLUE   = (  0,  90, 180),
    C_GOLD   = (255, 180,   0),
    C_LINE   = (220, 220, 220),

    # 评分→颜色映射
    TAG_C = {
        0: (198,  40,  40), 1: (198,  40,  40), 2: (198,  40,  40),
        3: (239, 108,   0), 4: (239, 108,   0), 5: (239, 108,   0),
        6: ( 39, 174,  96), 7: ( 39, 174,  96),
        8: (  0,  90, 180), 9: (  0,  90, 180), 10: (  0,  90, 180),
    },

    # ── 字体大小 ───────────────────────────────────
    F_TITLE        = 20,
    F_SECTION      = 13,
    F_LABEL        = 10,
    F_BODY         =  9,
    F_SMALL        =  8.5,
    F_MINI         =  9,
    F_TINY         =  7.5,
    F_CHART_SCORE  = 11,
    F_ACTION       =  9,

    # ── 间距 ───────────────────────────────────────
    LN_BODY  =  4.5,
    LN_SMALL =  4,
    LN_TINY  =  3.5,
    ROW_H    = 10,
    ROW_H_SM =  8,
    ROW_H_LG = 13,

    # ── 卡片布局 ────────────────────────────────────
    IMG_W    = 65,
    IMG_H    = 36,
    CARD_BAR =  3,
    CARD_TOP = 14,
)

# ── 向后兼容别名（旧代码直接用 C_DARK / TAG_C，不改原代码）─────────────
C_DARK  = STYLE["C_DARK"]
C_MID   = STYLE["C_MID"]
C_GREY  = STYLE["C_GREY"]
C_LIGHT = STYLE["C_LIGHT"]
C_RED   = STYLE["C_RED"]
C_GREEN = STYLE["C_GREEN"]
C_ORG   = STYLE["C_ORG"]
C_BLUE  = STYLE["C_BLUE"]
C_GOLD  = STYLE["C_GOLD"]
C_LINE  = STYLE["C_LINE"]
TAG_C   = STYLE["TAG_C"]
# ──────────────────────────────────────────────────────────────────────────

# VLM英文错误代码 → 中文翻译
ERROR_CODE_TRANSLATION = {
    "E1-power chain break":          "E1-发力链断裂",
    "E1-power chain broken":          "E1-发力链断裂",
    "E1-insufficient power":         "E1-发力不足",
    "E1-stiff wrist":                 "E1-手腕僵硬",
    "E1-incomplete follow-through":   "E1-收拍不完整",
    "E2-racquet face open":          "E2-拍面开放",
    "E2-racquet face angle":         "E2-拍面角度不正",
    "E3-raised elbow":               "E3-抬肘过高",
    "E3-elbow too high":              "E3-肘关节抬得过高",
    "E3-excessive elbow lift":         "E3-肘关节过度抬起",
    "E3-low contact point":           "E3-击球点过低",
    "E4-poor body rotation":          "E4-身体转动不足",
    "E4-lack of hip rotation":        "E4-髋关节转动不充分",
    "E5-insufficient wrist snap":     "E5-手腕爆发不足",
    "E5-excessive wrist movement":    "E5-手腕挥动过大",
    "E5-wrist instability":           "E5-手腕支撑不稳定",
    "E6-early trunk rotation":        "E6-躯干过早旋转",
    "E7-ball of foot landing":        "E7-踮脚步着陆",
    "E8-high center of gravity":      "E8-重心过高",
    "E9-no pivot":                    "E9-无重心转移",
    "E10-over执拍":                   "E10-握拍方式不当",
}

from fpdf import FPDF  # noqa: E402
import sys as _sys  # noqa: E402
_sys.path.insert(0, '/tmp')

# 知识库：文件不存在时优雅降级（不阻塞报告生成）
_kb_retriever = None
_kb_enabled = False

try:
    from knowledge_retriever import KnowledgeRetriever
    _kb_enabled = True
except Exception:
    KnowledgeRetriever = None

def _get_retriever():
    global _kb_retriever
    if not _kb_enabled:
        return None
    if _kb_retriever is None:
        try:
            _kb_retriever = KnowledgeRetriever()
        except Exception:
            return None
    return _kb_retriever

# 颜色
C_DARK  = ( 26,  26,  46)
C_MID   = ( 22,  33,  62)
C_GREY  = ( 60,  60,  60)
C_LIGHT = (100, 100, 100)
C_RED   = (198,  40,  40)
C_GREEN = ( 39, 174,  96)
C_ORG   = (239, 108,   0)
C_BLUE  = (  0,  90, 180)
C_GOLD  = (255, 180,   0)
C_LINE  = (220, 220, 220)
TAG_C   = {0: C_RED, 1: C_RED, 2: C_RED, 3: C_ORG, 4: C_ORG, 5: C_ORG, 6: C_GREEN, 7: C_GREEN, 8: C_BLUE, 9: C_BLUE, 10: C_BLUE}

def qlabel(q):
    return ["极差","差","较差","一般","及格","中","良好","较好","优秀","极优","完美"][max(0, min(10, round(float(q))))]

def qtext(q):
    return ["极差","差","较差","一般","及格","中","良好","较好","优秀","极优","完美"][max(0, min(10, round(float(q))))]

def trend_icon(t):
    return {"up": "↑", "down": "↓", "same": "→"}.get(t, "")

def trend_color(t):
    return {"up": C_GREEN, "down": C_RED, "same": C_ORG}.get(t, C_GREY)


class Report(FPDF):
    def header(self): pass
    def footer(self):
        self.set_y(-15)
        self.set_font("STHeiti", size=STYLE["F_MINI"])
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, f"- {self.page_no()} -", align="C")


def _translate_err(text):
    """把VLM英文错误代码翻译成中文（复用模块级翻译表）"""
    translated = text.strip()
    for en, zh in ERROR_CODE_TRANSLATION.items():
        if en.lower() in translated.lower():
            translated = re.sub(re.escape(en), zh, translated, flags=re.IGNORECASE)
    return translated

# VLM动作类型 → 中文
ACTION_TYPE_TRANSLATION = {
    "Smash":          "杀球",
    "smash":          "杀球",
    "Drop shot":      "吊球",
    "drop shot":      "吊球",
    "Net shot":       "网前球",
    "net shot":       "网前球",
    "Clear":          "高远球",
    "clear":          "高远球",
    "Drive":          "抽球",
    "drive":          "抽球",
    "Lob":            "挑球",
    "lob":            "挑球",
    "Push shot":      "推球",
    "push shot":      "推球",
    "Block":          "封网",
    "block":          "封网",
    "Defense":        "防守",
    "defense":        "防守",
    "Attack":         "进攻",
    "attack":         "进攻",
    "Backhand":       "反手",
    "backhand":       "反手",
    "Forehand":       "正手",
    "forehand":       "正手",
    "Save":           "救球",
    "save":           "救球",
}

def _translate_action_type(at):
    """把VLM英文动作类型翻译成中文"""
    return ACTION_TYPE_TRANSLATION.get(at, at)

def _error_key(e):
    """从错误字符串提取去重用的 key（只看错误代码 E1/E2/...，不看描述文本）"""
    m = re.match(r'(E\d+)', e.upper())
    return m.group(1) if m else e[:20]

def clean_err(text, max_len=50):
    text = text.strip()
    text = re.sub(r"^[）\)\u3001、\s]+", "", text)
    text = re.sub(r"^[\d\u2460-\u2473]+[\.\、\s]+", "", text)
    text = _translate_err(text)           # ← 翻译VLM英文错误代码
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text


_TRANSLATION_DICT = {
    "Lower the elbow": "降低肘关节",
    "maintain a more natural swing path": "保持更自然的挥拍轨迹",
    "focus on explosive wrist snap": "注重击球瞬间的手腕爆发",
    "at impact": "在击球瞬间",
    "by practicing slow-motion swings": "通过慢动作挥拍练习",
    "to perfect timing": "来完善发力时机",
    "improve footwork recovery": "改进步伐回动",
    "landing on the balls of the feet": "以前脚掌落地",
    "immediately pivoting to reset": "立即转髋重心调整",
    "keep it slightly bent and close to the body": "保持肘关节微屈靠近身体",
    "engage the legs and hips": "调动腿和髋部发力",
    "initiate with leg drive and hip rotation": "以蹬腿转髋启动",
    "keep elbow slightly bent": "保持肘关节微屈",
    "maintain optimal swing path": "保持最佳挥拍路径",
    "Practice slow-motion drills": "进行慢动作练习",
    "to reinforce proper sequencing": "强化正确的发力顺序",
    "engage hips and shoulders earlier": "更早调动髋肩转动",
    "generate more power from legs and core": "更多利用腿部核心发力",
    "increase shot depth and consistency": "增加回球深度和稳定性",
    "overhead clear drills": "头顶高远球练习",
    "full-body coordination": "全身协调配合",
    "improve coordination between leg drive and hip rotation": "改进蹬腿与转髋的协调配合",
    "achieve a more efficient, downward strike": "实现更有效的向下击打",
    "practice wrist relaxation and snap": "练习手腕放松与爆发",
    "with light touch drills": "进行轻触球练习",
    "use mirror or video feedback": "使用镜子或视频反馈",
    "adjust racquet face angle": "调整拍面角度",
    "to slightly downward at contact": "在触球时稍微向下",
    "for better net control": "以更好地控制网前",
    "ensure full wrist snap at impact": "确保击球瞬间手腕充分爆发",
    "explosive deceleration": "爆发性减速",
    "lower the elbow": "降低肘关节",
    "lower the elbow at the start of the swing": "在挥拍起始时降低肘关节",
    "lower the elbow at contact": "在击球瞬间降低肘关节",
    "lower the elbow during backswing": "在引拍时降低肘关节",
    "lower the elbow during the backswing": "在引拍时降低肘关节",
    "avoid raising the elbow too high": "避免肘关节抬得过高",
}


def _translate_suggestion_impl(text):
    """把英文改进建议翻译成中文"""
    if not text:
        return text
    # 按长度从长到短排序，确保优先匹配更长短语
    sorted_items = sorted(_TRANSLATION_DICT.items(), key=lambda x: len(x[0]), reverse=True)
    translated = text
    for en, zh in sorted_items:
        # 使用 word-boundary aware 替换，避免部分匹配和级联替换
        translated = re.sub(r'\b' + re.escape(en) + r'\b', zh, translated)
    return translated


def _infer_action_types(shots):
    """
    VLM 单帧无法区分杀球/高远球/吊球，
    通过 error_codes 关键词反向推断具体动作类型。
    同时将 generic "后场击球（单帧推断）" 替换为推断结果。
    """
    import re

    def _clean_err(text):
        text = text.strip()
        text = re.sub(r"^[）\)\u3001、\s]+", "", text)
        text = re.sub(r"^[\d\u2460-\u2473]+[\.\、\s]+", "", text)
        # 翻译VLM英文错误代码（遍历所有，翻译到的替换）
        translated = text
        for en, zh in ERROR_CODE_TRANSLATION.items():
            if en.lower() in translated.lower():
                translated = re.sub(re.escape(en), zh, translated, flags=re.IGNORECASE)
        return translated

    def _translate_suggestion(text):
        """把英文改进建议翻译成中文（代理到模块级函数）"""
        return _translate_suggestion_impl(text)

    def _do_infer(shot):
        at = shot.get("action_type", "")
        if at != "后场击球（单帧推断）":
            return  # 只处理 generic 类型

        errors = [_clean_err(e) for e in shot.get("errors", [])]
        err_text = " ".join(errors)

        # 抽关键词
        smash_kw   = ["下压", "下压角度", "重扣", "杀球", "扣杀"]
        clear_kw   = ["高远球", "弧度不够", "不到位", "球弧度", "高远"]
        drop_kw    = ["吊球", "网前", "放网", "弧线", "轻吊"]

        smash_hit  = any(k in err_text for k in smash_kw)
        clear_hit  = any(k in err_text for k in clear_kw)
        drop_hit   = any(k in err_text for k in drop_kw)

        hits = sum([smash_hit, clear_hit, drop_hit])

        if hits == 1:
            if smash_hit:
                shot["action_type"] = "正手杀球"
            elif clear_hit:
                shot["action_type"] = "正手高远球"
            elif drop_hit:
                shot["action_type"] = "正手吊球"
        elif hits > 1:
            # 多个命中：取最高权重
            # 下压/重扣/杀球 → 杀球；高远球/弧度 → 高远球；其他 → 吊球
            if smash_hit:
                shot["action_type"] = "正手杀球"
            elif clear_hit:
                shot["action_type"] = "正手高远球"
            else:
                shot["action_type"] = "正手吊球"
        # hits == 0：保持 generic，不处理

    for shot in shots:
        _do_infer(shot)

    return shots


def make_report(data: dict, output_path: str):
    """
    生成 PDF 报告

    data 格式:
    {
        "video": "VID_xxx.mp4",
        "duration": "5分34秒",
        "date": "2026-05-05",
        "player_colors": ["近端白", "近端蓝", "远端白", "远端蓝"],
        "player_name": "张三",          # 可选，当前分析球员名
        "session": { ... },              # 可选，来自 player_db 的 session 数据
        "progress": { ... },             # 可选，来自 player_db.compute_progress()
        "shots": [
            {
                "frame_file": "f_0000.jpg",
                "time": "00:15",
                "action_type": "正手抽球",
                "player": "近端白球员",
                "quality_rating": 3,
                "key_findings": [...],
                "errors": [...],
                "suggestions": [...]
            },
            ...
        ]
    }
    """
    pdf = Report()
    pdf.set_auto_page_break(auto=True, margin=10)
    try:
        pdf.add_font("STHeiti", fname=ASSETS_FONT, uni=True)
    except Exception as e:
        print(f"[WARN] 字体加载失败: {e}，使用内置字体")
    pdf.add_page()

    LM = pdf.l_margin
    RM = pdf.r_margin
    BW = pdf.w - LM - RM

    sessions = data.get("sessions", [])
    shots = data.get("shots", [])
    # VLM 单帧推断后处理：把 generic "后场击球" 替换为具体动作类型
    _infer_action_types(shots)
    player_name = data.get("player_name", "")
    session = data.get("session", {})
    progress = data.get("progress", {})
    player_colors = data.get("player_colors", [])

    # ─── 标题栏 ───
    pdf.set_fill_color(*C_MID)
    pdf.rect(LM, pdf.y - 4, 3, 30, "F")
    pdf.set_font("STHeiti", size=STYLE["F_TITLE"])
    pdf.set_text_color(*C_DARK)
    pdf.set_x(LM + 8)
    title = "羽毛球技术动作分析报告"
    if player_name:
        title = f"{player_name} · 技术分析报告"
    pdf.cell(BW - 8, 13, title, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("STHeiti", size=STYLE["F_BODY"])
    pdf.set_text_color(*C_LIGHT)
    pdf.set_x(LM + 8)
    meta = (f"视频：{data['video']}  |  时长：{data.get('duration','未知')}  |  "
            f"分析帧数：{len(shots)}帧  |  {data['date']}")
    pdf.cell(BW - 8, 6, meta, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_fill_color(*C_MID)
    pdf.rect(LM, pdf.y, BW, 1.5, "F")
    pdf.ln(4)

    # ─── 进步对比 Banner（如果有历史数据） ───
    if progress.get("enough_data"):
        pdf.set_fill_color(*C_MID)
        pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
        pdf.set_text_color(255, 255, 255)

        delta = progress["delta"]
        sign = "+" if delta > 0 else ""
        trend = trend_icon(session.get("quality_trend", ""))
        trend_color(session.get("quality_trend", ""))

        banner = (f"进步跟踪  |  第{progress['total_sessions']}次分析  |  "
                  f"总分：{progress['first_avg']} → {progress['latest_avg']}（{sign}{delta}）  {trend}")
        pdf.cell(BW, 8, banner, border=0, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # ─── Section 1: 球员信息 ───
    pdf.set_fill_color(*C_BLUE)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "一、球员信息", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # 按队伍分组（每队占一端，不拆分）
    team_end = {}  # {队伍名: 近端/远端}
    for p in player_colors:
        m = re.match(r"([白蓝红黑绿黄]队)([近远]端)", p)
        if m:
            team, end = m.groups()
            team_end[team] = end
    rows = list(team_end.items())

    # 表头：队伍 | 球员位置
    col_x = [pdf.l_margin + 0, pdf.l_margin + 45]
    col_w = [45, 45]
    row_h = 10
    headers = ["队伍", "球员位置"]
    pdf.set_fill_color(*C_DARK)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("STHeiti", size=STYLE["F_BODY"])
    for cx, cw, h in zip(col_x, col_w, headers):
        pdf.set_xy(cx, pdf.y)
        pdf.cell(cw, 8, h, border=1, fill=True, align="C")
    pdf.y += 8

    for idx, (team, end) in enumerate(rows):
        fill = (idx % 2 == 0)
        fc = (245, 247, 252) if fill else (255, 255, 255)
        color_name = team[0]
        tc = C_BLUE if color_name == "蓝" else (C_RED if color_name == "红" else (120, 120, 120))
        for ci, (cx, cw, val) in enumerate(zip(col_x, col_w, [team, end])):
            pdf.set_fill_color(*fc)
            pdf.rect(cx, pdf.y, cw, row_h, "FD")
            pdf.set_xy(cx, pdf.y)
            pdf.set_text_color(*tc)
            pdf.set_font("STHeiti", size=STYLE["F_BODY"])
            pdf.cell(cw, row_h, val, border=0, fill=False, align="C")
        pdf.y += row_h
    pdf.ln(5)

    # ─── Section 2: 整体评价 ───
    pdf.set_fill_color(*C_ORG)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "二、整体技术评价", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    ratings = [s.get("quality_rating", 3) for s in shots]
    avg_q = sum(ratings) / len(ratings) if ratings else 0
    pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
    pdf.set_text_color(*C_GREY)
    pdf.multi_cell(BW, 6, f"本次分析共 {len(shots)} 个有效动作帧，整体技术评分：{avg_q:.1f}/10（{qtext(int(round(avg_q)))}）。")
    pdf.ln(2)

    # ── 球速统计（小节）─────────────────────────────────
    speeds = [s["speed_kmh"] for s in shots if s.get("speed_kmh") and s.get("speed_kmh") > 0]
    if speeds:
        max_s = max(speeds)
        avg_s = sum(speeds) / len(speeds)
        pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
        pdf.set_text_color(*C_GREY)
        pdf.multi_cell(BW, 5.5, f"球速数据（{len(speeds)}个有效样本）：最高 {max_s:.0f} km/h，平均 {avg_s:.0f} km/h。")
        pdf.ln(4)

        # 速度分布条（简化横向柱状图，文本绘制）
        speed_bins = [
            ("慢速 <100", lambda v: v < 100),
            ("中速 100-200", lambda v: 100 <= v < 200),
            ("快速 200-300", lambda v: 200 <= v < 300),
            ("极速 >300", lambda v: v >= 300),
        ]
        bin_counts = [sum(1 for v in speeds if pred(v)) for _, pred in speed_bins]
        max_bin = max(bin_counts) if bin_counts else 1
        bar_max_w = BW * 0.6   # 最大条宽度

        for label, _ in speed_bins:
            cnt = bin_counts[speed_bins.index((label, _))]
            if cnt == 0:
                continue
            bar_w = bar_max_w * cnt / max_bin
            pdf.set_font("STHeiti", size=STYLE["F_MINI"])
            pdf.set_text_color(*C_GREY)
            # 固定行高 8mm，用 get_x() 记录行起点，避免 pdf.x 被 cell 游走带偏
            row_y = pdf.get_y() + 1
            bar_y = row_y + 1
            bar_x = LM + 40   # 条左端固定在页内，避免 pdf.x 状态污染
            if "慢速" in label:
                bar_c = C_GREEN
            elif "中速" in label:
                bar_c = C_GOLD
            elif "快速" in label:
                bar_c = C_ORG
            else:
                bar_c = C_RED
            # 标签在左，条在右，不重叠
            pdf.set_xy(LM, row_y)
            pdf.cell(38, 7, label, align="L")        # 左固定 38mm 放标签
            pdf.set_fill_color(*bar_c)
            pdf.rect(bar_x, bar_y, bar_w, 5, "F")    # 条从固定位置延伸
            pdf.set_xy(bar_x + bar_w + 2, row_y)
            pdf.cell(15, 7, f" {cnt}次", align="L")  # 数量在条右
            pdf.set_y(row_y + 8)

    pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
    pdf.cell(0, 6, "主要技术问题分布：", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    err_cnt = Counter()
    e_code_first_seen = {}  # E-code → 第一个出现的完整文本
    for s in shots:
        for e in s.get("errors", []):
            k = _error_key(e)  # 提取 E1/E2/... 作为聚合key，同一E-code合并
            if len(k) > 2:
                err_cnt[k] += 1
                if k not in e_code_first_seen:
                    e_code_first_seen[k] = clean_err(e, 50)  # 保留完整文本用于显示

    # ── 问题分布表（2列：问题类型 + 出现次数）──────────────
    ew = [BW * 0.70, BW * 0.30]
    ex = [LM, LM + ew[0]]

    pdf.set_fill_color(*C_MID)
    pdf.set_font("STHeiti", size=STYLE["F_BODY"])
    pdf.set_text_color(255, 255, 255)
    for h, cx, w in zip(["问题类型", "出现次数"], ex, ew):
        pdf.set_xy(cx, pdf.y)
        pdf.cell(w, 8, h, border=1, fill=True, align="C")
    pdf.y += 8

    for i, (err, cnt) in enumerate(err_cnt.most_common(8)):
        err_disp = e_code_first_seen.get(err, err)  # 显示完整描述，不是E-code本身
        fill = (i % 2 == 0)
        err_fc = (255, 245, 245) if fill else (255, 255, 255)
        row_h = max(9, (len(err_disp) // 24 + 1) * 9)

        cur_y = pdf.y
        pdf.set_fill_color(*err_fc)
        pdf.rect(ex[0], cur_y, ew[0], row_h, "FD")
        pdf.rect(ex[1], cur_y, ew[1], row_h, "FD")

        pdf.set_xy(ex[0], cur_y)
        pdf.set_font("STHeiti", size=STYLE["F_BODY"])
        pdf.set_text_color(*C_GREY)
        pdf.multi_cell(ew[0], 4.5, err_disp, border=0)

        pdf.set_xy(ex[1], cur_y)
        pdf.set_font("STHeiti", size=STYLE["F_BODY"])
        pdf.set_text_color(*C_RED)
        pdf.cell(ew[1], row_h, f"{cnt}次", border=0, fill=False, align="C")

        pdf.y = cur_y + row_h
    pdf.ln(5)

    # ── Section 2.5: 技术问题诊断汇总（新增：视频级聚合展示）──
    tech_summary = data.get("tech_summary", {})
    top_errors = tech_summary.get("top_errors", [])
    zone_breakdown = tech_summary.get("zone_breakdown", {})
    frames_dir = data.get("frames_dir", "")

    if top_errors:
        # 确保足够空间
        card_rows = (len(top_errors) + 1) // 2
        estimated_h = card_rows * 28 + 20  # 每卡片约28mm + 标题区20mm
        if pdf.y + estimated_h > pdf.page_break_trigger - 10:
            pdf.add_page()

        pdf.set_fill_color(*C_RED)
        pdf.rect(LM, pdf.y - 1, 3, 10, "F")
        pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
        pdf.set_text_color(*C_MID)
        pdf.set_x(LM + 6)
        pdf.cell(0, 8, "三、技术问题诊断汇总", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # ── 彩色问题卡片（2列布局）──────────────────────────────
        CARD_COLORS = [
            (198, 40,  40),   # 红
            (239, 108,  0),   # 橙
            (255, 180,  0),   # 金
            ( 39, 174, 96),   # 绿
            (  0,  90, 180),  # 蓝
            (100, 50,  180),  # 紫
            (  0, 150, 136),   # 青
            (180,  80,  40),   # 棕
        ]
        img_w = 45   # 缩略图宽度（mm）
        img_h = 25   # 缩略图高度
        card_w = (BW - 5) / 2   # 两列卡片
        card_h = img_h + 10

        for idx, te in enumerate(top_errors):
            col = idx % 2
            row = idx // 2
            x = LM + col * (card_w + 5)
            y = pdf.y + row * card_h

            # 卡片背景
            c = CARD_COLORS[idx % len(CARD_COLORS)]
            pdf.set_fill_color(*c)
            pdf.set_draw_color(*c)
            pdf.set_line_width(0.3)
            pdf.rect(x, y, card_w, card_h, "FD")

            # 顶部色条
            pdf.set_fill_color(*c)
            pdf.rect(x, y, card_w, 4, "F")

            # E-code 标签
            pdf.set_xy(x + 2, y + 4.5)
            pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
            pdf.set_text_color(255, 255, 255)
            pdf.cell(card_w - 4, 5, f"{te['code']} {te['name']}", align="L")

            # 次数
            pdf.set_xy(x + card_w - 18, y + 4.5)
            pdf.set_font("STHeiti", size=STYLE["F_BODY"])
            pdf.set_text_color(255, 255, 255)
            pdf.cell(16, 5, f"×{te['count']}", align="R")

            # 代表性帧缩略图
            frame_file = te.get("frame_file", "")
            if frame_file and frames_dir:
                rep_path = ""
                ann_name = frame_file.replace("f_", "ann_f_")
                for fname in [ann_name, frame_file]:
                    candidate = f"{frames_dir}/{fname}" if frames_dir else fname
                    if os.path.isfile(candidate):
                        rep_path = candidate
                        break
                if rep_path:
                    try:
                        from PIL import Image as PILImage
                        im = PILImage.open(rep_path)
                        iw, ih = im.size
                        ratio = ih / iw
                        dh = img_w * ratio
                        pdf.image(rep_path, x=x + 1, y=y + 9.5, w=img_w, h=dh)
                    except Exception:
                        pdf.set_fill_color(240, 240, 240)
                        pdf.rect(x + 1, y + 9.5, img_w, img_h, "D")
                else:
                    pdf.set_fill_color(240, 240, 240)
                    pdf.rect(x + 1, y + 9.5, img_w, img_h, "D")
            else:
                pdf.set_fill_color(240, 240, 240)
                pdf.rect(x + 1, y + 9.5, img_w, img_h, "D")

            # 时间戳
            pdf.set_xy(x + 1, y + card_h - 4)
            pdf.set_font("STHeiti", size=STYLE["F_TINY"])
            pdf.set_text_color(200, 200, 200)
            time_str = te.get("time", "")
            pdf.cell(img_w, 4, f"@{time_str}" if time_str else "", align="L")

        pdf.ln(card_rows * card_h - pdf.y + pdf.y)
        pdf.ln(4)

        # ── 区域分布表 ──────────────────────────────────────
        if zone_breakdown:
            pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
            pdf.set_text_color(*C_GREY)
            pdf.cell(0, 6, "区域错误分布：", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

            # 表头
            zone_cols = ["区域", "TOP1", "TOP2", "TOP3", "TOP4", "TOP5"]
            zone_xs = [LM]
            zone_ws = [30]
            for i in range(1, len(zone_cols)):
                zone_xs.append(zone_xs[-1] + zone_ws[-1])
                zone_ws.append((BW - 30) / (len(zone_cols) - 1))

            pdf.set_fill_color(*C_MID)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("STHeiti", size=STYLE["F_BODY"])
            for h, cx, w in zip(zone_cols, zone_xs, zone_ws):
                pdf.set_xy(cx, pdf.y)
                pdf.cell(w, 7, h, border=1, fill=True, align="C")
            pdf.y += 7

            zones = ["前场", "中场", "后场"]
            zones_with_data = [z for z in zones if zone_breakdown.get(z)]
            if not zones_with_data:
                zones_with_data = zones  # fallback: show all zones if no data
            for zi, zone in enumerate(zones_with_data):
                zone_data = zone_breakdown.get(zone, [])
                fill = (zi % 2 == 0)
                fc = (245, 247, 252) if fill else (255, 255, 255)
                row_h = 8

                pdf.set_fill_color(*fc)
                # 区域列
                pdf.set_xy(zone_xs[0], pdf.y)
                pdf.cell(zone_ws[0], row_h, zone, border=1, fill=True, align="C")
                # 各TOP列
                for ci in range(1, len(zone_cols)):
                    pdf.set_xy(zone_xs[ci], pdf.y)
                    val = zone_data[ci - 1] if ci - 1 < len(zone_data) else {}
                    cell_txt = f"{val.get('code','')}{val.get('name','')[-4:]}" if val else "-"
                    pdf.cell(zone_ws[ci], row_h, cell_txt, border=1, fill=True, align="C")
                pdf.y += row_h
            pdf.ln(5)

    # ─── Section 4: 详细动作分析 ───
    pdf.set_fill_color(*C_BLUE)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "四、详细技术分析", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    IMG_W_MM = 65
    IMG_H_MM = 36
    from PIL import Image as PILImage

    # 每个 shot 选取一个错误标注叠加到图上（按顺序选第一个 E 编号）
    shot_img_error = {}        # shot_idx → error 文本 or None
    for i, shot in enumerate(shots):
        flat_errors = []
        for err_str in shot.get("errors", []):
            for part in err_str.split(','):
                part = part.strip()
                if part:
                    flat_errors.append(part)
        chosen = None
        for e in flat_errors[:3]:
            key = _error_key(e)
            if len(key) >= 2:
                chosen = e
                break
        shot_img_error[i] = chosen

    # ── 全局去重：同类错误只配第一张图（预扫描+NO_IMG标记）──────────
    shown_error_keys = set()   # 已配图的错误类型
    NO_IMG = object()          # 标记"此卡不配图"
    shot_img_final = {}         # shot_idx → error文本 or NO_IMG
    for i, shot in enumerate(shots):
        chosen = shot_img_error.get(i)
        if chosen:
            key = _error_key(chosen)
            if key and key not in shown_error_keys and len(key) >= 2:
                shown_error_keys.add(key)
                shot_img_final[i] = chosen   # 有图
            else:
                shot_img_final[i] = NO_IMG  # 跳过图片但保留卡片
        else:
            shot_img_final[i] = None         # 无error

    for i, shot in enumerate(shots):
        q = shot.get("quality_rating", 3)
        ql = qlabel(q)
        tc = TAG_C.get(int(round(q)), C_LIGHT)

        action_type = _translate_action_type(shot.get("action_type", ""))

        # 分析失败且无实质内容：跳过此帧，不绘制卡片
        if action_type == "分析失败" and not shot.get("errors") and not shot.get("suggestions"):
            continue

        # R3兜底过滤：只渲染目标球员的shots
        target_player = data.get("target_player", "")
        if target_player and shot.get("player", "") != target_player:
            continue

        q = shot.get("quality_rating", 3)
        ql = qlabel(q)
        tc = TAG_C.get(int(round(q)), C_LIGHT)

        title = (f"动作{i+1}：{action_type}  |  "
                 f"{shot.get('player','')}  |  {shot.get('time','')}")

        card_h_mm = 8 + IMG_H_MM + 4
        if pdf.y + card_h_mm > pdf.page_break_trigger:
            pdf.add_page()

        card_start_y = pdf.y
        pdf.set_fill_color(*tc)
        pdf.rect(LM, card_start_y, 3, 14, "F")
        pdf.set_fill_color(240, 244, 248)
        pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
        pdf.set_text_color(*C_DARK)
        pdf.set_x(LM + 4)
        pdf.cell(pdf.w - LM - pdf.r_margin - 4, 7, title, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_fill_color(*tc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("STHeiti", size=STYLE["F_BODY"])
        pdf.set_x(LM + 4)
        pdf.cell(pdf.w - LM - pdf.r_margin - 4, 6, f"  {ql}  {q}/10",
                 border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        body_y = pdf.y
        body_y + IMG_H_MM   # 图片区域结束Y（用于分隔线）
        # shots 数据源有两个版本：frames_results 用 frame_file，analyze_shots 用 frames[0]
        _frames = shot.get("frames", [])
        frame_file = shot.get("frame_file") or (_frames[0] if _frames else "")
        frames_dir = data.get("frames_dir", "")
        # frames_dir 必须指向有效目录；拒绝 /tmp/bad_shots/target_frames 等污染路径
        arc_dir = os.path.dirname(os.path.dirname(frames_dir)) if frames_dir else ""
        if not frames_dir or not os.path.isdir(frames_dir) \
           or (arc_dir not in ("", "/tmp") and frames_dir == arc_dir):
            frames_dir = ""
        # 优先使用 annotated 文件（ann_f_xxx.jpg），不存在则 fallback 到原始帧
        img_path = ""
        if frame_file:
            ann_name = frame_file.replace("f_", "ann_f_")
            ann_path = f"{frames_dir}/{ann_name}" if frames_dir else ann_name
            raw_path = f"{frames_dir}/{frame_file}" if frames_dir else frame_file
            if os.path.isfile(ann_path):
                img_path = ann_path
            elif os.path.isfile(raw_path):
                img_path = raw_path
        txt_x = LM + IMG_W_MM + 5
        txt_w = pdf.w - LM - pdf.r_margin - IMG_W_MM - 5

        # 图片（带球员标注）— 使用全局去重后的 shot_img_final
        this_img_err = shot_img_final.get(i)        # None/NO_IMG/具体error文本
        # 铁律（2026-05-14）：无图不上点评
        # - 无 error 且无高质量帧 → 整卡不渲染
        # - render_img=False（无图/同类重复）→ 跳过图片区域，不留灰框，文字撑满行宽
        has_error = shot.get("errors") and len(shot.get("errors", [])) > 0
        # render_img：this_img_err 有具体error文本 且 img_path 存在 → 配图
        render_img = (this_img_err is not None
                      and this_img_err is not NO_IMG
                      and bool(img_path))
        if not render_img and not has_error:
            # 无图也无error → 整卡跳过，文字撑满行宽
            pdf.set_font("STHeiti", size=STYLE["F_ACTION"])
            pdf.set_text_color(80, 80, 80)
            pdf.set_fill_color(250, 250, 250)
            pdf.rect(LM, body_y, BW, 12, "F")
            action_label = f"{shot.get('action_type', '未知动作')}  {shot.get('quality_rating', 0)}/10"
            pdf.set_xy(LM + 3, body_y + 3)
            pdf.cell(BW - 6, 6, action_label, align="L")
            pdf.set_y(body_y + 14)
            # 下方文字渲染：跨全宽
            text_start_y = pdf.get_y() + 2
            txt_x_full = LM
            txt_w_full = BW
            pdf.set_xy(txt_x_full, text_start_y)
            # ── 内联渲染文字（替代不存在的 _render_shot_text）──
            findings     = shot.get("key_findings", [])
            errors       = shot.get("errors", [])
            suggestions  = shot.get("suggestions", [])
            end_y = text_start_y
            if findings:
                pdf.set_x(txt_x_full)
                pdf.set_text_color(40, 40, 40)
                pdf.cell(txt_w_full, 5, "技术诊断：")
                end_y = pdf.get_y() + 5
                for f in findings[:2]:
                    pdf.set_x(txt_x_full)
                    pdf.set_text_color(*C_GREY)
                    pdf.multi_cell(txt_w_full, 4.5, f"• {f[:120]}")
                end_y = pdf.get_y() + 1
            if errors:
                pdf.set_x(txt_x_full)
                pdf.ln(1)
                pdf.set_text_color(180, 40, 40)
                pdf.cell(txt_w_full, 5, "常见错误：")
                end_y = pdf.get_y() + 5
                for e in errors[:2]:
                    pdf.set_x(txt_x_full)
                    pdf.set_text_color(*C_GREY)
                    pdf.multi_cell(txt_w_full, 4.5, f"x {e[:100]}")
                end_y = pdf.get_y() + 1
            if suggestions:
                pdf.set_x(txt_x_full)
                pdf.ln(1)
                pdf.set_text_color(30, 120, 80)
                pdf.cell(txt_w_full, 5, "改进建议：")
                end_y = pdf.get_y() + 5
                for s in suggestions[:2]:
                    pdf.set_x(txt_x_full)
                    pdf.set_text_color(*C_GREY)
                    pdf.multi_cell(txt_w_full, 4.5, f"→ {s[:120]}")
                end_y = pdf.get_y() + 1
            # ── 结束内联渲染 ───
            pdf.set_y(end_y + 4)
            continue

        img_bottom_y = body_y
        if render_img:
            try:
                from PIL import Image as PILImage, ImageDraw
                im = PILImage.open(img_path)
                iw, ih = im.size
                ImageDraw.Draw(im)

                # 根据球员位置确定标注区域
                player_str = shot.get("player", "")
                m = re.match(r"([近远]端)([白蓝红黑绿黄])球员", player_str)
                if m:
                    pos, color_name = m.groups()
                    color_map = {"白": "#FFFFFF", "蓝": "#0066CC", "红": "#CC0000",
                                 "黑": "#333333", "绿": "#228B22", "黄": "#FFCC00"}
                    ann_color = color_map.get(color_name, "#FFFFFF")
                    def hex_to_rgba(h, alpha=180):
                        h = h.lstrip('#')
                        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)
                    ann_rgba = hex_to_rgba(ann_color, 180)
                    if pos == "远端":
                        box_x0, box_y0 = int(iw*0.3), int(ih*0.15)
                        box_x1, box_y1 = int(iw*0.7), int(ih*0.55)
                    else:
                        box_x0, box_y0 = int(iw*0.2), int(ih*0.45)
                        box_x1, box_y1 = int(iw*0.8), int(ih*0.95)
                    overlay = PILImage.new("RGBA", im.size, (0,0,0,0))
                    od = ImageDraw.Draw(overlay)
                    for edge_w in range(3):
                        od.rectangle([box_x0-edge_w, box_y0-edge_w,
                                     box_x1+edge_w, box_y1+edge_w],
                                    outline=ann_color, width=3)
                    im = PILImage.alpha_composite(im.convert("RGBA"), overlay)
                    label_bg = PILImage.new("RGBA", im.size, (0,0,0,0))
                    ld = ImageDraw.Draw(label_bg)
                    lw, lh = 8, 8
                    for dx in range(lw):
                        for dy in range(lh):
                            ld.rectangle([box_x0+dx, box_y0-lh-2+dy,
                                         box_x0+lw+dx, box_y0-2+dy],
                                        fill=ann_rgba)
                    im = PILImage.alpha_composite(im, label_bg)
                # img_path 已在上面（lines 643-652）正确指向 archive 目录的 ann_f_xxxx.jpg
                img_path_ann = img_path

                ann_base = os.path.dirname(img_path) if img_path else ""
                ann_path = f"{ann_base}/ann_{frame_file}" if ann_base and frame_file else ""
                if ann_path and os.path.exists(ann_path):
                    img_path_ann = ann_path

                iw, ih = im.size
                ratio = ih / iw  # 原始宽高比
                draw_h = IMG_W_MM * ratio
                if draw_h > IMG_H_MM:
                    # 高度超标时按高度限制，反算宽度（保持比例不变形）
                    draw_w = IMG_H_MM / ratio
                    actual_img_h = IMG_H_MM
                else:
                    actual_img_h = draw_h
                img_bottom_y = body_y + actual_img_h
                pdf.image(img_path_ann, x=LM, y=body_y, w=draw_w if draw_h > IMG_H_MM else IMG_W_MM, h=actual_img_h)
            except Exception as e:
                print(f"  [!] 标注失败: {e}")
                pdf.rect(LM, body_y, IMG_W_MM, IMG_H_MM, "D")
                img_bottom_y = body_y + IMG_H_MM
        else:
            # 同类问题重复（同类已配图）：不画灰框，文字跨全宽
            txt_x_full = txt_x
            txt_w_full = txt_w
            text_start_y = body_y + 2
            pdf.set_xy(txt_x_full, text_start_y)
            pdf.set_font("STHeiti", size=8.5)
            end_y = text_start_y
            findings  = shot.get("key_findings", [])
            errors    = shot.get("errors", [])
            suggestions = shot.get("suggestions", [])
            if action_type in ("准备发球", "死球", "捡球", "无效帧", "分析失败", "无法判断"):
                hit_kw = ("击球", "闪腕", "球速", "发力", "挥拍", "击球点", "击球瞬间")
                errors     = [e for e in errors     if not any(k in e for k in hit_kw)]
                suggestions = [s for s in suggestions if not any(k in s for k in hit_kw)]
                findings   = [f for f in findings   if not any(k in f for k in hit_kw)]
            if findings:
                pdf.set_xy(txt_x_full, end_y)
                pdf.set_text_color(40, 40, 40)
                pdf.cell(txt_w_full, 5, "技术诊断：")
                end_y = pdf.get_y() + 5
                for f in findings[:2]:
                    pdf.set_x(txt_x_full)
                    pdf.set_text_color(*C_GREY)
                    pdf.multi_cell(txt_w_full, 4.5, f"• {clean_err(f, 120)}")
                end_y = pdf.get_y() + 1
            if errors:
                pdf.set_x(txt_x_full)
                pdf.ln(1)
                pdf.set_text_color(180, 40, 40)
                pdf.cell(txt_w_full, 5, "常见错误：")
                end_y = pdf.get_y() + 5
                for e in errors[:2]:
                    pdf.set_x(txt_x_full)
                    pdf.set_text_color(*C_GREY)
                    pdf.multi_cell(txt_w_full, 4.5, f"x {clean_err(e, 100)}")
                end_y = pdf.get_y() + 1
            if suggestions:
                pdf.set_x(txt_x_full)
                pdf.ln(1)
                pdf.set_text_color(30, 120, 80)
                pdf.cell(txt_w_full, 5, "改进建议：")
                end_y = pdf.get_y() + 5
                for s in suggestions[:2]:
                    pdf.set_x(txt_x_full)
                    pdf.set_text_color(*C_GREY)
                    pdf.multi_cell(txt_w_full, 4.5, f"→ {_translate_suggestion_impl(s)}")
                end_y = pdf.get_y()
            击球选择 = shot.get("击球选择", "")
            战术意识 = shot.get("战术意识", "")
            跑位意识 = shot.get("跑位意识", "")
            tactic_items = [(k, v) for k, v in [("击球选择", 击球选择), ("战术意识", 战术意识), ("跑位意识", 跑位意识)] if v]
            if tactic_items:
                pdf.set_x(txt_x_full)
                pdf.ln(1)
                pdf.set_text_color(60, 60, 160)
                pdf.cell(txt_w_full, 5, "战术意识：")
                end_y = pdf.get_y() + 5
                for k, v in tactic_items[:2]:
                    pdf.set_x(txt_x_full)
                    pdf.set_text_color(*C_GREY)
                    pdf.multi_cell(txt_w_full, 4.5, f"· {k}：{v}")
                end_y = pdf.get_y()
            pdf.set_y(end_y + 4)
            continue

        # 文字（从图片区域底部下方开始，与图片右对齐）
        text_start_y = img_bottom_y + 3
        pdf.set_xy(txt_x, text_start_y)
        pdf.set_font("STHeiti", size=8.5)
        end_y = text_start_y

        # 过滤：未触球/分析失败状态，不应有击球类错误
        findings  = shot.get("key_findings", [])
        errors    = shot.get("errors", [])
        suggestions = shot.get("suggestions", [])
        if action_type in ("准备发球", "死球", "捡球", "无效帧", "分析失败", "无法判断"):
            hit_kw = ("击球", "闪腕", "球速", "发力", "挥拍", "击球点", "击球瞬间")
            errors     = [e for e in errors     if not any(k in e for k in hit_kw)]
            suggestions = [s for s in suggestions if not any(k in s for k in hit_kw)]
            findings   = [f for f in findings   if not any(k in f for k in hit_kw)]

        if findings:
            pdf.set_xy(txt_x, end_y)
            pdf.set_text_color(40, 40, 40)
            pdf.cell(txt_w, 5, "技术诊断：")
            end_y = pdf.get_y() + 5
            for f in findings[:2]:
                pdf.set_x(txt_x)
                pdf.set_text_color(*C_GREY)
                pdf.multi_cell(txt_w, 4.5, f"• {clean_err(f, 120)}")
            end_y = pdf.get_y() + 1

        if errors:
            pdf.set_x(txt_x)
            pdf.ln(1)
            pdf.set_text_color(180, 40, 40)
            pdf.cell(txt_w, 5, "常见错误：")
            end_y = pdf.get_y() + 5
            for e in errors[:2]:
                pdf.set_x(txt_x)
                pdf.set_text_color(*C_GREY)
                pdf.multi_cell(txt_w, 4.5, f"x {clean_err(e, 100)}")
            end_y = pdf.get_y() + 1

        if suggestions:
            pdf.set_x(txt_x)
            pdf.ln(1)
            pdf.set_text_color(30, 120, 80)
            pdf.cell(txt_w, 5, "改进建议：")
            end_y = pdf.get_y() + 5
            for s in suggestions[:2]:
                pdf.set_x(txt_x)
                pdf.set_text_color(*C_GREY)
                pdf.multi_cell(txt_w, 4.5, f"→ {_translate_suggestion_impl(s)}")
            end_y = pdf.get_y()

        # 战术分析
        击球选择 = shot.get("击球选择", "")
        战术意识 = shot.get("战术意识", "")
        跑位意识 = shot.get("跑位意识", "")
        tactic_items = [
            ("击球选择", 击球选择),
            ("战术意识", 战术意识),
            ("跑位意识", 跑位意识),
        ]
        tactic_items = [(k, v) for k, v in tactic_items if v]
        if tactic_items:
            pdf.ln(2)
            pdf.set_x(txt_x)
            pdf.set_text_color(60, 60, 140)
            pdf.cell(txt_w, 5, "战术分析：")
            end_y = pdf.get_y() + 5
            for k, v in tactic_items:
                pdf.set_x(txt_x)
                pdf.set_text_color(*C_GREY)
                pdf.multi_cell(txt_w, 4.5, f"· {k}：{v}")
            end_y = pdf.get_y()

        # 球速标签
        spd = shot.get("speed_kmh")
        if spd and spd > 0:
            pdf.set_x(txt_x)
            pdf.ln(1)
            # 速度颜色：>250红色(极速)，>180橙色(快速)，>100黄色(中速)，绿色(慢速)
            if spd >= 250:
                spd_c = C_RED
            elif spd >= 180:
                spd_c = C_ORG
            elif spd >= 100:
                spd_c = C_GOLD
            else:
                spd_c = C_GREEN
            pdf.set_fill_color(*spd_c)
            tag_w = 22
            tag_h = 6
            pdf.rect(pdf.x, end_y + 1, tag_w, tag_h, "F")
            pdf.set_font("STHeiti", size=STYLE["F_MINI"])
            pdf.set_text_color(255, 255, 255)
            pdf.set_xy(pdf.x, end_y + 1.5)
            pdf.cell(tag_w, tag_h - 1, f" 球速 {spd:.0f}km/h", align="L")
            end_y += tag_h + 2

        # 卡片底部 = 图片底部 和 文字底部 的较大者 + 足够padding
        card_bottom = max(img_bottom_y, end_y) + 4
        pdf.set_fill_color(*tc)
        pdf.rect(LM, card_bottom, pdf.w - LM - pdf.r_margin, 0.8, "F")
        pdf.y = card_bottom + 3

    # ─── Section 4: 教练总结 ───
    if pdf.y > pdf.page_break_trigger - 80:
        pdf.add_page()
    pdf.set_fill_color(*C_RED)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "五、教练总结与建议", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    top_errors = err_cnt.most_common(3)
    summary = [f"本次分析共 {len(shots)} 个有效动作样本，整体技术评分 {avg_q:.1f}/10。"]
    if top_errors:
        err_name = e_code_first_seen.get(top_errors[0][0], top_errors[0][0])
        summary.append(f"最突出问题：「{err_name}」（出现 {top_errors[0][1]} 次），建议重点练习。")
    if session.get("quality_trend"):
        t = session["quality_trend"]
        t_icon = trend_icon(t)
        trend_color(t)
        summary.append(f"进步趋势：{t_icon}（较上次{'上升' if t=='up' else '下降' if t=='down' else '持平'}）")

    pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
    pdf.set_text_color(*C_GREY)
    for line in summary:
        pdf.multi_cell(BW, 6, line)
        pdf.ln(2)
    pdf.ln(3)

    # 改进建议
    tips_map = {
        # 发力链相关
        "发力链": "加强下肢蹬地+髋部转动传导，每拍发力顺序：脚→腿→髋→肩→臂→腕。",
        "散": "力量传导脱节，加强'鞭打'式发力练习，从脚到手指逐级加速传递。",
        "蹬地": "增强下肢爆发力，多做负重深蹲和蹬跨步练习，提升击球前蹬地感。",
        "转髋": "髋部转动不充分，练习侧身转体挥拍，感受髋带肩、肩带臂的顺序。",
        "传导": "发力顺序混乱，加强'蹬、转、送'三步节拍练习，形成固定发力模式。",

        # 闪腕相关
        "闪腕": "练习手腕'甩鞭'动作，击球瞬间手腕快速制动，可借助弹力带辅助训练。",
        "腕力": "手腕力量不足，手指握力器练习+绑橡皮筋甩腕，增强腕部爆发力。",
        "甩腕": "甩腕不充分，专项练'抖手腕'发力，体会手指先动、腕部后'弹'的感觉。",
        "僵硬": "手腕过于僵硬，徒手挥拍时想象握着一只鸟——握紧会捏死，放松会飞走。",

        # 步伐相关
        "步伐": "增加米字步练习，增强脚步预判和快速移动能力。",
        "步法": "步法凌乱，加强'米字步'和'并步/交叉步'专项训练，形成自动化步型。",
        "移动": "移动偏慢，起动反应迟钝，增加'一起动'练习，看手势快速起动。",
        "蹬跨": "蹬跨步不到位，弱侧腿蹬地无力，多练单腿蹬跨和侧向弓步。",
        "重心": "重心起伏过大，保持'微蹲待机'姿态，横向移动时重心不超过支撑面。",
        "站位": "站位过死，缺乏小步调整，增加'碎步+调整'练习，随时微调站位。",

        # 拍面控制相关
        "拍面": "拍面角度不稳，镜前挥拍自查击球瞬间拍面朝向，固定甜区触球习惯。",
        "甜区": "甜区击球率低，尝试'看拍跳舞'练习，每次击球后观察拍面角度。",
        "包裹": "拍面包裹不足，加强'雨刷器'式挥拍和网前搓球练习。",
        "展腕": "展腕过早或过晚，击球瞬间拍面应垂直地面或微下压，找准展腕时机。",
        "拍频": "回球节奏单一，增加球路变化训练，避免被对手预判。",

        # 击球点相关
        "击球点": "击球点偏后，应在身体侧前方击球，保持'球拍伸出去'的姿态。",
        "击球位置": "击球点太后，通过多球训练强化'迎球击打'意识，不要等球。",
        "身侧": "击球点远离身体，侧身不充分，加强侧身挥拍徒手练习。",
        "偏高": "击球点偏高或偏低，通过看视频回放纠正击球点高度，建立肌肉记忆。",

        # 高远球专项
        "高远球": "高远球不到位，拍面后仰角度不足，击球前拍面应低于手腕，向上挥拍。",
        "弧度": "球弧度不够，高远球需大挥拍轨迹，拍面从下往上刷过球头。",
        "到位": "球不到位（不到位），发力不够或时机不准，加强挥拍速度和击球时机训练。",

        # 杀球/进攻
        "杀球": "杀球威胁不足，全身协调发力不足，加强'杀球三步曲'：蹬地+转体+甩腕。",
        "下压": "下压角度不够，拍面应明显下压（低于水平面），可通过'砸纸片'练习体会。",
        "重扣": "重扣力量不足，蹬地转体不充分，力量从脚底起逐级上传，腕部最后加速。",

        # 抽球相关
        "抽球": "平抽力量不足，肘部应引领大臂前挥，腕部保持弹性，'快出拍+松手腕'。",
        "平抽": "平抽速度慢，肘关节推进不足，甩臂式挥拍代替单纯手腕发力。",
        "挥拍": "挥拍轨迹不流畅，多练完整挥拍（从背后引拍到前送），建立动力定型。",
        "引拍": "引拍不充分或停顿，规范背后S形引拍轨迹，避免'架苍蝇拍'式引拍。",
        "前压": "挥拍缺少前压角度，平击过多，加强'拍头下压'意识，击球后拍头朝网。",

        # 放网/网前
        "放网": "放网质量差，力量过重或拍面太平，'轻抚球头'理念——几乎不下压。",
        "网前": "网前技术粗糙，练习'搓、勾、推、挑'四门基本功，体会不同手感。",
        "搓球": "搓球不够旋转，拍面过度下压，手腕'舀'的动作不足，应向前上方向送拍。",
        "勾球": "勾球角度不够，手腕外展幅度不足，练习'摸耳朵'式勾球轨迹。",
        "挑球": "挑球不够高不够后，甩腕不充分，拍面从下往上刷球头，力量传递到位。",

        # 整体协调
        "协调": "整体发力不协调，加强'全身协调'挥拍练习，镜前自查各环节顺序。",
        "流畅": "动作不够流畅，各环节脱节，建立'预判→到位→挥拍→随挥'四节拍。",
        "时机": "击球时机不对，过早起动或过晚，'看球拍触球瞬间再挥拍'。",
        "节奏": "比赛节奏乱，尝试'快慢结合'球路，主动变化节奏打乱对手。",
        "预判": "预判能力弱，盯对手肩和拍面，不盯球头，培养'提前起动'意识。",
        "前倾": "身体过度直立，重心未前移，击球前保持'蓄势待发'的微微前倾姿态。",
        "肩部": "肩部发力过多，手臂过僵，'大臂固定、小臂甩腕'，肩部保持稳定。",
        "肘部": "肘关节抬太高（架肘），平抽时尤为明显，大臂贴近身体，侧身抽球。",
        "松": "全身过紧，握拍太死，'握拍松、发力紧'——触球前手指放松，击球瞬间握紧。",
    }
    for err, cnt in top_errors:
        # 知识库检索（score字段不存在；以matched_qa非空判断命中）
        retriever = _get_retriever()
        kb_result = (retriever.search(err, top_k=2) if retriever else [])
        kb_q = kb_a = kb_video_title = kb_video_url = None
        article_result = next((r for r in kb_result if r.get('source') == 'article' and r.get('matched_qa')), None)
        video_result = next((r for r in kb_result if r.get('source') == 'video'), None)
        if article_result:
            qa_list = article_result['matched_qa']
            if qa_list:
                kb_q = qa_list[0]['q']
                kb_a = qa_list[0]['a']
        if video_result:
            kb_video_title = video_result.get('title', '')
            kb_video_url = video_result.get('url', '')

        tip = "建议加强基础动作练习。"
        for k, v in tips_map.items():
            if k in err:
                tip = v
                break
        c_y = pdf.y
        pdf.set_fill_color(255, 248, 248)
        pdf.set_draw_color(*C_RED)
        pdf.set_line_width(0.3)
        pdf.rect(LM, c_y, BW, 1, "FD")
        pdf.set_fill_color(*C_RED)
        pdf.rect(LM, c_y, 2, 1, "F")
        pdf.set_xy(LM + 5, c_y + 1)
        pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
        pdf.set_text_color(*C_RED)
        pdf.cell(BW - 10, 5, f"问题：{err}（{cnt}次）")
        pdf.ln(5)
        pdf.set_x(LM + 5)
        pdf.set_font("STHeiti", size=STYLE["F_BODY"])
        pdf.set_text_color(*C_GREY)
        pdf.multi_cell(BW - 10, 5, f"→ {tip}")
        pdf.y = c_y + 14

        # 知识库增强：专业Q&A（如果匹配度高）
        if kb_q and kb_a:
            # 中文字符在 STHeiti 8.5pt 下约 20 字/行；视频标题一行约 35 字
            # Q + A + 视频标题（可选）= 3 行基准 + 实际行数
            lines_q = max(1, (len(kb_q) - 1) // 20 + 1)
            lines_a = max(1, (len(kb_a) - 1) // 25 + 1)
            lines_vid = 1 + (1 if kb_video_url else 0)  # 标题 + URL（可选）
            estimated_h = 8 + lines_q * 5 + lines_a * 5 + lines_vid * 5 + 2
            if pdf.y + estimated_h > pdf.page_break_trigger - 10:
                pdf.add_page()
            box_y = pdf.y
            pdf.set_fill_color(245, 248, 255)
            pdf.set_draw_color(*C_BLUE)
            pdf.set_line_width(0.3)
            pdf.rect(LM, box_y, BW, estimated_h, "FD")
            pdf.set_fill_color(*C_BLUE)
            pdf.rect(LM, box_y, 2, estimated_h, "F")
            pdf.set_xy(LM + 5, box_y + 2)
            pdf.set_font("STHeiti", size=8.5)
            pdf.set_text_color(*C_BLUE)
            pdf.multi_cell(BW - 10, 5, f"专业参考：{kb_q}")
            pdf.set_x(LM + 5)
            pdf.set_font("STHeiti", size=8.5)
            pdf.set_text_color(*C_GREY)
            pdf.multi_cell(BW - 10, 5, f"{kb_a}")
            if kb_video_title:
                pdf.set_x(LM + 5)
                pdf.set_font("STHeiti", size=STYLE["F_MINI"])
                pdf.set_text_color(*C_BLUE)
                pdf.cell(BW - 10, 5, f"▶ {kb_video_title}")
                pdf.ln(4)
                # 视频链接（斜体灰色显示，节省空间）
                if kb_video_url:
                    vid_short = kb_video_url.replace('https://www.bilibili.com/video/', '▶  bilibili.com/')
                    pdf.set_x(LM + 5)
                    pdf.set_font("STHeiti", size=STYLE["F_TINY"])
                    pdf.set_text_color(*C_LIGHT)
                    pdf.cell(BW - 10, 4, vid_short)
            pdf.y = box_y + estimated_h + 2
        else:
            pdf.ln(2)

    pdf.ln(2)

    # ─── Section 5: 五维评分详情 ───
    if pdf.y > pdf.page_break_trigger - 90:
        pdf.add_page()
    pdf.set_fill_color(*C_BLUE)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "六、五维技术评分", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    DIMENSIONS = ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]

    # 计算本次各维度均分
    dim_avgs = {}
    for dim in DIMENSIONS:
        vals = [s.get(dim, 0) for s in shots if s.get(dim) is not None]
        dim_avgs[dim] = round(sum(vals) / len(vals), 1) if vals else 0

    # 五维进步数据（来自 player_db.compute_progress）
    dim_progress = progress.get("dim_progress", {})
    hist_avgs = {}
    for dim, ddata in dim_progress.items():
        hist_avgs[dim] = ddata.get("first")

    # ─── 五维雷达图（fpdf2 手绘） ───────────────────────────────────────────
    def _render_radar_chart(pdf, cx, cy, radius, scores, labels):
        """
        手动绘制5边形雷达图（fpdf2无内置雷达图）
        cx, cy: 中心点坐标（mm）
        radius: 主轴半径（mm），满分10分对应此半径
        scores: dict {维度名: 分数}，分数范围 0-10
        labels: 维度名称列表
        """
        import math

        n = 5  # 5个维度
        angle_step = 2 * math.pi / n  # 每72°一个顶点

        # 顶点相对于圆心的坐标（角度从顶点0（顶部）开始，逆时针分布）
        # 顶点0在顶部，即 -π/2（或 3π/2）
        def vertex_pos(i, r):
            ang = -math.pi / 2 + i * angle_step
            return (cx + r * math.cos(ang), cy + r * math.sin(ang))

        # ── 1. 画参考比例尺（灰色虚线多边形） ──────────────────────────────
        for scale in [0.25, 0.5, 0.75, 1.0]:
            pts = [vertex_pos(i, radius * scale) for i in range(n)]
            # 只画线，不填充
            pdf.set_draw_color(200, 200, 200)
            pdf.set_line_width(0.3)
            for i in range(n):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % n]
                pdf.line(x1, y1, x2, y2)

        # ── 2. 画5条轴线（圆心→顶点） ─────────────────────────────────────
        pdf.set_draw_color(180, 180, 180)
        pdf.set_line_width(0.4)
        for i in range(n):
            x1, y1 = cx, cy
            x2, y2 = vertex_pos(i, radius)
            pdf.line(x1, y1, x2, y2)

        # ── 3. 画数据多边形（半透明绿色填充 + 深绿边框） ──────────────────
        # 收集数据顶点
        data_pts = []
        for i, label in enumerate(labels):
            score = scores.get(label, 0)
            r = radius * min(score / 10.0, 1.0)  # 限制最大为radius
            data_pts.append(vertex_pos(i, r))

        # 填充多边形
        pdf.set_fill_color(39, 174, 96)  # C_GREEN
        pdf.set_draw_color(27, 130, 60)  # 深绿边框
        pdf.set_line_width(0.6)

        # 用 polygon 方法绘制填充多边形（stroke=True, fill=True）
        pdf.polygon(data_pts, style="DF")

        # 边框
        for i in range(n):
            x1, y1 = data_pts[i]
            x2, y2 = data_pts[(i + 1) % n]
            pdf.line(x1, y1, x2, y2)

        # ── 4. 各维度分数标注在轴线上（内侧） ──────────────────────────────
        pdf.set_font("STHeiti", size=8)
        pdf.set_text_color(60, 60, 60)
        for i, label in enumerate(labels):
            score = scores.get(label, 0)
            r_label = radius * min(score / 10.0, 1.0)
            ang = -math.pi / 2 + i * angle_step
            # 标注位置：半径的65%处，顺着轴线方向偏移一点
            lx = cx + r_label * math.cos(ang) * 0.65
            ly = cy + r_label * math.sin(ang) * 0.65
            pdf.set_xy(lx - 4, ly - 2)
            pdf.cell(8, 4, f"{score:.1f}", align="C")

        # ── 5. 维度标签挂在顶点外侧（避免重叠的偏移策略） ─────────────────
        pdf.set_font("STHeiti", size=9)
        pdf.set_text_color(*C_DARK)
        label_offsets = [
            (0, -8),      # 顶部 → 向上偏移
            (6, -5),      # 右上 → 右上
            (6, 6),       # 右下 → 右下
            (-14, 6),     # 左下 → 左下（向左多移避免压图）
            (-14, -5),    # 左上 → 左上
        ]
        for i, label in enumerate(labels):
            # 标签位置：顶点外侧 10mm
            ang = -math.pi / 2 + i * angle_step
            lx_off, ly_off = label_offsets[i]
            lx = cx + (radius + 10) * math.cos(ang) + lx_off
            ly = cy + (radius + 10) * math.sin(ang) + ly_off
            pdf.set_xy(lx, ly)
            pdf.cell(14, 4, label + "+10分", align="C")

        # ── 6. 中心圆点 ──────────────────────────────────────────────────
        pdf.set_fill_color(39, 174, 96)
        pdf.set_draw_color(27, 130, 60)
        pdf.set_line_width(0.3)
        pdf.ellipse(cx - 1.5, cy - 1.5, 3, 3, style="FD")

        # ── 7. 参考满分10分标注 ──────────────────────────────────────────
        pdf.set_font("STHeiti", size=6.5)
        pdf.set_text_color(160, 160, 160)
        pdf.set_xy(cx + radius * 0.98 - 6, cy + 1)
        pdf.cell(12, 3, "10分", align="R")
        pdf.set_xy(cx - 6, cy - radius * 0.98 - 2)
        pdf.cell(12, 3, "满分", align="C")

    # 页面宽度内绘制雷达图
    LM + 10
    chart_cx = LM + BW / 2
    chart_cy = pdf.y + 45  # 预留足够空间
    chart_radius = min(BW * 0.38, 60)  # 半径自适应页面宽度

    # 确保有足够空间
    if pdf.y + chart_radius * 2.5 + 20 > pdf.page_break_trigger:
        pdf.add_page()

    chart_cy = pdf.y + chart_radius + 15  # 重新定位

    # 画雷达图
    _render_radar_chart(pdf, chart_cx, chart_cy, chart_radius, dim_avgs, DIMENSIONS)

    # 雷达图下方输出各维度分项数值
    pdf.ln(2)
    score_card_w = BW / 5 - 2
    score_start_x = LM
    pdf.set_font("STHeiti", size=STYLE["F_BODY"])

    for i, dim in enumerate(DIMENSIONS):
        x = score_start_x + i * (score_card_w + 2)
        pdf.set_xy(x, chart_cy + chart_radius + 8)
        avg = dim_avgs[dim]
        prev = hist_avgs.get(dim)
        delta = round(avg - prev, 1) if prev is not None else None

        bar_color = TAG_C.get(int(round(avg)), C_GREY)

        # 分数色块
        pdf.set_fill_color(*bar_color)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("STHeiti", size=STYLE["F_CHART_SCORE"])
        pdf.cell(score_card_w, 8, f"{avg:.1f}", fill=True, align="C")

        # 维度名
        pdf.set_xy(x, chart_cy + chart_radius + 16)
        pdf.set_font("STHeiti", size=STYLE["F_TINY"])
        pdf.set_text_color(*C_GREY)
        pdf.cell(score_card_w, 4, dim, align="C")

        # 进步值
        if delta is not None:
            d_color = C_GREEN if delta > 0 else (C_RED if delta < 0 else C_ORG)
            sign = "+" if delta > 0 else ""
            d_icon = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            pdf.set_xy(x, chart_cy + chart_radius + 20)
            pdf.set_font("STHeiti", size=STYLE["F_TINY"])
            pdf.set_text_color(*d_color)
            pdf.cell(score_card_w, 4, f"{d_icon}{sign}{delta:.1f}", align="C")
        elif prev is None and progress.get("enough_data"):
            pdf.set_xy(x, chart_cy + chart_radius + 20)
            pdf.set_font("STHeiti", size=STYLE["F_TINY"])
            pdf.set_text_color(180, 180, 180)
            pdf.cell(score_card_w, 4, "首次", align="C")

    pdf.ln(chart_radius * 2 + 30)

    # ─── Section 6: 历史进步对比 ───
    if progress.get("enough_data") and progress.get("total_sessions", 0) >= 2:
        if pdf.y > pdf.page_break_trigger - 70:
            pdf.add_page()
        pdf.set_fill_color(*C_GREEN)
        pdf.rect(LM, pdf.y - 1, 3, 10, "F")
        pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
        pdf.set_text_color(*C_MID)
        pdf.set_x(LM + 6)
        pdf.cell(0, 8, "六、进步跟踪", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        delta = progress["delta"]
        sign = "+" if delta > 0 else ""
        trend = progress.get("quality_trend", {})
        t_str = "上升" if delta > 0 else ("下降" if delta < 0 else "持平")

        pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
        pdf.set_text_color(*C_GREY)
        pdf.multi_cell(BW, 6, f"从 {progress['first_avg']} 分（{progress['first_date']}）"
                             f" → {progress['latest_avg']} 分（{progress['latest_date']}），"
                             f"综合总分 {sign}{delta} 分，{t_str}。")
        pdf.ln(2)

        # 改善项目
        improved = progress.get("improved_errors", [])
        worsened = progress.get("worsened_errors", [])
        progress.get("new_errors", [])

        imp_w = [BW * 0.45, BW * 0.18, BW * 0.18, BW * 0.19]
        imp_x = [LM, LM + imp_w[0], LM + imp_w[0] + imp_w[1], LM + imp_w[0] + imp_w[1] + imp_w[2]]
        imp_headers = ["问题", "上次", "本次", "变化"]

        if improved:
            pdf.set_font("STHeiti", size=STYLE["F_BODY"])
            pdf.set_text_color(*C_GREEN)
            pdf.cell(0, 6, f"改善项目（{len(improved)}项）", new_x="LMARGIN", new_y="NEXT")
            pdf.set_fill_color(*C_MID)
            pdf.set_text_color(255, 255, 255)
            headers = ["问题", "上次", "本次", "变化"]
            for h, cx, w in zip(headers, imp_x, imp_w):
                pdf.set_xy(cx, pdf.y)
                pdf.cell(w, 7, h, border=1, fill=True, align="C")
            pdf.y += 7
            for i, item in enumerate(improved[:5]):
                fc2 = (240, 255, 245) if i % 2 == 0 else (255, 255, 255)
                pdf.set_fill_color(*fc2)
                row_data = [item["error"][:18], f"{item['from']}次", f"{item['to']}次", f"↓ {item['from']-item['to']}次"]
                for val, cx, w in zip(row_data, imp_x, imp_w):
                    pdf.set_fill_color(*fc2)
                    pdf.rect(cx, pdf.y, w, 8, "FD")
                    pdf.set_xy(cx, pdf.y)
                    pdf.set_font("STHeiti", size=8.5)
                    pdf.set_text_color(C_GREEN if "变化" in imp_headers[imp_x.index(cx)] else C_GREY)
                    pdf.cell(w, 8, val, border=0, fill=False, align="C")
                pdf.y += 8
            pdf.ln(3)

        if worsened:
            pdf.set_font("STHeiti", size=STYLE["F_BODY"])
            pdf.set_text_color(*C_RED)
            pdf.cell(0, 6, f"加重项目（{len(worsened)}项）", new_x="LMARGIN", new_y="NEXT")
            for i, item in enumerate(worsened[:5]):
                fc2 = (255, 245, 245) if i % 2 == 0 else (255, 255, 255)
                row_data = [item["error"][:18], f"{item['from']}次", f"{item['to']}次", f"↑ {item['to']-item['from']}次"]
                for val, cx, w in zip(row_data, imp_x, imp_w):
                    pdf.set_fill_color(*fc2)
                    pdf.rect(cx, pdf.y, w, 8, "FD")
                    pdf.set_xy(cx, pdf.y)
                    pdf.set_font("STHeiti", size=8.5)
                    pdf.set_text_color(C_RED if "变化" in imp_headers[imp_x.index(cx)] else C_GREY)
                    pdf.cell(w, 8, val, border=0, fill=False, align="C")
                pdf.y += 8
            pdf.ln(3)

    # ─── Section 7: 评分曲线图（matplotlib → PDF） ───────────
    if progress.get("enough_data") and len(sessions) >= 2:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from PIL import Image as PILImage  # ← 加这行

        plt.rcParams["font.family"] = ["STHeiti", "Arial Unicode MS"]
        plt.rcParams["axes.unicode_minus"] = False

        dates = [s.get("date", "")[-5:] for s in sessions]  # MM-DD
        avgs  = [s.get("avg_quality", 0) for s in sessions]
        dims  = ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]
        dim_colors = ["#E53935", "#FF9800", "#43A047", "#1E88E5", "#8E24AA"]

        fig, ax = plt.subplots(figsize=(7, 3.2))
        ax.set_facecolor("#F5F7FA")
        fig.patch.set_facecolor("#F5F7FA")

        # 综合均分曲线
        ax.plot(range(len(avgs)), avgs, "o-", color="#1A237E", linewidth=2,
                markersize=7, zorder=5, label="综合评分")
        for i, v in enumerate(avgs):
            ax.annotate(f"{v:.1f}", (i, v), textcoords="offset points",
                       xytext=(0, 8), ha="center", fontsize=8,
                       color="#1A237E", fontweight="bold")

        # 五维曲线（淡色）
        for di, dim in enumerate(dims):
            dim_vals = []
            for s in sessions:
                vals = [shot.get(dim) for shot in s.get("shots", []) if shot.get(dim) is not None]
                dim_vals.append(round(sum(vals)/len(vals), 1) if vals else 0)
            if any(v > 0 for v in dim_vals):
                ax.plot(range(len(dim_vals)), dim_vals, "o--", color=dim_colors[di],
                       linewidth=1.2, markersize=4, alpha=0.6, label=dim)

        ax.set_xticks(range(len(dates)))
        ax.set_xticklabels(dates, fontsize=8)
        ax.set_ylim(0, 10.5)
        ax.set_ylabel("评分", fontsize=9)
        ax.set_title("技术评分历史变化", fontsize=11, fontweight="bold", color="#1A237E")
        ax.legend(loc="lower right", fontsize=7, framealpha=0.8)
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        chart_path = f"/tmp/bad_shots/score_chart_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        plt.tight_layout()
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close()

        if pdf.y > pdf.page_break_trigger - 100:
            pdf.add_page()

        pdf.set_fill_color(*C_ORG)
        pdf.rect(LM, pdf.y - 1, 3, 10, "F")
        pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
        pdf.set_text_color(*C_MID)
        pdf.set_x(LM + 6)
        pdf.cell(0, 8, "七、技术评分历史曲线", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        if os.path.exists(chart_path):
            iw, ih = PILImage.open(chart_path).size
            ratio = ih / iw
            cw = BW
            ch = min(cw * ratio, 70)
            pdf.image(chart_path, x=LM, y=pdf.y, w=cw, h=ch)
            pdf.y += ch + 4
        pdf.ln(3)

    # ─── Section 8: 徽章成就墙 ───────────────────────────────
    all_badges = data.get("all_badges", [])
    new_badges = data.get("new_badges", [])
    if all_badges:
        if pdf.y > pdf.page_break_trigger - 60:
            pdf.add_page()
        pdf.set_fill_color(*C_GOLD if new_badges else C_BLUE)
        pdf.rect(LM, pdf.y - 1, 3, 10, "F")
        pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
        pdf.set_text_color(*C_MID)
        pdf.set_x(LM + 6)
        badge_title = "八、成就徽章"
        if new_badges:
            new_names = [b["name"] for b in all_badges if b["id"] in new_badges]
            badge_title += f"  ★ 新解锁：{' / '.join(new_names)}"
        pdf.cell(0, 8, badge_title, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # ── 徽章颜色配置（按稀有度） ─────────────────────────────────────────
        BADGE_COLOR_MAP = {
            # 铜色：首次 / ×3
            "first_analysis": (205, 127, 50),    # #CD7F32
            "streak_3":      (205, 127, 50),
            # 银色：×7
            "streak_7":      (192, 192, 192),    # #C0C0C0
            # 金色：×30 / 8+ / 9+
            "streak_30":     (255, 215, 0),      # #FFD700
            "score_break_8": (255, 215, 0),
            "score_break_9": (255, 215, 0),
            # 默认：铜色
        }
        # 备用铜色（当 id 不在 map 中时）
        DEFAULT_COLOR = (205, 127, 50)

        # ── 图标 Unicode 映射 ─────────────────────────────────────────────────
        BADGE_ICON_MAP = {
            "first_analysis": "⚡",
            "streak_3":      "🔥",
            "streak_7":      "💎",
            "streak_30":     "👑",
            "score_break_8": "🎯",
            "score_break_9": "🏆",
        }

        [b for b in all_badges if b["earned"]]
        cols = 4
        cell_w = BW / cols
        row_h = 18   # 稍微增高以容纳圆形徽章
        badge_r = 6  # 徽章圆形半径（mm）

        for idx, b in enumerate(all_badges):
            col = idx % cols
            row = idx // cols
            bx = LM + col * cell_w
            by = pdf.y + row * row_h
            if by + row_h > pdf.page_break_trigger:
                pdf.add_page()
                by = pdf.y
                pdf.y += row * row_h

            # 徽章圆心
            bcx = bx + cell_w / 2
            bcy = by + badge_r + 1

            is_earned = b["earned"]
            badge_id = b["id"]
            base_color = BADGE_COLOR_MAP.get(badge_id, DEFAULT_COLOR)

            if is_earned:
                # ── 已解锁：实心圆 + 渐变光泽效果 ──────────────────────────────
                # 外圈金属质感（稍大的暗色圈）
                pdf.set_fill_color(max(0, base_color[0] - 60),
                                   max(0, base_color[1] - 60),
                                   max(0, base_color[2] - 60))
                pdf.ellipse(bcx - badge_r - 1, bcy - badge_r - 1,
                            (badge_r + 1) * 2, (badge_r + 1) * 2, "F")

                # 主体渐变（从中心向外颜色渐浅，模拟金属光泽）
                # 最外层：深色边框
                pdf.set_fill_color(max(0, base_color[0] - 40),
                                   max(0, base_color[1] - 40),
                                   max(0, base_color[2] - 40))
                pdf.ellipse(bcx - badge_r - 0.5, bcy - badge_r - 0.5,
                            (badge_r + 0.5) * 2, (badge_r + 0.5) * 2, "F")

                # 第二层：主体色
                pdf.set_fill_color(*base_color)
                pdf.ellipse(bcx - badge_r, bcy - badge_r,
                            badge_r * 2, badge_r * 2, "F")

                # 第三层：内层高光（颜色减淡，模拟光泽）
                lighter = tuple(min(255, c + 60) for c in base_color)
                pdf.set_fill_color(*lighter)
                pdf.ellipse(bcx - badge_r + 1.5, bcy - badge_r + 1.5,
                            (badge_r - 1.5) * 2, (badge_r - 1.5) * 2, "F")

                # 中心符号
                icon_char = BADGE_ICON_MAP.get(badge_id, b["icon"])
                pdf.set_font("STHeiti", size=11)
                pdf.set_text_color(255, 255, 255)
                pdf.set_xy(bcx - 5, bcy - 4)
                pdf.cell(10, 8, icon_char, align="C")

                # 徽章名称（底部）
                pdf.set_xy(bx + 1, bcy + badge_r + 0.5)
                pdf.set_font("STHeiti", size=STYLE["F_TINY"])
                pdf.set_text_color(*C_DARK)
                pdf.cell(cell_w - 2, 4, b["name"], align="C")

                # 解锁条件（小字，灰色）
                pdf.set_xy(bx + 1, bcy + badge_r + 4)
                pdf.set_font("STHeiti", size=6.5)
                pdf.set_text_color(*C_LIGHT)
                pdf.cell(cell_w - 2, 3.5, b["desc"], align="C")

            else:
                # ── 未解锁：半透明灰色描边 + 虚线 ──────────────────────────────
                # 底色（暗灰）
                pdf.set_fill_color(230, 230, 230)
                pdf.ellipse(bcx - badge_r, bcy - badge_r,
                            badge_r * 2, badge_r * 2, "F")

                # 灰色描边圆
                pdf.set_draw_color(180, 180, 180)
                pdf.set_line_width(0.8)
                pdf.ellipse(bcx - badge_r, bcy - badge_r,
                            badge_r * 2, badge_r * 2, style="D")

                # 内部加一条虚线（模拟未解锁状态）
                pdf.set_draw_color(200, 200, 200)
                pdf.set_line_width(0.4)
                pdf.ellipse(bcx - badge_r + 2, bcy - badge_r + 2,
                            (badge_r - 2) * 2, (badge_r - 2) * 2, style="D")

                # 问号占位符
                pdf.set_font("STHeiti", size=10)
                pdf.set_text_color(180, 180, 180)
                pdf.set_xy(bcx - 5, bcy - 4)
                pdf.cell(10, 8, "?", align="C")

                # 徽章名称（底部，灰色）
                pdf.set_xy(bx + 1, bcy + badge_r + 0.5)
                pdf.set_font("STHeiti", size=STYLE["F_TINY"])
                pdf.set_text_color(160, 160, 160)
                pdf.cell(cell_w - 2, 4, b["name"], align="C")

                # 解锁条件（小字，浅灰）
                pdf.set_xy(bx + 1, bcy + badge_r + 4)
                pdf.set_font("STHeiti", size=6.5)
                pdf.set_text_color(180, 180, 180)
                pdf.cell(cell_w - 2, 3.5, b["desc"], align="C")

        pdf.y += (len(all_badges) // cols + 1) * row_h + 4

    pdf.output(output_path)
    sz = os.path.getsize(output_path)
    print(f"报告生成: {output_path} ({sz//1024}KB)")
    return output_path


if __name__ == "__main__":
    print("报告生成模块加载正常")


# ── 每月进步报告生成 ─────────────────────────────────────────────────────────

def generate_monthly_report(name: str, year: int, month: int, output_dir: str = None) -> str:
    """
    生成球员月度进步报告 PDF。
    布局：
      - 顶部标题："{name} 的 {year}年{month}月 进步报告"
      - 概览卡片：本月分析N次、本月均分、上月均分、分数变化（↑/↓/+0）
      - 进步项目：列出当月改善的错误
      - 关键帧对比：本月最早 vs 本月最晚同动作帧图并排（最多3组）
      - 成就徽章：本月新解锁的徽章
      - 底部："分享到朋友圈"占位

    返回 PDF 文件路径，无数据时返回空字符串。
    """
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from player_db import get_monthly_report, get_player_dir

    report_data = get_monthly_report(name, year, month)
    if not report_data:
        return ""

    if output_dir is None:
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        output_dir = reports_dir

    import datetime as _dt
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"月度报告_{year}年{month:02d}月_{name}_{ts}.pdf")

    pdf = Report()
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_font("STHeiti", fname=ASSETS_FONT, uni=True)
    pdf.add_page()

    LM = pdf.l_margin
    RM = pdf.r_margin
    BW = pdf.w - LM - RM

    # ─── 标题栏 ───────────────────────────────────────────
    pdf.set_fill_color(*C_MID)
    pdf.rect(LM, pdf.y - 4, 3, 30, "F")
    pdf.set_font("STHeiti", size=STYLE["F_TITLE"])
    pdf.set_text_color(*C_DARK)
    pdf.set_x(LM + 8)
    pdf.cell(BW - 8, 13, f"{name} 的 {year}年{month}月 进步报告", align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("STHeiti", size=STYLE["F_BODY"])
    pdf.set_text_color(*C_LIGHT)
    pdf.set_x(LM + 8)
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf.cell(BW - 8, 6, f"生成时间：{generated}", align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_fill_color(*C_MID)
    pdf.rect(LM, pdf.y, BW, 1.5, "F")
    pdf.ln(4)

    # ─── 概览卡片 ─────────────────────────────────────────
    session_count = report_data.get("session_count", 0)
    avg_quality = report_data.get("avg_quality", 0)
    prev_avg = report_data.get("prev_avg_quality")
    delta = report_data.get("delta")

    # 卡片尺寸
    card_h = 18
    card_colors = [
        (C_MID, "本月分析次数", str(session_count), "次"),
        (C_BLUE, "本月均分", f"{avg_quality:.1f}", "分"),
    ]
    if prev_avg is not None:
        if delta is not None:
            if delta > 0:
                delta_icon = "↑"
                delta_color = C_GREEN
                delta_str = f"+{delta:.1f}"
            elif delta < 0:
                delta_icon = "↓"
                delta_color = C_RED
                delta_str = f"{delta:.1f}"
            else:
                delta_icon = "→"
                delta_color = C_ORG
                delta_str = "+0"
        else:
            delta_icon = ""
            delta_color = C_GREY
            delta_str = "-"

        card_colors.append((delta_color, "分数变化", f"{delta_icon}{delta_str}" if delta_icon else delta_str, ""))
        card_colors.append((C_ORG, "上月均分", f"{prev_avg:.1f}", "分"))
    else:
        card_colors.append((C_GREY, "上月均分", "无数据", ""))

    card_w = BW / len(card_colors)
    card_xs = [LM + i * card_w for i in range(len(card_colors))]

    for i, (color, label, value, unit) in enumerate(card_colors):
        cx = card_xs[i]
        cy = pdf.y
        pdf.set_fill_color(*color)
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.3)
        pdf.rect(cx, cy, card_w - 2, card_h, "FD")

        # 顶部色条
        pdf.set_fill_color(*color)
        pdf.rect(cx, cy, card_w - 2, 3, "F")

        # 标签
        pdf.set_xy(cx, cy + 3)
        pdf.set_font("STHeiti", size=STYLE["F_MINI"])
        pdf.set_text_color(255, 255, 255)
        pdf.cell(card_w - 2, 5, label, align="C")

        # 数值
        pdf.set_xy(cx, cy + 8)
        pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
        pdf.set_text_color(255, 255, 255)
        pdf.cell(card_w - 2, 8, f"{value}", align="C")
        if unit:
            pdf.set_font("STHeiti", size=STYLE["F_MINI"])
            pdf.cell(card_w - 2, 5, unit, align="C")

    pdf.y += card_h + 5

    # ─── 进步/退步项目 ─────────────────────────────────────
    improved = report_data.get("improved_errors", [])
    worsened = report_data.get("worsened_errors", [])

    if improved or worsened:
        pdf.set_fill_color(*C_GREEN)
        pdf.rect(LM, pdf.y - 1, 3, 10, "F")
        pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
        pdf.set_text_color(*C_MID)
        pdf.set_x(LM + 6)
        pdf.cell(0, 8, "本月技术进步", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        if improved:
            pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
            pdf.set_text_color(*C_GREEN)
            pdf.cell(BW, 5, f"改善了 {len(improved)} 项错误 ↓", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
            for item in improved[:5]:  # 最多显示5项
                err_text = item.get("error", "")[:40]
                pdf.set_font("STHeiti", size=STYLE["F_BODY"])
                pdf.set_text_color(*C_GREY)
                from_c = item.get("from", 0)
                to_c = item.get("to", 0)
                pdf.cell(BW, 5, f"  • {err_text}（{from_c} → {to_c}）", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
            pdf.set_text_color(*C_LIGHT)
            pdf.cell(BW, 5, "  本月无新增改善项", new_x="LMARGIN", new_y="NEXT")

        if worsened:
            pdf.ln(2)
            pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
            pdf.set_text_color(*C_RED)
            pdf.cell(BW, 5, f"需要注意 {len(worsened)} 项错误 ↑", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
            for item in worsened[:3]:  # 最多显示3项
                err_text = item.get("error", "")[:40]
                pdf.set_font("STHeiti", size=STYLE["F_BODY"])
                pdf.set_text_color(*C_GREY)
                from_c = item.get("from", 0)
                to_c = item.get("to", 0)
                pdf.cell(BW, 5, f"  • {err_text}（{from_c} → {to_c}）", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # ─── 关键帧对比 ────────────────────────────────────────
    sessions = report_data.get("sessions", [])
    if len(sessions) >= 2:
        # 获取 frame_archive 路径
        player_dir = get_player_dir(name)
        frame_archive_dir = os.path.join(player_dir, "frame_archive")

        # 按日期排序sessions
        sorted_sessions = sorted(sessions, key=lambda s: s.get("date", ""))

        # 找到最早和最晚的 session
        first_session = sorted_sessions[0]
        last_session = sorted_sessions[-1]

        # 按动作类型匹配帧图
        first_shots = {s.get("action_type", ""): s.get("frame_file", "") for s in first_session.get("shots", [])}
        last_shots = {s.get("action_type", ""): s.get("frame_file", "") for s in last_session.get("shots", [])}

        # 找到共同的 action_type
        common_actions = set(first_shots.keys()) & set(last_shots.keys())
        common_actions = [a for a in common_actions if a and a not in ("分析失败",)]

        if common_actions:
            pdf.set_fill_color(*C_BLUE)
            pdf.rect(LM, pdf.y - 1, 3, 10, "F")
            pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
            pdf.set_text_color(*C_MID)
            pdf.set_x(LM + 6)
            pdf.cell(0, 8, "关键帧对比", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            # 子标题
            pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
            pdf.set_text_color(*C_LIGHT)
            pdf.cell(BW, 5, f"最早（{first_session.get('date', '')}）→ 最晚（{last_session.get('date', '')}）", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            # 最多3组对比
            compare_count = min(3, len(common_actions))
            compare_actions = common_actions[:compare_count]

            for action in compare_actions:
                # 检查是否需要换页
                if pdf.y > pdf.page_break_trigger - 50:
                    pdf.add_page()

                frame_first = first_shots.get(action, "")
                frame_last = last_shots.get(action, "")

                # 日期标签
                pdf.set_font("STHeiti", size=STYLE["F_BODY"])
                pdf.set_text_color(*C_GREY)
                pdf.cell(BW / 2 - 5, 5, f"早期: {first_session.get('date', '')}", align="L")
                pdf.cell(BW / 2 - 5, 5, f"近期: {last_session.get('date', '')}", align="L", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)

                # 两张图并排
                half_w = (BW - 10) / 2
                img_h = 30

                # 左图（早期）
                if frame_first:
                    img_path_first = os.path.join(frame_archive_dir, first_session.get("date", ""), frame_first)
                    if os.path.exists(img_path_first):
                        try:
                            from PIL import Image as PILImage
                            im = PILImage.open(img_path_first)
                            iw, ih = im.size
                            ratio = ih / iw
                            dh = min(half_w * ratio, img_h)
                            pdf.image(img_path_first, x=LM, y=pdf.y, w=half_w, h=dh)
                        except Exception:
                            pdf.set_fill_color(240, 240, 240)
                            pdf.rect(LM, pdf.y, half_w, img_h, "D")
                    else:
                        pdf.set_fill_color(240, 240, 240)
                        pdf.rect(LM, pdf.y, half_w, img_h, "D")
                else:
                    pdf.set_fill_color(240, 240, 240)
                    pdf.rect(LM, pdf.y, half_w, img_h, "D")

                # 右图（近期）
                if frame_last:
                    img_path_last = os.path.join(frame_archive_dir, last_session.get("date", ""), frame_last)
                    if os.path.exists(img_path_last):
                        try:
                            from PIL import Image as PILImage
                            im = PILImage.open(img_path_last)
                            iw, ih = im.size
                            ratio = ih / iw
                            dh = min(half_w * ratio, img_h)
                            pdf.image(img_path_last, x=LM + half_w + 5, y=pdf.y, w=half_w, h=dh)
                        except Exception:
                            pdf.set_fill_color(240, 240, 240)
                            pdf.rect(LM + half_w + 5, pdf.y, half_w, img_h, "D")
                    else:
                        pdf.set_fill_color(240, 240, 240)
                        pdf.rect(LM + half_w + 5, pdf.y, half_w, img_h, "D")
                else:
                    pdf.set_fill_color(240, 240, 240)
                    pdf.rect(LM + half_w + 5, pdf.y, half_w, img_h, "D")

                pdf.y += img_h + 2

                # 动作类型标签
                pdf.set_font("STHeiti", size=STYLE["F_MINI"])
                pdf.set_text_color(*C_LIGHT)
                pdf.cell(half_w, 4, action, align="C")
                pdf.cell(half_w + 5, 4, action, align="C", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(3)

    # ─── 成就徽章 ─────────────────────────────────────────
    new_badges = report_data.get("new_badges", [])
    if new_badges:
        if pdf.y > pdf.page_break_trigger - 40:
            pdf.add_page()

        pdf.set_fill_color(*C_GOLD)
        pdf.rect(LM, pdf.y - 1, 3, 10, "F")
        pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
        pdf.set_text_color(*C_MID)
        pdf.set_x(LM + 6)
        pdf.cell(0, 8, "本月新解锁徽章", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        badge_cols = 4
        badge_cell_w = BW / badge_cols
        badge_row_h = 14

        for idx, badge in enumerate(new_badges):
            col = idx % badge_cols
            row = idx // badge_cols
            bx = LM + col * badge_cell_w
            by = pdf.y + row * badge_row_h

            if by + badge_row_h > pdf.page_break_trigger:
                pdf.add_page()
                by = pdf.y

            pdf.set_fill_color(*C_GOLD)
            pdf.rect(bx + 1, by, badge_cell_w - 2, badge_row_h - 2, "FD")

            pdf.set_xy(bx + 1, by + 1)
            pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
            pdf.set_text_color(255, 255, 255)
            pdf.cell(badge_cell_w - 2, 8, badge.get("icon", "?"), align="C")

            pdf.set_xy(bx + 1, by + 9)
            pdf.set_font("STHeiti", size=STYLE["F_TINY"])
            pdf.set_text_color(*C_DARK)
            pdf.cell(badge_cell_w - 2, 4, badge.get("name", ""), align="C")

        pdf.y += (len(new_badges) // badge_cols + 1) * badge_row_h + 4

    # ─── 分享占位 ──────────────────────────────────────────
    if pdf.y > pdf.page_break_trigger - 30:
        pdf.add_page()

    pdf.ln(5)
    pdf.set_fill_color(240, 240, 240)
    pdf.rect(LM, pdf.y, BW, 20, "F")

    pdf.set_xy(LM, pdf.y + 3)
    pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
    pdf.set_text_color(*C_LIGHT)
    pdf.cell(BW, 6, "分享到朋友圈", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(LM, pdf.y + 1)
    pdf.set_font("STHeiti", size=STYLE["F_TINY"])
    pdf.set_text_color(200, 200, 200)
    pdf.cell(BW, 5, "— 月度进步报告 · 羽毛球视频分析小程序 —", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.output(output_path)
    sz = os.path.getsize(output_path)
    print(f"月度报告生成: {output_path} ({sz // 1024}KB)")
    return output_path

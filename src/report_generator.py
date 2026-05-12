# -*- coding: utf-8 -*-
"""
羽毛球视频分析小程序 - PDF 报告生成模块
基于 fpdf2，支持球员历史进步对比
"""
import os, sys, json, datetime, re
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
    F_MINI         =  8,
    F_TINY         =  7.5,
    F_CHART_SCORE  = 11,

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

from fpdf import FPDF
import sys
sys.path.insert(0, '/tmp')
from knowledge_retriever import KnowledgeRetriever

# 懒加载知识库（首次使用时初始化）
_kb_retriever = None
def _get_retriever():
    global _kb_retriever
    if _kb_retriever is None:
        _kb_retriever = KnowledgeRetriever()
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
    translated = text
    # 按长度从长到短排序，确保优先匹配更长短语
    sorted_items = sorted(_TRANSLATION_DICT.items(), key=lambda x: len(x[0]), reverse=True)
    for en, zh in sorted_items:
        translated = translated.replace(en, zh)
    return translated


def _infer_action_types(shots):
    """
    VLM 单帧无法区分杀球/高远球/吊球，
    通过 error_codes 关键词反向推断具体动作类型。
    同时将 generic "后场击球（单帧推断）" 替换为推断结果。
    """
    from collections import Counter
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
            if   smash_hit: shot["action_type"] = "正手杀球"
            elif clear_hit: shot["action_type"] = "正手高远球"
            elif drop_hit:  shot["action_type"] = "正手吊球"
        elif hits > 1:
            # 多个命中：取最高权重
            # 下压/重扣/杀球 → 杀球；高远球/弧度 → 高远球；其他 → 吊球
            if smash_hit:  shot["action_type"] = "正手杀球"
            elif clear_hit: shot["action_type"] = "正手高远球"
            else:           shot["action_type"] = "正手吊球"
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
    pdf.add_font("STHeiti", "", ASSETS_FONT)
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
        trend_c = trend_color(session.get("quality_trend", ""))

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
        pdf.ln(1)

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
            pdf.cell(BW * 0.25, 5, label, align="L")
            # 彩色条：慢=绿，中=黄，快=橙，极=红
            if "慢速" in label:
                bar_c = C_GREEN
            elif "中速" in label:
                bar_c = C_GOLD
            elif "快速" in label:
                bar_c = C_ORG
            else:
                bar_c = C_RED
            pdf.set_fill_color(*bar_c)
            pdf.rect(pdf.x, pdf.y - 4, bar_w, 5, "F")
            pdf.set_text_color(*C_GREY)
            pdf.cell(BW * 0.1, 5, f" {cnt}")
            pdf.ln(5)
        pdf.ln(2)

    pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
    pdf.cell(0, 6, "主要技术问题分布：", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    err_cnt = Counter()
    for s in shots:
        for e in s.get("errors", []):
            k = clean_err(e, 40)
            if len(k) > 2:
                err_cnt[k] += 1

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
        fill = (i % 2 == 0)
        err_fc = (255, 245, 245) if fill else (255, 255, 255)
        row_h = max(9, (len(err) // 24 + 1) * 9)

        cur_y = pdf.y
        pdf.set_fill_color(*err_fc)
        pdf.rect(ex[0], cur_y, ew[0], row_h, "FD")
        pdf.rect(ex[1], cur_y, ew[1], row_h, "FD")

        pdf.set_xy(ex[0], cur_y)
        pdf.set_font("STHeiti", size=STYLE["F_BODY"])
        pdf.set_text_color(*C_GREY)
        pdf.multi_cell(ew[0], 4.5, err, border=0)

        pdf.set_xy(ex[1], cur_y)
        pdf.set_font("STHeiti", size=STYLE["F_BODY"])
        pdf.set_text_color(*C_RED)
        pdf.cell(ew[1], row_h, f"{cnt}次", border=0, fill=False, align="C")

        pdf.y = cur_y + row_h
    pdf.ln(5)

    # ─── Section 3: 详细动作分析 ───
    pdf.set_fill_color(*C_BLUE)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "三、详细技术分析", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    stars_map = {0:"☆☆☆☆☆☆☆☆☆☆", 1:"★☆☆☆☆☆☆☆☆☆", 2:"★★☆☆☆☆☆☆☆☆", 3:"★★★☆☆☆☆☆☆☆", 4:"★★★★☆☆☆☆☆☆", 5:"★★★★★☆☆☆☆☆", 6:"★★★★★★☆☆☆☆", 7:"★★★★★★★☆☆☆", 8:"★★★★★★★★☆☆", 9:"★★★★★★★★★☆", 10:"★★★★★★★★★★"}

    IMG_W_MM = 65
    IMG_H_MM = 36
    from PIL import Image as PILImage

    # ── 同类型错误去重：每类错误只配一张图，后续仅文字 ──────────────
    shown_error_keys = set()   # 已配图的错误类型
    NO_IMG = object()          # 标记"此卡不配图"

    # 预扫描：每个 shot 应该用哪条 error 配图（None=不放图）
    shot_img_error = {}        # shot_idx → error 文本 or NO_IMG or None
    for i, shot in enumerate(shots):
        errors = shot.get("errors", [])
        chosen = None
        for e in errors[:2]:   # 只看前两条
            key = clean_err(e, 40)
            if key not in shown_error_keys and len(key) > 2:
                chosen = e
                shown_error_keys.add(key)
                break
        shot_img_error[i] = chosen   # None=无error，None!NO_IMG=有error但都重复

    # 重置，进入正式渲染
    shown_error_keys = set()

    for i, shot in enumerate(shots):
        q = shot.get("quality_rating", 3)
        ql = qlabel(q)
        tc = TAG_C.get(int(round(q)), C_LIGHT)

        action_type = _translate_action_type(shot.get("action_type", ""))

        # 分析失败且无实质内容：跳过此帧，不绘制卡片
        if action_type == "分析失败" and not shot.get("errors") and not shot.get("suggestions"):
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
        # shots 数据源有两个版本：frames_results 用 frame_file，analyze_shots 用 frames[0]
        _frames = shot.get("frames", [])
        frame_file = shot.get("frame_file", _frames[0] if _frames else "")
        frames_dir = data.get("frames_dir", "")
        # frames_dir 必须指向有效目录；拒绝 /tmp/bad_shots/target_frames 等污染路径
        _FORBIDDEN = ("/tmp/bad_shots", "/tmp/session_frames")
        if not frames_dir or not os.path.isdir(frames_dir) \
           or any(frames_dir.startswith(f) for f in _FORBIDDEN):
            frames_dir = ""
        img_path = f"{frames_dir}/{frame_file}" if frame_file else ""
        txt_x = LM + IMG_W_MM + 5
        txt_w = pdf.w - LM - pdf.r_margin - IMG_W_MM - 5

        # 图片（带球员标注）- 同类型错误只配一次图，其余留空线框
        this_img_err = shot_img_error.get(i)        # None/NO_IMG/具体error文本
        render_img = (this_img_err is not None and this_img_err is not NO_IMG
                      and frame_file and os.path.isfile(img_path))
        if render_img:
            # 标记此错误类型已配图，后续相同类型不再配图
            err_key = clean_err(this_img_err, 40)
            shown_error_keys.add(err_key)

        if render_img:
            try:
                from PIL import Image as PILImage, ImageDraw, ImageFont
                im = PILImage.open(img_path)
                iw, ih = im.size
                draw = ImageDraw.Draw(im)

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
                    ann_dir = os.path.dirname(img_path) if img_path else ""
                    if ann_dir and os.path.isdir(ann_dir):
                        tmp_path = f"{ann_dir}/ann_{frame_file}"
                        im.convert("RGB").save(tmp_path, "JPEG", quality=85)
                        img_path_ann = tmp_path
                    else:
                        img_path_ann = img_path
                else:
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
                    pdf.image(img_path_ann, x=LM, y=body_y, w=draw_w, h=IMG_H_MM)
                else:
                    pdf.image(img_path_ann, x=LM, y=body_y, w=IMG_W_MM, h=draw_h)
            except Exception as e:
                print(f"  [!] 标注失败: {e}")
                pdf.rect(LM, body_y, IMG_W_MM, IMG_H_MM, "D")
        else:
            # 无图：留空线框，浅灰背景
            pdf.set_fill_color(248, 248, 248)
            pdf.set_draw_color(210, 210, 210)
            pdf.set_line_width(0.3)
            pdf.rect(LM, body_y, IMG_W_MM, IMG_H_MM, "FD")
            # 中间显示简短说明
            pdf.set_font("STHeiti", size=7)
            pdf.set_text_color(180, 180, 180)
            note = ""
            if this_img_err is NO_IMG:
                note = "同类问题见上图"
            elif this_img_err:
                note = f"等问题：{clean_err(this_img_err, 14)}"
            if note:
                pdf.set_xy(LM, body_y + IMG_H_MM/2 - 3)
                pdf.cell(IMG_W_MM, 6, note, align="C")

        # 文字
        pdf.set_xy(txt_x, body_y)
        pdf.set_font("STHeiti", size=8.5)
        end_y = body_y

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

        # 卡片底部 = 图片底部 和 文字底部 的较大者
        card_bottom = max(body_y + IMG_H_MM, end_y) + 4
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
    pdf.cell(0, 8, "四、教练总结与建议", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    top_errors = err_cnt.most_common(3)
    summary = [f"本次分析共 {len(shots)} 个有效动作样本，整体技术评分 {avg_q:.1f}/10。"]
    if top_errors:
        summary.append(f"最突出问题：「{top_errors[0][0]}」（出现 {top_errors[0][1]} 次），建议重点练习。")
    if session.get("quality_trend"):
        t = session["quality_trend"]
        t_icon = trend_icon(t)
        t_c = trend_color(t)
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
        kb_result = retriever.search(err, top_k=2)
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
    pdf.cell(0, 8, "五、五维技术评分", new_x="LMARGIN", new_y="NEXT")
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

    # 评分条最大宽度（mm）
    BAR_MAX_W = BW * 0.52
    LABEL_W = BW * 0.22
    SCORE_W = BW * 0.10
    DELTA_W = BW * 0.16

    row_h = 13
    for dim in DIMENSIONS:
        if pdf.y + row_h > pdf.page_break_trigger:
            pdf.add_page()
        cur_y = pdf.y

        avg = dim_avgs[dim]
        prev = hist_avgs.get(dim)
        delta = round(avg - prev, 1) if prev is not None else None

        # 背景行
        fill_c = (245, 247, 252) if True else (255, 255, 255)
        pdf.set_fill_color(*fill_c)
        pdf.rect(LM, cur_y, BW, row_h - 2, "F")

        # 左侧色条
        bar_color = TAG_C.get(int(round(avg)), C_GREY)
        pdf.set_fill_color(*bar_color)
        pdf.rect(LM, cur_y, 2, row_h - 2, "F")

        # 维度名称
        pdf.set_xy(LM + 4, cur_y + 2)
        pdf.set_font("STHeiti", size=STYLE["F_LABEL"])
        pdf.set_text_color(*C_DARK)
        pdf.cell(LABEL_W, 6, dim)

        # 分数
        pdf.set_font("STHeiti", size=STYLE["F_CHART_SCORE"])
        pdf.set_text_color(*bar_color)
        score_x = LM + LABEL_W
        pdf.set_xy(score_x, cur_y + 1)
        pdf.cell(SCORE_W, 8, f"{avg:.1f}", align="C")

        # 评分条背景
        bar_x = score_x + SCORE_W + 2
        bar_y = cur_y + 2.5
        bar_h = 7
        pdf.set_fill_color(230, 230, 230)
        pdf.rect(bar_x, bar_y, BAR_MAX_W, bar_h, "F")

        # 评分条填充
        fill_w = BAR_MAX_W * (avg / 10.0)
        if fill_w > 0:
            pdf.set_fill_color(*bar_color)
            pdf.rect(bar_x, bar_y, fill_w, bar_h, "F")

        # 分数标签在条上方
        pdf.set_font("STHeiti", size=STYLE["F_TINY"])
        pdf.set_text_color(120, 120, 120)
        pdf.set_xy(bar_x + fill_w - 8 if fill_w > 8 else bar_x + fill_w + 1, bar_y - 0.5)
        if fill_w > 8:
            pdf.set_text_color(255, 255, 255)
        pdf.cell(8, 4, f"{avg:.1f}/10")

        # 进步标签
        if delta is not None:
            delta_x = bar_x + BAR_MAX_W + 4
            sign = "+" if delta > 0 else ""
            d_color = C_GREEN if delta > 0 else (C_RED if delta < 0 else C_ORG)
            d_icon = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            pdf.set_font("STHeiti", size=STYLE["F_BODY"])
            pdf.set_text_color(*d_color)
            pdf.set_xy(delta_x, cur_y + 2)
            pdf.cell(DELTA_W, 6, f"{d_icon} {sign}{delta:.1f}分")
            pdf.set_font("STHeiti", size=STYLE["F_TINY"])
            pdf.set_text_color(140, 140, 140)
            pdf.set_xy(delta_x, cur_y + 8)
            pdf.cell(DELTA_W, 4, f"上次{prev:.1f}分")
        elif prev is None and progress.get("enough_data"):
            pdf.set_font("STHeiti", size=STYLE["F_MINI"])
            pdf.set_text_color(180, 180, 180)
            pdf.set_xy(bar_x + BAR_MAX_W + 4, cur_y + 4)
            pdf.cell(DELTA_W, 5, "首次分析")

        pdf.y = cur_y + row_h - 2
    pdf.ln(3)

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
        new_errs = progress.get("new_errors", [])

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
        import numpy as np
        from PIL import Image as PILImage  # ← 加这行

        plt.rcParams["font.family"] = ["STHeiti", "Heiti SC", "Arial Unicode MS"]
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

        earned = [b for b in all_badges if b["earned"]]
        cols = 4
        cell_w = BW / cols
        row_h = 16
        for idx, b in enumerate(all_badges):
            col = idx % cols
            row = idx // cols
            bx = LM + col * cell_w
            by = pdf.y + row * row_h
            if by + row_h > pdf.page_break_trigger:
                pdf.add_page()
                by = pdf.y
                pdf.y += row * row_h

            fc = (240, 248, 255) if b["earned"] else (245, 245, 245)
            pdf.set_fill_color(*fc)
            pdf.rect(bx + 1, by, cell_w - 2, row_h - 2, "FD")

            pdf.set_xy(bx + 1, by + 1)
            pdf.set_font("STHeiti", size=STYLE["F_SECTION"])
            tc = C_GOLD if b["earned"] else (180, 180, 180)
            pdf.set_text_color(*tc)
            pdf.cell(cell_w - 2, 8, b["icon"], align="C")

            pdf.set_xy(bx + 1, by + 8)
            pdf.set_font("STHeiti", size=STYLE["F_TINY"])
            pdf.set_text_color(C_DARK if b["earned"] else (160, 160, 160))
            pdf.cell(cell_w - 2, 4, b["name"], align="C")

            pdf.set_xy(bx + 1, by + 12)
            pdf.set_font("STHeiti", size=STYLE["F_TINY"])
            pdf.set_text_color(*C_LIGHT)
            pdf.multi_cell(cell_w - 2, 3.5, b["desc"], align="C")

        pdf.y += (len(all_badges) // cols + 1) * row_h + 4

    pdf.output(output_path)
    sz = os.path.getsize(output_path)
    print(f"报告生成: {output_path} ({sz//1024}KB)")
    return output_path


if __name__ == "__main__":
    print("报告生成模块加载正常")

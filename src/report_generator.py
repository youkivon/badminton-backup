# -*- coding: utf-8 -*-
"""
羽毛球视频分析小程序 - PDF 报告生成模块
基于 fpdf2，支持球员历史进步对比
"""
import os, sys, json, datetime, re
from collections import Counter

# 字体路径（清理 feat/morx/hdmx/bsln/meta 表，避免 fpdf2 subset warn）
FONT_DIR = "/tmp/fonts"
FONT_TTF = f"{FONT_DIR}/stHeiti.ttf"
FONT_CLEAN = f"{FONT_DIR}/stHeiti_clean.ttf"
os.makedirs(FONT_DIR, exist_ok=True)

def _build_font():
    """首次运行时从系统 TTC 提取 TTF，清理 fpdf2 不懂的表"""
    import fontTools.ttLib
    ttc = fontTools.ttLib.TTFont("/System/Library/Fonts/STHeiti Light.ttc", fontNumber=0)
    ttc.save(FONT_TTF)
    for tag in ["feat", "morx", "hdmx", "bsln", "meta"]:
        if tag in ttc.keys():
            del ttc[tag]
    ttc.save(FONT_CLEAN)
    sz = os.path.getsize(FONT_TTF) // 1024
    print(f"字体提取: {sz}KB -> 清理后 {os.path.getsize(FONT_CLEAN)//1024}KB")

if not os.path.exists(FONT_CLEAN):
    _build_font()

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
        self.set_font("STHeiti", size=8)
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, f"- {self.page_no()} -", align="C")


def clean_err(text, max_len=50):
    text = text.strip()
    text = re.sub(r"^[）\)\u3001、\s]+", "", text)
    text = re.sub(r"^[\d\u2460-\u2473]+[\.\、\s]+", "", text)
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text


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
        return text

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
    pdf.add_font("STHeiti", "", FONT_CLEAN)
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
    pdf.set_font("STHeiti", size=20)
    pdf.set_text_color(*C_DARK)
    pdf.set_x(LM + 8)
    title = "羽毛球技术动作分析报告"
    if player_name:
        title = f"{player_name} · 技术分析报告"
    pdf.cell(BW - 8, 13, title, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("STHeiti", size=9)
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
        pdf.set_font("STHeiti", size=10)
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
    pdf.set_font("STHeiti", size=13)
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
    pdf.set_font("STHeiti", size=9)
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
            pdf.set_font("STHeiti", size=9)
            pdf.cell(cw, row_h, val, border=0, fill=False, align="C")
        pdf.y += row_h
    pdf.ln(5)

    # ─── Section 2: 整体评价 ───
    pdf.set_fill_color(*C_ORG)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=13)
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "二、整体技术评价", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    ratings = [s.get("quality_rating", 3) for s in shots]
    avg_q = sum(ratings) / len(ratings) if ratings else 0
    pdf.set_font("STHeiti", size=10)
    pdf.set_text_color(*C_GREY)
    pdf.multi_cell(BW, 6, f"本次分析共 {len(shots)} 个有效动作帧，整体技术评分：{avg_q:.1f}/10（{qtext(int(round(avg_q)))}）。")
    pdf.ln(2)
    pdf.set_font("STHeiti", size=10)
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
    pdf.set_font("STHeiti", size=9)
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
        pdf.set_font("STHeiti", size=9)
        pdf.set_text_color(*C_GREY)
        pdf.multi_cell(ew[0], 4.5, err, border=0)

        pdf.set_xy(ex[1], cur_y)
        pdf.set_font("STHeiti", size=9)
        pdf.set_text_color(*C_RED)
        pdf.cell(ew[1], row_h, f"{cnt}次", border=0, fill=False, align="C")

        pdf.y = cur_y + row_h
    pdf.ln(5)

    # ─── Section 3: 详细动作分析 ───
    pdf.set_fill_color(*C_BLUE)
    pdf.rect(LM, pdf.y - 1, 3, 10, "F")
    pdf.set_font("STHeiti", size=13)
    pdf.set_text_color(*C_MID)
    pdf.set_x(LM + 6)
    pdf.cell(0, 8, "三、详细技术分析", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    stars_map = {0:"☆☆☆☆☆☆☆☆☆☆", 1:"★☆☆☆☆☆☆☆☆☆", 2:"★★☆☆☆☆☆☆☆☆", 3:"★★★☆☆☆☆☆☆☆", 4:"★★★★☆☆☆☆☆☆", 5:"★★★★★☆☆☆☆☆", 6:"★★★★★★☆☆☆☆", 7:"★★★★★★★☆☆☆", 8:"★★★★★★★★☆☆", 9:"★★★★★★★★★☆", 10:"★★★★★★★★★★"}

    IMG_W_MM = 65
    IMG_H_MM = 36
    from PIL import Image as PILImage

    for i, shot in enumerate(shots):
        q = shot.get("quality_rating", 3)
        ql = qlabel(q)
        tc = TAG_C.get(int(round(q)), C_LIGHT)

        action_type = shot.get("action_type", "")

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
        pdf.set_font("STHeiti", size=10)
        pdf.set_text_color(*C_DARK)
        pdf.set_x(LM + 4)
        pdf.cell(pdf.w - LM - pdf.r_margin - 4, 7, title, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_fill_color(*tc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("STHeiti", size=9)
        pdf.set_x(LM + 4)
        pdf.cell(pdf.w - LM - pdf.r_margin - 4, 6, f"  {ql}  {q}/10",
                 border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        body_y = pdf.y
        # shots 数据源有两个版本：frames_results 用 frame_file，analyze_shots 用 frames[0]
        _frames = shot.get("frames", [])
        frame_file = shot.get("frame_file", _frames[0] if _frames else "")
        frames_dir = data.get("frames_dir", "/tmp/bad_shots/target_frames")
        img_path = f"{frames_dir}/{frame_file}"
        txt_x = LM + IMG_W_MM + 5
        txt_w = pdf.w - LM - pdf.r_margin - IMG_W_MM - 5

        # 图片（带球员标注）- 必须是文件而非目录
        if frame_file and os.path.isfile(img_path):
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
                    # 转换 hex 字符串为 RGBA tuple
                    def hex_to_rgba(h, alpha=180):
                        h = h.lstrip('#')
                        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)
                    ann_rgba = hex_to_rgba(ann_color, 180)
                    ann_rgba_str = hex_to_rgba(ann_color, 120)
                    # 远端球员画面位置偏上/偏小，近端偏下/偏大
                    if pos == "远端":
                        box_x0, box_y0 = int(iw*0.3), int(ih*0.15)
                        box_x1, box_y1 = int(iw*0.7), int(ih*0.55)
                    else:
                        box_x0, box_y0 = int(iw*0.2), int(ih*0.45)
                        box_x1, box_y1 = int(iw*0.8), int(ih*0.95)
                    # 半透明背景框
                    overlay = PILImage.new("RGBA", im.size, (0,0,0,0))
                    od = ImageDraw.Draw(overlay)
                    for edge_w in range(3):
                        od.rectangle([box_x0-edge_w, box_y0-edge_w,
                                     box_x1+edge_w, box_y1+edge_w],
                                    outline=ann_color, width=3)
                    im = PILImage.alpha_composite(im.convert("RGBA"), overlay)
                    # 标签背景
                    label_bg = PILImage.new("RGBA", im.size, (0,0,0,0))
                    ld = ImageDraw.Draw(label_bg)
                    lw, lh = 8, 8
                    for dx in range(lw):
                        for dy in range(lh):
                            ld.rectangle([box_x0+dx, box_y0-lh-2+dy,
                                         box_x0+lw+dx, box_y0-2+dy],
                                        fill=ann_rgba)
                    im = PILImage.alpha_composite(im, label_bg)
                    # 保存临时文件
                    tmp_path = f"{frames_dir}/ann_{frame_file}"
                    im.convert("RGB").save(tmp_path, "JPEG", quality=85)
                    img_path_ann = tmp_path
                else:
                    img_path_ann = img_path

                iw2, ih2 = im.size, im.size
                ratio = ih / iw
                draw_h = IMG_W_MM * ratio
                if draw_h > IMG_H_MM:
                    draw_h = IMG_H_MM
                pdf.image(img_path_ann, x=LM, y=body_y, w=IMG_W_MM, h=draw_h)
            except Exception as e:
                print(f"  [!] 标注失败: {e}")
                pdf.rect(LM, body_y, IMG_W_MM, IMG_H_MM, "D")
        else:
            pdf.rect(LM, body_y, IMG_W_MM, IMG_H_MM, "D")

        # 文字
        pdf.set_xy(txt_x, body_y)
        pdf.set_font("STHeiti", size=8.5)
        end_y = body_y

        # 过滤：未触球/分析失败状态，不应有击球类错误
        findings  = shot.get("key_findings", [])
        errors    = shot.get("errors", [])
        suggestions = shot.get("suggestions", [])
        if action_type in ("准备发球", "死球", "捡球", "无效帧", "分析失败"):
            hit_kw = ("击球", "闪腕", "球速", "发力", "挥拍", "击球点", "击球瞬间")
            errors     = [e for e in errors     if not any(k in e for k in hit_kw)]
            suggestions = [s for s in suggestions if not any(k in s for k in hit_kw)]
            findings   = [f for f in findings   if not any(k in f for k in hit_kw)]

        if findings:
            pdf.set_xy(txt_x, end_y)
            pdf.set_text_color(40, 40, 40)
            pdf.cell(txt_w, 5, "技术诊断：")
            end_y = pdf.y + 5
            for f in findings[:2]:
                pdf.set_x(txt_x)
                pdf.set_text_color(*C_GREY)
                pdf.multi_cell(txt_w, 4.5, f"• {clean_err(f, 120)}")
            end_y = pdf.y + 1

        if errors:
            pdf.set_x(txt_x)
            pdf.ln(1)
            pdf.set_text_color(180, 40, 40)
            pdf.cell(txt_w, 5, "常见错误：")
            end_y = pdf.y + 5
            for e in errors[:2]:
                pdf.set_x(txt_x)
                pdf.set_text_color(*C_GREY)
                pdf.multi_cell(txt_w, 4.5, f"x {clean_err(e, 100)}")
            end_y = pdf.y + 1

        if suggestions:
            pdf.set_x(txt_x)
            pdf.ln(1)
            pdf.set_text_color(30, 120, 80)
            pdf.cell(txt_w, 5, "改进建议：")
            end_y = pdf.y + 5
            for s in suggestions[:2]:
                pdf.set_x(txt_x)
                pdf.set_text_color(*C_GREY)
                pdf.multi_cell(txt_w, 4.5, f"→ {clean_err(s, 300)}")
            end_y = pdf.y

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
    pdf.set_font("STHeiti", size=13)
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

    pdf.set_font("STHeiti", size=10)
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
        pdf.set_font("STHeiti", size=9.5)
        pdf.set_text_color(*C_RED)
        pdf.cell(BW - 10, 5, f"问题：{err}（{cnt}次）")
        pdf.ln(5)
        pdf.set_x(LM + 5)
        pdf.set_font("STHeiti", size=9)
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
                pdf.set_font("STHeiti", size=8)
                pdf.set_text_color(*C_BLUE)
                pdf.cell(BW - 10, 5, f"▶ {kb_video_title}")
                pdf.ln(4)
                # 视频链接（斜体灰色显示，节省空间）
                if kb_video_url:
                    vid_short = kb_video_url.replace('https://www.bilibili.com/video/', '▶  bilibili.com/')
                    pdf.set_x(LM + 5)
                    pdf.set_font("STHeiti", size=7.5)
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
    pdf.set_font("STHeiti", size=13)
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
        pdf.set_font("STHeiti", size=10)
        pdf.set_text_color(*C_DARK)
        pdf.cell(LABEL_W, 6, dim)

        # 分数
        pdf.set_font("STHeiti", size=11)
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
        pdf.set_font("STHeiti", size=7.5)
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
            pdf.set_font("STHeiti", size=9)
            pdf.set_text_color(*d_color)
            pdf.set_xy(delta_x, cur_y + 2)
            pdf.cell(DELTA_W, 6, f"{d_icon} {sign}{delta:.1f}分")
            pdf.set_font("STHeiti", size=7.5)
            pdf.set_text_color(140, 140, 140)
            pdf.set_xy(delta_x, cur_y + 8)
            pdf.cell(DELTA_W, 4, f"上次{prev:.1f}分")
        elif prev is None and progress.get("enough_data"):
            pdf.set_font("STHeiti", size=8)
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
        pdf.set_font("STHeiti", size=13)
        pdf.set_text_color(*C_MID)
        pdf.set_x(LM + 6)
        pdf.cell(0, 8, "六、进步跟踪", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        delta = progress["delta"]
        sign = "+" if delta > 0 else ""
        trend = progress.get("quality_trend", {})
        t_str = "上升" if delta > 0 else ("下降" if delta < 0 else "持平")

        pdf.set_font("STHeiti", size=10)
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
            pdf.set_font("STHeiti", size=9)
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
            pdf.set_font("STHeiti", size=9)
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
        pdf.set_font("STHeiti", size=13)
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
        pdf.set_font("STHeiti", size=13)
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
            pdf.set_font("STHeiti", size=14)
            tc = C_GOLD if b["earned"] else (180, 180, 180)
            pdf.set_text_color(*tc)
            pdf.cell(cell_w - 2, 8, b["icon"], align="C")

            pdf.set_xy(bx + 1, by + 8)
            pdf.set_font("STHeiti", size=7.5)
            pdf.set_text_color(C_DARK if b["earned"] else (160, 160, 160))
            pdf.cell(cell_w - 2, 4, b["name"], align="C")

            pdf.set_xy(bx + 1, by + 12)
            pdf.set_font("STHeiti", size=6.5)
            pdf.set_text_color(*C_LIGHT)
            pdf.multi_cell(cell_w - 2, 3.5, b["desc"], align="C")

        pdf.y += (len(all_badges) // cols + 1) * row_h + 4

    pdf.output(output_path)
    sz = os.path.getsize(output_path)
    print(f"报告生成: {output_path} ({sz//1024}KB)")
    return output_path


if __name__ == "__main__":
    print("报告生成模块加载正常")

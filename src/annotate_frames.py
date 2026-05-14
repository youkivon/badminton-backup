# -*- coding: utf-8 -*-
"""
轻量帧图标注：给帧图叠加动作类型标签 + 质量分
不画场地线，只加角标（报告能用就行）

用法（独立运行）:
  python annotate_frames.py <history.json路径> <archive_dir路径>
  python annotate_frames.py /path/to/history.json /path/to/archive --output_dir /path/to/output

用法（被 run_analysis.py 调用）:
  from annotate_frames import annotate_session_frames
  annotate_session_frames(history_data, arc_dir, output_dir=None)
"""
import os
import json
import sys
import argparse
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"


def annotate_frame(src_path, dst_path, label, score):
    """在帧图右下角叠加动作标签"""
    img = Image.open(src_path).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img)

    font_size = max(14, int(H * 0.035))
    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception:
        font = ImageFont.load_default()

    tag = f"{label}  {score}/10"
    bbox = draw.textbbox((0, 0), tag, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 6
    rx = W - tw - pad * 2 - 10
    ry = H - th - pad * 2 - 10

    # 颜色：按评分
    if score >= 8:
        bg = (0, 90, 180)   # 蓝-优秀
    elif score >= 6:
        bg = (39, 174, 96)  # 绿-良好
    elif score >= 4:
        bg = (239, 108, 0)  # 橙-一般
    else:
        bg = (198, 40, 40)  # 红-差

    draw.rectangle([rx, ry, rx + tw + pad * 2, ry + th + pad * 2], fill=bg)
    draw.text((rx + pad, ry + pad), tag, font=font, fill=(255, 255, 255))

    img.save(dst_path, "JPEG", quality=88)
    return True


def annotate_session_frames(history_data: dict, arc_dir: str, output_dir: str = None):
    """
    主入口（供 run_analysis.py 调用）。
    history_data: 解析后的 history JSON（dict）
    arc_dir: 帧图归档目录（players/{name}/frame_archive/{date}）
    output_dir: 标注图输出目录（默认与 arc_dir 相同，用 ann_ 前缀区分）
    """
    if output_dir is None:
        output_dir = arc_dir

    shots_frames = {}  # frame_file -> (action_type, score)
    for shot in history_data.get("shots", []):
        for fn in shot.get("frames", []):
            shots_frames[fn] = (
                shot.get("action_type", "未知"),
                shot.get("quality_rating", "?"),
            )

    print(f"待标注帧: {len(shots_frames)} 张")
    print(f"  归档目录: {arc_dir}")
    print(f"  输出目录: {output_dir}")

    annotated = 0
    skipped = 0
    for fn, (label, score) in shots_frames.items():
        src = os.path.join(arc_dir, fn)
        dst = os.path.join(output_dir, f"ann_{fn}")
        if os.path.exists(src):
            try:
                annotate_frame(src, dst, label, score)
                print(f"  ✓ {fn} -> ann_{fn}")
                annotated += 1
            except Exception as e:
                print(f"  ✗ 标注失败 {fn}: {e}")
                skipped += 1
        else:
            print(f"  ✗ 找不到: {src}")
            skipped += 1

    print(f"\n完成: {annotated}/{len(shots_frames)} 张已标注，{skipped} 张跳过")
    return annotated


# ── CLI 入口 ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="羽毛球帧图标注工具")
    parser.add_argument("history", help="history.json 路径")
    parser.add_argument("archive", help="frame_archive 目录路径")
    parser.add_argument("--output_dir", "-o", default=None,
                        help="标注图输出目录（默认同 archive）")
    args = parser.parse_args()

    if not os.path.exists(args.history):
        print(f"[错误] history.json 不存在: {args.history}")
        sys.exit(1)
    if not os.path.exists(args.archive):
        print(f"[错误] archive 目录不存在: {args.archive}")
        sys.exit(1)

    with open(args.history, encoding="utf-8") as f:
        history_data = json.load(f)

    annotate_session_frames(history_data, args.archive, args.output_dir)


if __name__ == "__main__":
    main()

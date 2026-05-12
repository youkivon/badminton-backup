# -*- coding: utf-8 -*-
"""
轻量帧图标注：给帧图叠加动作类型标签 + 质量分
不画场地线，只加角标（报告能用就行）
"""
import os, json, sys
from PIL import Image, ImageDraw, ImageFont

ARCHIVE = "/Users/youqifang/Desktop/小程序/players/游琪方/frame_archive/2026-05-11"
HISTORY = "/Users/youqifang/Desktop/小程序/players/游琪方/history/2026-05-11.json"
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"

def annotate_frame(src_path, dst_path, label, score):
    """在帧图右下角叠加动作标签"""
    img = Image.open(src_path).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img)

    font_size = max(14, int(H * 0.035))
    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except:
        font = ImageFont.load_default()

    # 背景框
    tag = f"{label}  {score}/10"
    bbox = draw.textbbox((0, 0), tag, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 6
    rx = W - tw - pad * 2 - 10
    ry = H - th - pad * 2 - 10
    draw.rectangle([rx, ry, rx + tw + pad * 2, ry + th + pad * 2],
                   fill=(39, 174, 96))  # 绿色背景
    draw.text((rx + pad, ry + pad), tag, font=font, fill=(255, 255, 255))

    # 左上角常见错误角标（如果有错误）
    img.save(dst_path, "JPEG", quality=88)
    return True

def main():
    with open(HISTORY) as f:
        data = json.load(f)

    shots_frames = {}  # frame_file -> (action_type, score)
    for shot in data.get("shots", []):
        for fn in shot.get("frames", []):
            shots_frames[fn] = (shot.get("action_type", "未知"), shot.get("quality_rating", "?"))

    print(f"待标注帧: {len(shots_frames)} 张")
    annotated = 0
    for fn, (label, score) in shots_frames.items():
        src = os.path.join(ARCHIVE, fn)
        dst = os.path.join(ARCHIVE, f"ann_{fn}")
        if os.path.exists(src):
            annotate_frame(src, dst, label, score)
            annotated += 1
            print(f"  ✓ {fn} -> ann_{fn}")
        else:
            print(f"  ✗ 找不到: {src}")

    print(f"\n完成: {annotated}/{len(shots_frames)} 张已标注")

if __name__ == "__main__":
    main()

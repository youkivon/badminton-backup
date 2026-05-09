# -*- coding: utf-8 -*-
"""
羽毛球位置检测模块
用 OpenCV HSV 颜色检测标注场上羽毛球位置
结合场地坐标系判断击球场景
"""
import cv2
import numpy as np
# court_position imported lazily only when needed
def _lazy_import():
    global get_near_far_side, get_zone
    from court_position import get_near_far_side, get_zone

# 羽毛球的典型HSV范围（白色球头 + 橙色球裙）
LOWER_WHITE = np.array([0, 0, 180])
UPPER_WHITE = np.array([180, 50, 255])
LOWER_ORANGE = np.array([0, 80, 100])
UPPER_ORANGE = np.array([30, 255, 255])
LOWER_YELLOW = np.array([20, 60, 150])  # 浅黄/米白
UPPER_YELLOW = np.array([40, 120, 220])


def detect_shuttlecock(img_or_path, court_corners=None):
    """
    检测羽毛球的中心位置
    
    Args:
        img_or_path: numpy array (BGR) 或 文件路径
        court_corners: 可选，球场四角的透视变换信息
                      (top_left, top_right, bottom_left, bottom_right) 像素坐标
                      用于判断球在哪个半场
    
    Returns:
        dict: {
            "found": bool,
            "cx": int, "cy": int,        # 球心像素坐标
            "radius": int,               # 检测到的半径
            "confidence": float,         # 置信度 0-1
            "court_side": str,           # "near" / "far" / "unknown"（根据court_corners判断）
            "court_zone": str,           # "front" / "middle" / "back"（根据court_corners判断）
            "frame_annotated": numpy array,  # 标注了球位置的帧图（BGR）
        }
    """
    if isinstance(img_or_path, str):
        img = cv2.imread(img_or_path)
        if img is None:
            return _empty_result()
    else:
        img = img_or_path.copy()

    h, w = img.shape[:2]
    img_display = img.copy()

    # 缩小加速
    scale = 320 / w if w > 640 else 1.0
    if scale < 1:
        img_small = cv2.resize(img, (int(w * scale), int(h * scale)))
    else:
        img_small = img

    hsv = cv2.cvtColor(img_small, cv2.COLOR_BGR2HSV)

    # ── 多种颜色通道联合检测 ──────────────────────
    masks = []
    names = []

    # 白/灰白色（球头+球裙亮部）
    m_white = cv2.inRange(hsv, LOWER_WHITE, UPPER_WHITE)
    masks.append(m_white)
    names.append("white")

    # 橙色（球裙）
    m_orange = cv2.inRange(hsv, LOWER_ORANGE, UPPER_ORANGE)
    masks.append(m_orange)
    names.append("orange")

    # 浅黄白（亮部羽毛）
    m_yellow = cv2.inRange(hsv, LOWER_YELLOW, UPPER_YELLOW)
    masks.append(m_yellow)
    names.append("yellow")

    best_cx, best_cy, best_radius, best_score = None, None, None, 0

    for mi, (mask, name) in enumerate(zip(masks, names)):
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < 30 or area > 4000:
                continue

            # 椭圆/圆拟合
            if len(c) >= 5:
                try:
                    ellipse = cv2.fitEllipse(c)
                    (cx_e, cy_e), (ma, MA), angle = ellipse
                    cx_e /= scale
                    cy_e /= scale
                    radius = max(ma, MA) / 2 / scale
                except:
                    continue
            else:
                continue

            # 形状检测：轮廓复杂度（羽毛球接近圆形但有毛状边缘）
            perimeter = cv2.arcLength(c, True)
            if perimeter < 1:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)

            # 面积+圆度综合评分
            # 羽毛球在画面中通常 10-80 像素半径
            size_score = 1.0 if 5 < radius < 100 else max(0, 1 - abs(radius - 40) / 40)
            score = circularity * 0.5 + size_score * 0.5

            if score > best_score:
                best_score = score
                best_cx = int(cx_e)
                best_cy = int(cy_e)
                best_radius = int(radius)

    found = best_score > 0.3 and best_cx is not None

    # ── court_side / court_zone 判断 ─────────────
    court_side = "unknown"
    court_zone = "unknown"

    if found and court_corners is not None:
        try:
            corners = court_corners  # (tl, tr, bl, br) 四个角的像素坐标
            if len(corners) == 4:
                # 用透视变换判断球在近端还是远端
                # 计算球相对于球网（上下边线中点连线）的位置
                cx, cy = best_cx, best_cy
                # 网中心 y 坐标约为 (br_y + tr_y) / 2
                net_y = (corners[2][1] + corners[3][1] + corners[0][1] + corners[1][1]) / 4
                court_side = "near" if cy < net_y else "far"

                # 场地高度方向（前中后场）
                # 总高度：br_y - tr_y（或bl_y - tl_y）
                court_h = abs(corners[2][1] - corners[0][1])
                rel_y = (cy - min(corners[0][1], corners[1][1])) / court_h if court_h > 0 else 0.5
                if rel_y < 0.33:
                    court_zone = "front"
                elif rel_y < 0.67:
                    court_zone = "middle"
                else:
                    court_zone = "back"
        except:
            pass

    # ── 标注球位置 ─────────────────────────────
    if found:
        # 放大半径（因为缩小了图像）
        r_ann = max(best_radius + 3, 6)

        # 外圈：橙色
        cv2.circle(img_display, (best_cx, best_cy), r_ann + 3, (0, 140, 255), 2)
        # 中心点：白色
        cv2.circle(img_display, (best_cx, best_cy), 2, (255, 255, 255), -1)

        # 标签
        label = "🏸 %s/%s" % (
            court_side if court_side != "unknown" else "?",
            court_zone if court_zone != "unknown" else "?"
        )
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(img_display, label, (best_cx + r_ann + 5, best_cy - 5),
                    font, 0.55, (0, 255, 255), 1, cv2.LINE_AA)

        # 标注球位置到图角（方便确认）
        # 左上角文字
        info = "Ball: (%d,%d) r=%d conf=%.2f" % (best_cx, best_cy, best_radius, best_score)
        cv2.putText(img_display, info, (8, 20), font, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    else:
        cv2.putText(img_display, "Ball: NOT DETECTED", (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)

    return {
        "found": found,
        "cx": best_cx,
        "cy": best_cy,
        "radius": best_radius,
        "confidence": best_score,
        "court_side": court_side,
        "court_zone": court_zone,
        "frame_annotated": img_display,
    }


def _empty_result():
    return {
        "found": False, "cx": None, "cy": None, "radius": None,
        "confidence": 0.0, "court_side": "unknown", "court_zone": "unknown",
        "frame_annotated": None,
    }


def annotate_frame_with_ball(frame_path, court_corners=None, output_path=None):
    """
    读取帧图，标注羽毛球位置，保存并返回标注后的图像路径
    """
    result = detect_shuttlecock(frame_path, court_corners=court_corners)
    if result["frame_annotated"] is not None:
        if output_path is None:
            import os, hashlib
            dir_name = os.path.dirname(frame_path)
            base = os.path.splitext(os.path.basename(frame_path))[0]
            output_path = os.path.join(dir_name, base + "_ball.jpg")

        cv2.imwrite(output_path, result["frame_annotated"])
        return output_path, result
    return None, result

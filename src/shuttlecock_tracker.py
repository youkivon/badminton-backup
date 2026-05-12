# -*- coding: utf-8 -*-
"""
羽毛球球速追踪模块
通过高帧率片段追踪球的像素轨迹，用羽毛球双打场地宽6.1米做比例尺计算球速。

核心原理：
- 比例尺：球网柱间距(像素) / 610cm = pixels_per_cm
- 速度：像素位移 / pixels_per_cm / 时间差(秒) * 3.6 = km/h
"""
import cv2
import numpy as np
import os, subprocess, re, math
from shuttlecock_detector import detect_shuttlecock


# 羽毛球双打场地宽 6.1 米（两根球网柱之间）
COURT_DOUBLES_WIDTH_CM = 610.0


def extract_clip(video_path, center_sec, duration_sec=4, fps=15,
                 output_path=None):
    """
    从视频中提取以 center_sec 为中心的高帧率片段。

    Args:
        video_path: 原始视频路径
        center_sec: 片段中心时间（秒）
        duration_sec: 片段总时长（秒，默认4秒）
        fps: 输出帧率（默认15fps，兼顾精度和文件大小）
        output_path: 保存路径，默认在 /tmp 下生成

    Returns:
        输出视频路径，或 None（提取失败）
    """
    if output_path is None:
        output_path = f"/tmp/bad_shots/clip_{int(center_sec*100)}s_{fps}fps.mp4"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 校验视频实际时长，超出范围直接跳过
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration", "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=10
        )
        total_dur = float(probe.stdout.strip())
    except Exception:
        total_dur = None

    if total_dur is not None and center_sec > total_dur - 0.5:
        # 时刻超出视频范围，不提取
        return None

    start_sec = max(0, center_sec - duration_sec / 2)
    # 限制不超过视频结尾
    if total_dur is not None:
        start_sec = min(start_sec, max(0, total_dur - duration_sec))
    actual_dur = min(duration_sec, total_dur - start_sec) if total_dur else duration_sec
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", video_path,
        "-t", str(actual_dur),
        "-vf", f"fps={fps}",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-an",   # 无音频
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(output_path):
        print(f"  [!] clip提取失败: {r.stderr[-200:]}")
        return None
    return output_path


def _get_clip_frames(clip_path):
    """读取 clip 所有帧（numpy array list）"""
    cap = cv2.VideoCapture(clip_path)
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    return frames


def _detect_ball_in_frame(frame):
    """
    在单帧中检测羽毛球位置。
    复用了 shuttlecock_detector 的 HSV 逻辑，但输出 (cx, cy) 或 None。
    """
    h, w = frame.shape[:2]
    scale = 320 / w if w > 640 else 1.0
    if scale < 1:
        frame_small = cv2.resize(frame, (int(w * scale), int(h * scale)))
    else:
        frame_small = frame

    hsv = cv2.cvtColor(frame_small, cv2.COLOR_BGR2HSV)

    # HSV 范围（同 shuttlecock_detector）
    lower_white  = np.array([0, 0, 140])
    upper_white  = np.array([180, 80, 255])
    lower_orange = np.array([0, 50, 80])
    upper_orange = np.array([40, 255, 255])
    lower_yellow = np.array([15, 30, 120])
    upper_yellow = np.array([45, 100, 255])

    m_white  = cv2.inRange(hsv, lower_white, upper_white)
    m_orange = cv2.inRange(hsv, lower_orange, upper_orange)
    m_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)
    combined = cv2.max(m_white, cv2.max(m_orange, m_yellow))

    kernel = np.ones((5, 5), np.uint8)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)

    cnts, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_score = 0
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 20 or area > 8000:
            continue
        if len(c) < 5:
            continue
        try:
            ellipse = cv2.fitEllipse(c)
            (cx_e, cy_e), (ma, MA), _ = ellipse
            cx_e /= scale
            cy_e /= scale
            cy_e = h - cy_e   # 转为画面坐标系（y轴向下）
            radius = max(ma, MA) / 2 / scale
        except:
            continue

        perimeter = cv2.arcLength(c, True)
        if perimeter < 1:
            continue
        circularity = 4 * np.pi * area / (perimeter * perimeter)
        size_score = 1.0 if 5 < radius < 100 else max(0, 1 - abs(radius - 40) / 40)
        score = circularity * 0.3 + size_score * 0.7

        if score > best_score:
            best_score = score
            best = (int(cx_e), int(cy_e), radius)

    if best_score > 0.3 and best is not None:
        return best   # (cx, cy, radius)
    return None


def _calibrate_pixels_per_cm(clip_path):
    """
    用球网柱自动校准比例尺（pixels_per_cm）。

    策略：用 shuttlecock_detector 对 clip 首帧检测，
    找两个最大的圆（球网柱），计算它们之间的像素距离。
    球网柱特征：白色/银色竖直长条，在画面上半部分。

    Returns:
        pixels_per_cm: float 或 None（校准失败）
    """
    cap = cv2.VideoCapture(clip_path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None

    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 找圆形（球网柱是竖直圆柱，在画面中近似椭圆）
    # 使用霍夫圆变换（近似圆）
    # 缩小加速
    scale = 640 / w if w > 640 else 1.0
    if scale < 1:
        frame_s = cv2.resize(frame, (int(w * scale), int(h * scale)))
        scale_back = 1.0 / scale
    else:
        frame_s = frame
        scale_back = 1.0

    gray_s = cv2.cvtColor(frame_s, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray_s, (5, 5), 0)
    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.5, minDist=50,
        param1=50, param2=15, minRadius=8, maxRadius=40
    )

    if circles is None:
        return None

    circles = circles[0]
    # 取画面上半部分（y < h*0.6）的圆，且近似竖直方向（短轴/长轴 > 0.6）
    candidates = []
    for cx, cy, r in circles:
        cy_actual = cy * scale_back
        if cy_actual < h * 0.65:   # 球网柱在画面上半部分
            candidates.append((cx * scale_back, cy_actual, r * scale_back))

    if len(candidates) < 2:
        return None

    # 取 y 坐标最接近的两个圆（球网柱左右柱）
    candidates.sort(key=lambda p: p[1])
    # 如果第一和第二个 y 差太大，说明不是球网柱
    y0, y1 = candidates[0][1], candidates[1][1]
    if abs(y1 - y0) > h * 0.15:
        return None

    # 取画面中 x 距离最大的那对
    if len(candidates) == 2:
        (x0, _, _), (x1, _, _) = candidates
    else:
        # 找 x 距离最大的两个
        best_pair = None
        best_dist = 0
        for i in range(len(candidates)):
            for j in range(i+1, len(candidates)):
                d = abs(candidates[i][0] - candidates[j][0])
                if d > best_dist:
                    best_dist = d
                    best_pair = (candidates[i], candidates[j])
        if best_pair is None:
            return None
        (x0, _, _), (x1, _, _) = best_pair

    pixel_distance = abs(x1 - x0)
    if pixel_distance < 50:
        return None

    pixels_per_cm = pixel_distance / COURT_DOUBLES_WIDTH_CM
    return pixels_per_cm


def track_clip(clip_path, pixels_per_cm=None, fps=15):
    """
    追踪 clip 中羽毛球的像素轨迹，返回每帧位置和计算出的球速。

    Args:
        clip_path: 高帧率片段路径
        pixels_per_cm: 比例尺（像素/厘米），如不提供则自动校准
        fps: 片段帧率（默认15，和 extract_clip 一致）

    Returns:
        dict: {
            "positions": [(frame_idx, cx, cy), ...],   # 球心像素坐标
            "frame_count": int,
            "fps": float,
            "pixels_per_cm": float,
            "speed_kmh": float or None,   # 最高球速
            "avg_speed_kmh": float or None,
            "trajectory": "straight" / "arc" / "unknown",
            "detected": bool,
            "error": str or None,
        }
    """
    if pixels_per_cm is None:
        pixels_per_cm = _calibrate_pixels_per_cm(clip_path)
        if pixels_per_cm is None:
            return {
                "positions": [], "frame_count": 0, "fps": fps,
                "pixels_per_cm": None, "speed_kmh": None,
                "avg_speed_kmh": None, "trajectory": "unknown",
                "detected": False, "error": "校准失败（未检测到球网柱）"
            }

    frames = _get_clip_frames(clip_path)
    if not frames:
        return {
            "positions": [], "frame_count": 0, "fps": fps,
            "pixels_per_cm": pixels_per_cm, "speed_kmh": None,
            "avg_speed_kmh": None, "trajectory": "unknown",
            "detected": False, "error": "无法读取帧"
        }

    positions = []   # [(frame_idx, cx, cy), ...]
    prev_cx, prev_cy = None, None
    consecutive_jumps = 0
    JUMP_TOLERANCE = 3   # 连续3次跳帧才判定为跟踪丢失（容忍偶尔的误检）
    max_jump_ratio = 0.30  # 容忍单帧最多30%画面位移

    for fi, frame in enumerate(frames):
        result = _detect_ball_in_frame(frame)
        if result is not None:
            cx, cy, radius = result
            if prev_cx is not None:
                dist = math.sqrt((cx - prev_cx)**2 + (cy - prev_cy)**2)
                max_jump = frame.shape[1] * max_jump_ratio
                if dist > max_jump:
                    consecutive_jumps += 1
                    if consecutive_jumps >= JUMP_TOLERANCE:
                        # 连续3次跳帧：跟踪丢失，重置
                        prev_cx, prev_cy = None, None
                        consecutive_jumps = 0
                    continue
                else:
                    consecutive_jumps = 0  # 还在容忍范围内
            positions.append((fi, cx, cy))
            prev_cx, prev_cy = cx, cy

    if len(positions) < 2:
        return {
            "positions": positions, "frame_count": len(frames), "fps": fps,
            "pixels_per_cm": pixels_per_cm, "speed_kmh": None,
            "avg_speed_kmh": None, "trajectory": "unknown",
            "detected": len(positions) > 0, "error": "检测到的球位置不足以计算速度"
        }

    # 计算帧间速度
    speeds = []   # [km/h, ...]
    for i in range(1, len(positions)):
        fi0, cx0, cy0 = positions[i-1]
        fi1, cx1, cy1 = positions[i]
        d_pixel = math.sqrt((cx1 - cx0)**2 + (cy1 - cy0)**2)
        d_cm = d_pixel / pixels_per_cm
        d_m = d_cm / 100.0
        dt = (fi1 - fi0) / fps   # 秒
        if dt > 0:
            mps = d_m / dt
            kmh = mps * 3.6
            speeds.append(kmh)

    # 过滤明显不合理值（羽毛球 60-500 km/h）
    valid_speeds = [s for s in speeds if 40 < s < 600]
    if not valid_speeds:
        # 如果全被过滤，降低阈值重试
        valid_speeds = [s for s in speeds if 20 < s < 700]
        if not valid_speeds:
            valid_speeds = speeds  # 不过滤

    max_speed_kmh = max(valid_speeds) if valid_speeds else None
    avg_speed_kmh = sum(valid_speeds) / len(valid_speeds) if valid_speeds else None

    # 轨迹判断：用位移的 y/x 比值判断直线/弧线
    if len(positions) >= 3:
        _, x0, y0 = positions[0]
        _, xm, ym = positions[len(positions)//2]
        _, xn, yn = positions[-1]
        # 方向向量
        dx1, dy1 = xm - x0, ym - y0
        dx2, dy2 = xn - xm, yn - ym
        # 点积判断是否同向
        dot = dx1*dx2 + dy1*dy2
        norm = math.sqrt(dx1**2+dy1**2) * math.sqrt(dx2**2+dy2**2)
        if norm > 0 and dot / norm > 0.7:
            trajectory = "straight"
        else:
            trajectory = "arc"
    else:
        trajectory = "unknown"

    return {
        "positions": positions,
        "frame_count": len(frames),
        "fps": fps,
        "pixels_per_cm": float(pixels_per_cm) if pixels_per_cm is not None else None,
        "speed_kmh": float(max_speed_kmh) if max_speed_kmh is not None else None,
        "avg_speed_kmh": float(avg_speed_kmh) if avg_speed_kmh is not None else None,
        "trajectory": trajectory,
        "detected": True,
        "error": None,
    }


def track_shot_in_video(video_path, shot_time_sec,
                        court_corners=None,
                        pixels_per_cm=None,
                        clip_fps=15):
    """
    一次性完成：从原始视频 → 提取clip → 追踪球 → 返回速度数据。

    Args:
        video_path: 原始视频路径
        shot_time_sec: 击球时间（秒），即 shot["time"] 中的秒数
        court_corners: 未使用（保留接口兼容）
        pixels_per_cm: 可选，强制指定比例尺
        clip_fps: clip帧率

    Returns:
        同 track_clip 的返回值
    """
    clip_path = extract_clip(video_path, shot_time_sec,
                             duration_sec=4, fps=clip_fps)
    if clip_path is None:
        return {
            "positions": [], "frame_count": 0, "fps": clip_fps,
            "pixels_per_cm": None, "speed_kmh": None,
            "avg_speed_kmh": None, "trajectory": "unknown",
            "detected": False, "error": "clip提取失败"
        }
    return track_clip(clip_path, pixels_per_cm=pixels_per_cm, fps=clip_fps)


def annotate_clip_with_ball_path(clip_path, output_path=None,
                                  positions=None, pixels_per_cm=None):
    """
    在 clip 每帧上标注球的轨迹，保存为带标注的视频。
    用于调试和演示。

    Args:
        clip_path: clip视频路径
        output_path: 输出视频路径
        positions: 如不提供，则重新 track
        pixels_per_cm: 比例尺

    Returns:
        输出视频路径，或 None
    """
    if positions is None:
        result = track_clip(clip_path, pixels_per_cm=pixels_per_cm)
        positions = result["positions"]
    if not positions:
        return None

    pos_dict = {fi: (cx, cy) for fi, cx, cy in positions}

    frames = _get_clip_frames(clip_path)
    if not frames:
        return None

    if output_path is None:
        d = os.path.dirname(clip_path)
        b = os.path.splitext(os.path.basename(clip_path))[0]
        output_path = os.path.join(d, b + "_annotated.mp4")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    h, w = frames[0].shape[:2]
    out = cv2.VideoWriter(output_path, fourcc, 15, (w, h))

    for fi, frame in enumerate(frames):
        if fi in pos_dict:
            cx, cy = pos_dict[fi]
            # 轨迹颜色：首帧绿色，尾帧红色，中间黄色
            if fi == min(pos_dict.keys()):
                color = (0, 255, 0)
            elif fi == max(pos_dict.keys()):
                color = (0, 0, 255)
            else:
                color = (0, 255, 255)
            cv2.circle(frame, (cx, cy), 8, color, 2)
            cv2.putText(frame, f"#{fi}", (cx+10, cy-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # 绘制到目前为止的轨迹线
        sorted_pos = sorted(pos_dict.items())
        for pi in range(len(sorted_pos)):
            if sorted_pos[pi][0] <= fi:
                _, tx, ty = sorted_pos[pi]
                cv2.circle(frame, (tx, ty), 3, (200, 200, 0), -1)
            if pi > 0 and sorted_pos[pi-1][0] <= fi and sorted_pos[pi][0] <= fi:
                _, tx0, ty0 = sorted_pos[pi-1]
                _, tx1, ty1 = sorted_pos[pi]
                cv2.line(frame, (tx0, ty0), (tx1, ty1), (200, 200, 0), 1)

        out.write(frame)

    out.release()
    return output_path

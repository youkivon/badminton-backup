"""
球场摄像机标定模块
基于 Deep-Learning-Based-Temporal-Analysis-of-Badminton-Gameplay/camera_analysis.py

功能：
1. 羽毛球球场尺寸常量
2. 摄像机视角参数计算（高度、角度、距离）
3. 透视变换矩阵计算（将图像坐标转换为实际场地坐标）
4. 像素距离 → 实际距离（cm）转换

羽毛球场标准尺寸（单打/双打通用）：
- 场地长度：1340 cm（13.4m）
- 场地宽度：610 cm（6.1m）
- 球网高度：155 cm（两侧）
- 发球线到球网：198 cm
- 网前到双打后场：438 cm
"""

import numpy as np
import cv2

# 羽毛球场地标准尺寸（cm）
COURT_LENGTH = 1340   # 场地长度
COURT_WIDTH = 610      # 场地宽度（双打宽度）
NET_Y = 670            # 球网在场地坐标系中的 Y 坐标（半场中心）

# 场地区域划分（基于 Y 坐标）
class CourtZone:
    """场地区域定义（从近到远）"""
    NET_ZONE_MAX = NET_Y + 50      # 网前区近边界（靠近球网）
    MID_ZONE_MIN = NET_ZONE_MAX    # 中场区近边界
    MID_ZONE_MAX = 1000            # 中场区远边界
    BACK_ZONE_MIN = MID_ZONE_MAX   # 后场区近边界

# 发球线位置
SERVICE_LINE_OFFSET = 198  # 从球网到发球线的距离

# 关键点索引（ResNet50 输出的 30 个关键点中提取 4 个角点）
# 0=左下, 4=左上, 25=右下, 29=右上（0-indexed）
CORNER_KEYPOINT_INDICES = {
    "top_left": 4,
    "top_right": 29,
    "bottom_left": 0,
    "bottom_right": 25,
}


def calculate_view_parameters(corner_points: np.ndarray) -> dict:
    """
    根据球场角点计算摄像机视角参数。

    Args:
        corner_points: shape (4, 2)，四角点坐标 [x, y]
                      顺序：top_left, top_right, bottom_left, bottom_right

    Returns:
        dict: {
            "height_above_ground": 摄像机高度（cm）,
            "angle_of_inclination": 摄像机倾角（度）,
            "distance_from_shorter_edge": 摄像机到近端距离（cm）,
            "scaling_factor": 像素→实际距离的缩放因子（cm/像素）
        }
    """
    top_left, top_right, bottom_left, bottom_right = corner_points

    # 上下边的平均 Y 坐标
    y_top = (top_left[1] + top_right[1]) / 2
    y_bottom = (bottom_left[1] + bottom_right[1]) / 2

    # 图像中球场高度（像素）
    h_image = y_bottom - y_top

    # 缩放因子：实际长度 / 图像像素高度
    scaling_factor = COURT_LENGTH / h_image  # cm/像素

    # 摄像机估算高度
    h_actual = scaling_factor * h_image / 2

    # 左右边中心点水平距离
    d_horizontal = np.linalg.norm(top_right[:2] - top_left[:2])

    # 摄像机倾角
    theta = np.arctan2(h_actual, d_horizontal) * (180 / np.pi)

    # 到近端估算距离
    d_shorter_edge = np.linalg.norm(top_left[:2] - bottom_left[:2]) / 2

    return {
        "height_above_ground": round(h_actual, 2),
        "angle_of_inclination": round(theta, 2),
        "distance_from_shorter_edge": round(d_shorter_edge, 2),
        "scaling_factor": round(scaling_factor, 4),
        "court_height_pixels": h_image,
    }


def get_perspective_transform_matrix(
    corner_points: np.ndarray,
    target_width: int = None,
    target_height: int = None,
) -> tuple:
    """
    计算透视变换矩阵：将图像坐标系的角点转换为标准场地坐标系（cm）。

    Args:
        corner_points: shape (4, 2)，四角点
        target_width: 目标宽度（默认 COURT_WIDTH）
        target_height: 目标高度（默认 COURT_LENGTH）

    Returns:
        (M, inv_M): 透视变换矩阵及其逆矩阵
    """
    if target_width is None:
        target_width = COURT_WIDTH
    if target_height is None:
        target_height = COURT_LENGTH

    # 源点（检测到的球场四角）
    src_points = np.array(corner_points, dtype=np.float32)

    # 目标点（标准场地矩形）
    dst_points = np.float32([
        [0, 0],               # top-left
        [target_width, 0],    # top-right
        [0, target_height],  # bottom-left
        [target_width, target_height],  # bottom-right
    ])

    # 透视变换矩阵（图像 → 场地坐标 cm）
    M = cv2.getPerspectiveTransform(src_points, dst_points)

    # 逆矩阵（场地坐标 cm → 图像像素）
    inv_M = cv2.getPerspectiveTransform(dst_points, src_points)

    return M, inv_M


def pixel_to_court(pixel_point: tuple, inv_M: np.ndarray) -> tuple:
    """
    将图像像素坐标转换为场地实际坐标（cm）。

    Args:
        pixel_point: (x, y) 像素坐标
        inv_M: 逆透视变换矩阵

    Returns:
        (x_cm, y_cm): 场地坐标系坐标
    """
    pt = np.array([[pixel_point[0], pixel_point[1], 1.0]], dtype=np.float32)
    transformed = inv_M @ pt.T
    if transformed[2] != 0:
        x = transformed[0] / transformed[2]
        y = transformed[1] / transformed[2]
    else:
        x, y = transformed[0], transformed[1]
    return (round(x, 1), round(y, 1))


def court_to_pixel(court_point: tuple, M: np.ndarray) -> tuple:
    """
    将场地实际坐标（cm）转换为图像像素坐标。

    Args:
        court_point: (x_cm, y_cm)
        M: 透视变换矩阵

    Returns:
        (x_pixel, y_pixel)
    """
    pt = np.array([[court_point[0], court_point[1], 1.0]], dtype=np.float32)
    transformed = M @ pt.T
    if transformed[2] != 0:
        x = transformed[0] / transformed[2]
        y = transformed[1] / transformed[2]
    else:
        x, y = transformed[0], transformed[1]
    return (round(x, 1), round(y, 1))


class CourtZone:
    """场地区域常量（用于类型标注）"""
    NET = "net"
    MID = "mid"
    BACK = "back"


NET_Y = 670  # 球网 Y 坐标（场地坐标系）


def get_zone(y_cm):
    """
    根据场地 Y 坐标（cm）判断球员所在区域。

    区域划分（从近到远）：
    - 网前区（net）：0 ~ 720 cm
    - 中场区（mid）：720 ~ 1000 cm
    - 后场区（back）：1000 ~ 1340 cm

    Args:
        y_cm: 球员在场地坐标系中的 Y 坐标（0=近端，1340=远端）

    Returns:
        "net" | "mid" | "back"
    """
    if y_cm <= 720:
        return "net"
    elif y_cm <= 1000:
        return "mid"
    else:
        return "back"


def get_near_far_side(y_cm):
    """
    判断球员在球网的哪一侧。

    Args:
        y_cm: Y 坐标（0=近端发球线，1340=远端双打底线）

    Returns:
        "near"（近端/发球侧）| "far"（远端/底线侧）
    """
    return "near" if y_cm < NET_Y else "far"


# ============ 简化版：无需模型的角点提取 ============

def estimate_court_corners_from_frame(
    frame,
    net_side: str = "bottom",
) -> np.ndarray | None:
    """
    从单帧图像估算球场四角（简化版，无需模型）。

    使用场地几何特征：边线是直线，通过霍夫变换检测。
    同时利用了羽毛球场地是矩形的几何约束。

    Args:
        frame: OpenCV BGR 帧
        net_side: 球网在画面中的位置，"bottom"=底部，"top"=顶部

    Returns:
        corner_points: shape (4, 2)，四角点，或 None
    """
    # 预留接口：后续可以用 Vision SDK 标注球场四角
    # 当前返回 None，由调用方通过手动标注或 VLM 提供
    return None


def manual_court_corners(
    corners: list,
    court_width: int = COURT_WIDTH,
    court_length: int = COURT_LENGTH,
) -> np.ndarray:
    """
    根据手动标注的 4 个角点构建透视变换所需的标准角点。

    Args:
        corners: 4 个角点的像素坐标 [[x,y], ...]，顺序不限
        court_width: 场地宽度（默认 610 cm）
        court_length: 场地长度（默认 1340 cm）

    Returns:
        corner_points: 标准化后的角点 (4, 2)
    """
    pts = np.array(corners, dtype=np.float32)

    # 按 Y 坐标排序（上下）
    pts = pts[np.argsort(pts[:, 1])]

    # 上排两个点（Y 较小）
    top_two = pts[:2]
    # 下排两个点（Y 较大）
    bottom_two = pts[2:]

    # 上排按 X 排序：左→右
    top_two = top_two[np.argsort(top_two[:, 0])]
    # 下排按 X 排序：左→右
    bottom_two = bottom_two[np.argsort(bottom_two[:, 0])]

    top_left, top_right = top_two[0], top_two[1]
    bottom_left, bottom_right = bottom_two[0], bottom_two[1]

    return np.array([top_left, top_right, bottom_left, bottom_right], dtype=np.float32)


if __name__ == "__main__":
    # 简单测试
    # 假设检测到的球场四角（像素坐标）
    mock_corners = np.array([
        [100, 200],   # top-left
        [580, 200],   # top-right
        [50, 540],    # bottom-left
        [630, 540],   # bottom-right
    ], dtype=np.float32)

    params = calculate_view_parameters(mock_corners)
    print("摄像机参数:", params)

    M, inv_M = get_perspective_transform_matrix(mock_corners)
    print("透视矩阵已计算")

    # 测试坐标转换
    court_pos = pixel_to_court((320, 360), inv_M)
    print(f"像素 (320, 360) -> 场地 {court_pos} cm")

    zone = get_zone(court_pos[1])
    side = get_near_far_side(court_pos[1])
    print(f"区域: {zone}, 侧别: {side}")

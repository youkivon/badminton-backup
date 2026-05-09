"""
球员站位判断模块
基于 Deep-Learning-Based-Temporal-Analysis-of-Badminton-Gameplay/player_tracker.py
中无需 YOLO 的 near/far 判断逻辑整合。

功能：
1. 球员 near/far 侧别判断（基于 Y 坐标与球网的相对位置）
2. 球员区域判断（网前/中场/后场）
3. 击球时球员站位聚合

依赖：
- court_calibration.py（COURT_LENGTH, COURT_WIDTH, NET_Y 等常量）
"""

try:
    from .court_calibration import (
        COURT_LENGTH,
        COURT_WIDTH,
        NET_Y,
        CourtZone,
        get_zone,
        get_near_far_side,
    )
except ImportError:
    from court_calibration import (
        COURT_LENGTH,
        COURT_WIDTH,
        NET_Y,
        CourtZone,
        get_zone,
        get_near_far_side,
    )


def assign_near_far_from_pair(positions: list) -> tuple | None:
    """
    给定同一帧中检测到的两个球员位置，判断哪个是 near（近端）哪个是 far（远端）。

    双打中：
    - near 侧 = 靠近摄像机的一侧（画面下方，Y 坐标 < 球网 Y）
    - far 侧 = 远离摄像机的一侧（画面上方，Y 坐标 > 球网 Y）

    Args:
        positions: [pos1, pos2]，每个 pos 是 (x, y) 或 {"x": x, "y": y}

    Returns:
        (near_pos, far_pos) 元组，或 None（无法判断时）
    """
    if len(positions) != 2:
        return None

    def get_y(p):
        return p[1] if isinstance(p, (list, tuple)) else p["y"]

    p0_y = get_y(positions[0])
    p1_y = get_y(positions[1])

    # 近端 = Y 坐标较小（在画面下方）
    if p0_y < p1_y:
        near, far = positions[0], positions[1]
    else:
        near, far = positions[1], positions[0]

    return near, far


def verify_and_fix_side(
    transformed_players_dict: dict,
    court_length: int = COURT_LENGTH,
    net_y: int = NET_Y,
) -> dict:
    """
    根据球场坐标系验证并修正 near/far 侧别。

    原理：far 侧球员 Y 坐标应 > 球网 Y，near 侧球员 Y 坐标应 < 球网 Y。
    如果反过来，说明初始判断有误，需要交换。

    来源：player_tracker.py::verify_and_fix_players()

    Args:
        transformed_players_dict: {frame_id: [pos1, pos2]}，pos 为 (x_cm, y_cm)
        court_length: 场地长度（默认 1340 cm）
        net_y: 球网 Y 坐标（默认 670 cm）

    Returns:
        corrected_dict: 同格式，已修正侧别
    """
    corrected = {}

    for frame_id, positions in transformed_players_dict.items():
        if len(positions) != 2:
            continue

        far_pos = positions[0]
        near_pos = positions[1]

        # far 侧球员 Y 应该 > 球网 Y
        # near 侧球员 Y 应该 < 球网 Y
        if far_pos[1] <= net_y and near_pos[1] >= net_y:
            # 需要交换
            corrected[frame_id] = [near_pos, far_pos]
        else:
            corrected[frame_id] = [far_pos, near_pos]

    return corrected


def get_player_zone_stats(
    transformed_players_dict: dict,
    court_length: int = COURT_LENGTH,
    net_y: int = NET_Y,
) -> dict:
    """
    统计两个球员各自在网前/中场/后场的出现频率。

    Args:
        transformed_players_dict: {frame_id: [far_pos, near_pos]}，pos=(x_cm, y_cm)

    Returns:
        {
            "far": {"net": count, "mid": count, "back": count, "total": count},
            "near": {"net": count, "mid": count, "back": count, "total": count},
        }
    """
    stats = {
        "far": {"net": 0, "mid": 0, "back": 0, "total": 0},
        "near": {"net": 0, "mid": 0, "back": 0, "total": 0},
    }

    for frame_id, positions in transformed_players_dict.items():
        if len(positions) != 2:
            continue

        far_pos, near_pos = positions[0], positions[1]

        far_zone = get_zone(far_pos[1])
        near_zone = get_zone(near_pos[1])

        stats["far"][far_zone] += 1
        stats["far"]["total"] += 1
        stats["near"][near_zone] += 1
        stats["near"]["total"] += 1

    # 转换为百分比
    for side in ["far", "near"]:
        total = stats[side]["total"]
        if total > 0:
            for zone in ["net", "mid", "back"]:
                stats[side][f"{zone}_pct"] = round(
                    stats[side][zone] / total * 100, 1
                )
        else:
            stats[side]["net_pct"] = 0
            stats[side]["mid_pct"] = 0
            stats[side]["back_pct"] = 0

    return stats


def detect_stationary_players(
    transformed_players_dict: dict,
    threshold_cm: float = 30.0,
    min_frames: int = 30,
) -> list:
    """
    检测站位不动的球员（可用于识别等待/准备姿态）。

    Args:
        transformed_players_dict: {frame_id: [far_pos, near_pos]}
        threshold_cm: 移动超过此距离才算"动了"（默认 30 cm）
        min_frames: 连续多少帧没动才报告（默认 30 帧）

    Returns:
        [{"frame_id": int, "side": "far"|"near", "x_cm": float, "y_cm": float}, ...]
    """
    stationary = []

    for side_idx in [0, 1]:  # 0=far, 1=near
        side_name = "far" if side_idx == 0 else "near"

        prev_pos = None
        still_frames = 0

        for frame_id in sorted(transformed_players_dict.keys()):
            positions = transformed_players_dict[frame_id]
            if len(positions) <= side_idx:
                continue

            current_pos = positions[side_idx]

            if prev_pos is None:
                prev_pos = current_pos
                still_frames = 1
                continue

            dx = current_pos[0] - prev_pos[0]
            dy = current_pos[1] - prev_pos[1]
            dist = (dx**2 + dy**2) ** 0.5

            if dist < threshold_cm:
                still_frames += 1
            else:
                if still_frames >= min_frames:
                    stationary.append({
                        "frame_id": frame_id - still_frames,
                        "side": side_name,
                        "x_cm": round(prev_pos[0], 1),
                        "y_cm": round(prev_pos[1], 1),
                        "still_frames": still_frames,
                    })
                still_frames = 1
                prev_pos = current_pos

    return stationary


if __name__ == "__main__":
    # 测试用例
    mock_dict = {
        1: [(200, 400), (300, 800)],   # far=(200,400), near=(300,800)
        2: [(210, 410), (310, 810)],
        3: [(220, 420), (320, 820)],
    }

    result = verify_and_fix_side(mock_dict)
    print("修正后的 near/far:", result)

    stats = get_player_zone_stats(result)
    print("区域统计:", stats)

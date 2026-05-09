# -*- coding: utf-8 -*-
"""
羽毛球视频分析小程序 - 球员档案数据库
管理球员 profile.json 和历史分析记录
"""
import os, json
from datetime import datetime

PLAYERS_DIR = "/Users/youqifang/Desktop/小程序/players"
os.makedirs(PLAYERS_DIR, exist_ok=True)

# ── 成就徽章定义 ─────────────────────────────────────────────────────────────
BADGE_DEFS = [
    {
        "id": "first_analysis",
        "name": "初登场",
        "desc": "完成第一次技术分析",
        "icon": "[首]",
        "condition": lambda p: len(p.get("sessions", [])) >= 1,
    },
    {
        "id": "streak_3",
        "name": "连分析3次",
        "desc": "累计完成3次分析",
        "icon": "[×3]",
        "condition": lambda p: len(p.get("sessions", [])) >= 3,
    },
    {
        "id": "streak_7",
        "name": "连分析7次",
        "desc": "累计完成7次分析",
        "icon": "[×7]",
        "condition": lambda p: len(p.get("sessions", [])) >= 7,
    },
    {
        "id": "streak_30",
        "name": "连分析30次",
        "desc": "累计完成30次分析",
        "icon": "[×30]",
        "condition": lambda p: len(p.get("sessions", [])) >= 30,
    },
    {
        "id": "score_break_8",
        "name": "突破8分",
        "desc": "任意动作首次突破8分",
        "icon": "[8+]",
        "condition": lambda p: _has_dim_break(p, 8),
    },
    {
        "id": "score_break_9",
        "name": "突破9分",
        "desc": "任意动作首次突破9分",
        "icon": "[9+]",
        "condition": lambda p: _has_dim_break(p, 9),
    },
    {
        "id": "total_up_20pct",
        "name": "总分涨20%",
        "desc": "综合总分相比首次分析提升≥20%",
        "icon": "[↑20%]",
        "condition": lambda p: _total_up_pct(p) >= 0.20,
    },
    {
        "id": "improved_3_errors",
        "name": "改善3项错误",
        "desc": "同一次分析中改善了≥3项历史错误",
        "icon": "[OK3]",
        "condition": lambda p: _improved_count(p) >= 3,
    },
]


def _has_dim_break(profile, threshold: float) -> bool:
    sessions = profile.get("sessions", [])
    if len(sessions) < 1:
        return False
    DIMENSIONS = ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]
    seen = {d: False for d in DIMENSIONS}
    for s in sessions:
        for d in DIMENSIONS:
            vals = [shot.get(d) for shot in s.get("shots", []) if shot.get(d) is not None]
            if vals and max(vals) >= threshold:
                seen[d] = True
    return any(seen.values())


def _total_up_pct(profile) -> float:
    sessions = profile.get("sessions", [])
    if len(sessions) < 2:
        return 0.0
    first_avg = sessions[0].get("avg_quality", 0)
    if first_avg == 0:
        return 0.0
    latest_avg = sessions[-1].get("avg_quality", 0)
    return (latest_avg - first_avg) / first_avg


def _improved_count(profile) -> int:
    sessions = profile.get("sessions", [])
    if len(sessions) < 2:
        return 0
    # 看最新一次 vs 前一次有多少错误数量减少
    prev = sessions[-2].get("error_history", {})
    curr = sessions[-1].get("error_history", {})
    count = 0
    for err, cdata in curr.items():
        pc = prev.get(err, {}).get("count", 0)
        if pc > 0 and cdata.get("count", 0) < pc:
            count += 1
    return count


def check_badges(profile: dict) -> list:
    """检查并返回本次新解锁的徽章 ID 列表"""
    current = set(profile.get("badges", []))
    new_badges = []
    for b in BADGE_DEFS:
        if b["id"] not in current and b["condition"](profile):
            new_badges.append(b["id"])
    return new_badges


def get_all_badges(profile: dict) -> list:
    """返回当前已解锁的徽章详情列表"""
    earned = set(profile.get("badges", []))
    return [
        {
            "id": b["id"],
            "name": b["name"],
            "desc": b["desc"],
            "icon": b["icon"],
            "earned": b["id"] in earned,
        }
        for b in BADGE_DEFS
    ]


def get_player_dir(name: str) -> str:
    """获取球员目录，不存在则创建"""
    safe = name.strip().replace(" ", "_")
    path = os.path.join(PLAYERS_DIR, safe)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "history"), exist_ok=True)
    os.makedirs(os.path.join(path, "frame_archive"), exist_ok=True)
    return path


def load_profile(name: str) -> dict:
    """加载球员档案，不存在则创建空白模板"""
    path = os.path.join(get_player_dir(name), "profile.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "name": name,
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "last_analysis": None,
        "total_sessions": 0,
        "play_style": "",
        "tags": [],
        "wechat_id": "",  # 客户微信账号，分析完成后推送到此微信
        "badges": [],      # 已解锁的徽章ID列表
        "sessions": []
    }


def save_profile(name: str, profile: dict):
    """保存球员档案"""
    path = os.path.join(get_player_dir(name), "profile.json")
    profile["last_analysis"] = datetime.now().strftime("%Y-%m-%d")
    profile["total_sessions"] = len(profile["sessions"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def add_session(name: str, session_data: dict, frames_dir: str = None):
    """
    新增一次分析记录到球员档案

    session_data 格式:
    {
        "date": "2026-05-05",
        "video": "VID_xxx.mp4",
        "shots_count": 14,
        "avg_quality": 3.2,
        "quality_trend": "up",        # "up" / "down" / "same" / null
        "prev_avg_quality": 3.0,
        "error_history": {
            "动作僵硬": {"count": 5, "prev_count": 7, "status": "improved"},
            ...
        },
        "total_errors": 20,
        "unique_errors": 6,
        "shots": [...]                   # 详细击球数据
    }
    """
    profile = load_profile(name)

    # 计算进步状态
    if profile["sessions"]:
        prev = profile["sessions"][-1]
        prev_avg = prev.get("avg_quality", 0)
        curr_avg = session_data.get("avg_quality", 0)
        if curr_avg > prev_avg + 0.1:
            session_data["quality_trend"] = "up"
        elif curr_avg < prev_avg - 0.1:
            session_data["quality_trend"] = "down"
        else:
            session_data["quality_trend"] = "same"
        session_data["prev_avg_quality"] = prev_avg
    else:
        session_data["quality_trend"] = None
        session_data["prev_avg_quality"] = None

    # 追加记录
    profile["sessions"].append(session_data)

    # 检查徽章解锁（session 已追加，可以判断条件）
    new_badge_ids = check_badges(profile)
    if new_badge_ids:
        existing = set(profile.get("badges", []))
        profile["badges"] = list(existing | set(new_badge_ids))
        session_data["new_badges"] = new_badge_ids

    save_profile(name, profile)

    # 同时保存详细历史 JSON
    hist_path = os.path.join(get_player_dir(name), "history", f"{session_data['date']}.json")
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    return profile


def get_history(name: str) -> list:
    """获取球员所有历史记录"""
    profile = load_profile(name)
    return profile.get("sessions", [])


def list_players() -> list:
    """列出所有球员"""
    return [d for d in os.listdir(PLAYERS_DIR)
            if os.path.isdir(os.path.join(PLAYERS_DIR, d)) and d != "__pycache__"]


def compute_progress(name: str) -> dict:
    """
    计算进步情况：对比最新一次 vs 第一次分析
    返回: {"total_sessions", "first_avg", "latest_avg", "delta",
           "improved_errors", "worsened_errors", "new_errors",
           "dim_progress": {dim: {"first": x, "latest": y, "delta": z}, ...}}
    """
    DIMENSIONS = ["发力链", "闪腕", "步伐", "拍面控制", "整体协调"]

    sessions = get_history(name)
    if len(sessions) < 2:
        return {"total_sessions": len(sessions), "enough_data": False}

    first = sessions[0]
    latest = sessions[-1]

    first_avg = first.get("avg_quality", 0)
    latest_avg = latest.get("avg_quality", 0)
    delta = round(latest_avg - first_avg, 1)

    # 错误变化
    first_errs = first.get("error_history", {})
    latest_errs = latest.get("error_history", {})

    improved = []
    worsened = []
    new_in_latest = []

    all_errs = set(first_errs.keys()) | set(latest_errs.keys())
    for err in all_errs:
        fc = first_errs.get(err, {}).get("count", 0)
        lc = latest_errs.get(err, {}).get("count", 0)
        if lc < fc:
            improved.append({"error": err, "from": fc, "to": lc})
        elif lc > fc:
            worsened.append({"error": err, "from": fc, "to": lc})
        if err not in first_errs and err in latest_errs:
            new_in_latest.append({"error": err, "count": lc})

    # 各维度均分变化
    dim_progress = {}
    for dim in DIMENSIONS:
        f_vals = [s.get(dim) for s in first.get("shots", []) if s.get(dim) is not None]
        l_vals = [s.get(dim) for s in latest.get("shots", []) if s.get(dim) is not None]
        if f_vals and l_vals:
            f_avg = round(sum(f_vals) / len(f_vals), 1)
            l_avg = round(sum(l_vals) / len(l_vals), 1)
            dim_progress[dim] = {
                "first": f_avg,
                "latest": l_avg,
                "delta": round(l_avg - f_avg, 1)
            }

    return {
        "total_sessions": len(sessions),
        "enough_data": True,
        "first_avg": first_avg,
        "latest_avg": latest_avg,
        "delta": delta,
        "improved_errors": improved,
        "worsened_errors": worsened,
        "new_errors": new_in_latest,
        "first_date": first.get("date", ""),
        "latest_date": latest.get("date", ""),
        "dim_progress": dim_progress,
    }


if __name__ == "__main__":
    # 测试
    print("球员列表:", list_players())
    for p in list_players():
        s = get_history(p)
        print(f"  {p}: {len(s)} 次记录")

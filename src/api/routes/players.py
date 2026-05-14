# -*- coding: utf-8 -*-
"""
球员管理路由。
"""
import os
from flask import Blueprint, jsonify, request

# 添加 src 路径
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../..", "src"))

from src import player_db as pdb

bp = Blueprint("players", __name__)


@bp.route("/api/players", methods=["GET"])
def list_players():
    """列出所有球员。"""
    raw = pdb.list_players()
    # raw: ["张三", "李四"] → 转成 [{"name": "张三", "session_count": 0}, ...]
    players = []
    for name in raw:
        profile = pdb.load_profile(name)
        players.append({
            "name": name,
            "session_count": profile.get("total_sessions", 0),
        })
    return jsonify({"players": players})


@bp.route("/api/players", methods=["POST"])
def create_player():
    """创建球员档案。"""
    body = request.get_json() or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "缺少 name 字段"}), 400

    # 检查是否已存在
    if _player_exists(name):
        return jsonify({"error": "球员已存在"}), 409

    from datetime import datetime
    pdb.save_profile(name, {
        "name": name,
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "last_analysis": "",
        "play_style": body.get("play_style", ""),
        "level": body.get("level", ""),
        "wechat_id": body.get("wechat_id", ""),
        "profile": {
            "play_style": body.get("play_style", ""),
            "level": body.get("level", ""),
            "tags": [],
        },
        "sessions": [],
        "badges": [],
    })

    profile = pdb.load_profile(name)
    return jsonify(profile), 201


def _player_exists(name: str) -> bool:
    """球员目录是否存在（目录创建了不一定有档案，需检查 profile.json）。"""
    profile_path = os.path.join(pdb.get_player_dir(name), "profile.json")
    return os.path.exists(profile_path)


@bp.route("/api/players/<name>", methods=["GET"])
def get_player(name):
    """获取球员完整档案。"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    profile = pdb.load_profile(name)
    return jsonify(profile)


@bp.route("/api/players/<name>", methods=["DELETE"])
def delete_player(name):
    """删除球员（及其所有历史）。"""
    import shutil
    if not os.path.exists(pdb.get_player_dir(name)):
        return jsonify({"error": "球员不存在"}), 404
    shutil.rmtree(pdb.get_player_dir(name))
    return "", 204


@bp.route("/api/players/<name>", methods=["PATCH"])
def update_player(name):
    """更新球员基本信息（wechat_id / play_style / level）"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    body = request.get_json() or {}
    profile = pdb.load_profile(name)
    # 只允许更新这几个字段
    for field in ("wechat_id", "play_style", "level"):
        if field in body:
            profile[field] = body[field]
    pdb.save_profile(name, profile)
    return jsonify(profile)


@bp.route("/api/players/<name>/history", methods=["GET"])
def list_history(name):
    """历史分析列表。"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    sessions = pdb.get_history(name)
    return jsonify({"sessions": sessions})


@bp.route("/api/players/<name>/history/<session_id>", methods=["GET"])
def get_history_detail(name, session_id):
    """单次分析详情。"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    history = pdb.get_history(name)
    for s in history:
        if s.get("id") == session_id:
            return jsonify(s)
    return jsonify({"error": "记录不存在"}), 404


@bp.route("/api/players/<name>/report/<session_id>", methods=["GET"])
def download_report(name, session_id):
    """下载 PDF 报告。"""
    from flask import send_file
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    history = pdb.get_history(name)
    for s in history:
        if s.get("id") == session_id:
            path = s.get("report_path", "")
            if path and os.path.exists(path):
                return send_file(path, as_attachment=True,
                               download_name=f"{name}_报告_{session_id}.pdf")
            return jsonify({"error": "报告文件不存在"}), 404
    return jsonify({"error": "记录不存在"}), 404


@bp.route("/api/players/<name>/badges", methods=["GET"])
def list_badges(name):
    """获取球员已解锁徽章列表及全部徽章状态"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    profile = pdb.load_profile(name)
    from src.player_db import get_all_badges
    badges = get_all_badges(profile)
    return jsonify({"badges": badges, "earned": profile.get("badges", [])})


@bp.route("/api/players/<name>/progress", methods=["GET"])
def get_progress(name):
    """进步曲线数据（含跨session error_history对比）"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    progress = pdb.compute_progress(name)
    return jsonify(progress)


@bp.route("/api/players/<name>/streak", methods=["GET"])
def get_streak(name):
    """获取球员连续打卡数据"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    streak = pdb.get_streak(name)
    return jsonify(streak)


@bp.route("/api/players/<name>/monthly_report/<int:year>/<int:month>", methods=["GET"])
def get_monthly_report(name, year, month):
    """获取指定月份的进步报告数据"""
    if not _player_exists(name):
        return jsonify({"error": "球员不存在"}), 404
    if month < 1 or month > 12:
        return jsonify({"error": "月份无效"}), 400
    report = pdb.get_monthly_report(name, year, month)
    if not report:
        return jsonify({"error": "该月份无数据"}), 404
    return jsonify(report)

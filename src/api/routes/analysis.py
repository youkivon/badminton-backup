# -*- coding: utf-8 -*-
"""
分析任务路由。
"""
import os
from flask import Blueprint, jsonify, request

sys_path = os.path.join(os.path.dirname(__file__), "../..", "src")
import sys
sys.path.insert(0, sys_path)

from src.api.services.analysis_runner import submit_job, get_job_status

bp = Blueprint("analysis", __name__)


@bp.route("/api/players/<name>/analyze", methods=["POST"])
def analyze(name):
    """上传视频并触发异步分析。"""
    from src import player_db as pdb
    if not pdb.load_profile(name):
        return jsonify({"error": "球员不存在"}), 404

    if "video" not in request.files:
        return jsonify({"error": "缺少 video 字段"}), 400

    video = request.files["video"]
    if not video.filename.lower().endswith(".mp4"):
        return jsonify({"error": "仅支持 MP4 格式"}), 400

    report_type = request.form.get("report_type", "full")
    if report_type not in ("tactical", "technical", "full"):
        return jsonify({"error": "report_type 必须是 tactical / technical / full"}), 400

    # 保存临时视频文件
    job_id = submit_job.__code__.co_freevars and video.filename or "_"
    import uuid
    job_id = str(uuid.uuid4())

    tmp_dir = os.environ.get("BADMINTON_TMP_DIR", "/tmp/badminton_jobs")
    os.makedirs(tmp_dir, exist_ok=True)
    video_path = os.path.join(tmp_dir, f"{job_id}.mp4")
    video.save(video_path)

    # 检查文件大小（微信限制 10MB）
    size = os.path.getsize(video_path)
    if size > 10 * 1024 * 1024:
        os.remove(video_path)
        return jsonify({"error": f"视频过大（{size//1024//1024}MB），微信限制10MB"}), 413

    # 提交任务
    from src.api.services.analysis_runner import submit_job as _submit
    actual_job_id = _submit(name, video_path, report_type)

    return jsonify({
        "job_id": actual_job_id,
        "status": "pending",
        "message": "视频已接收，等待分析",
    }), 202


@bp.route("/api/jobs/<job_id>", methods=["GET"])
def job_status(job_id):
    """查询任务状态。"""
    from src.api.services.analysis_runner import get_job_status as _get
    job = _get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(job)

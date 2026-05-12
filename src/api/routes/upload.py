# -*- coding: utf-8 -*-
"""
视频质检路由。
"""
import os, uuid, tempfile
from flask import Blueprint, jsonify, request

bp = Blueprint("upload", __name__)


@bp.route("/api/upload/video", methods=["POST"])
def video_quality():
    """仅做视频质检，不触发分析。"""
    if "video" not in request.files:
        return jsonify({"error": "缺少 video 字段"}), 400

    video = request.files["video"]
    if not video.filename.lower().endswith(".mp4"):
        return jsonify({"error": "仅支持 MP4 格式"}), 400

    size = 0
    tmp_path = None
    try:
        # 保存到临时文件
        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.mp4")
        video.save(tmp_path)
        size = os.path.getsize(tmp_path)

        if size > 10 * 1024 * 1024:
            return jsonify({
                "valid": False,
                "reason": f"视频过大（{size//1024//1024}MB），微信限制10MB"
            })

        # 用 ffprobe 检查分辨率和时长
        import subprocess
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", tmp_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        import json as _json
        try:
            info = _json.loads(result.stdout)
        except Exception:
            return jsonify({"valid": False, "reason": "无法读取视频信息"}), 200

        video_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
        if not video_stream:
            return jsonify({"valid": False, "reason": "找不到视频流"}), 200

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        fps_str = video_stream.get("r_frame_rate", "30/1")
        # 解析分数格式 fps 如 "30000/1001"
        try:
            num, den = fps_str.split("/")
            fps = round(int(num) / int(den))
        except Exception:
            fps = 30

        duration = float(info.get("format", {}).get("duration", 0))

        # 校验分辨率
        if height < 720:
            return jsonify({
                "valid": False,
                "reason": f"分辨率不足720p（当前：{height}p）",
                "resolution": f"{width}x{height}",
                "fps": fps,
                "duration": round(duration),
            }), 200

        # 校验时长
        if duration > 600:
            return jsonify({
                "valid": False,
                "reason": f"视频时长超过10分钟（当前：{int(duration)}秒）",
                "resolution": f"{width}x{height}",
                "fps": fps,
                "duration": round(duration),
            }), 200

        return jsonify({
            "valid": True,
            "resolution": f"{width}x{height}",
            "fps": fps,
            "duration": round(duration),
            "message": "视频合格",
        }), 200

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

# -*- coding: utf-8 -*-
"""
后台分析任务运行器。
在线程中运行视频分析，不阻塞 Flask 请求。
"""
import os, sys, uuid, threading, logging, time, json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

# 添加 src 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../..", "src"))

log = logging.getLogger(__name__)

# ── 全局任务池 & Job 存储 ───────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict = {}  # job_id → JobStatus dict


# ── 公开 API ────────────────────────────────────────────────────────────────

def submit_job(player_name: str, video_path: str, report_type: str = "full") -> str:
    """提交分析任务，返回 job_id。"""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "任务已接收",
        "result": None,
    }
    _executor.submit(_run_analysis, job_id, player_name, video_path, report_type)
    return job_id


def get_job_status(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


# ── 内部逻辑 ────────────────────────────────────────────────────────────────

def _run_analysis(job_id: str, player_name: str, video_path: str, report_type: str):
    """在线程中运行完整分析流程。"""
    try:
        _update_job(job_id, "running", 5, "正在提取视频帧...")

        # 调用已有分析脚本
        from src import run_analysis as ra

        # 构造输出目录
        frames_dir = f"/tmp/bad_shots/target_frames/{job_id}"
        os.makedirs(frames_dir, exist_ok=True)

        _update_job(job_id, "running", 10, "正在抽帧...")

        # 抽帧
        ra.extract_smart_frames(video_path, frames_dir, fps=4, max_ball=150, max_noball=20)

        _update_job(job_id, "running", 30, "正在 VLM 分析...")

        # VLM 分析（使用缓存的帧）
        results = ra.load_or_run_analysis(frames_dir)

        _update_job(job_id, "running", 70, "正在生成报告...")

        # 组装数据
        shots = results.get("shots", [])
        from src import report_generator as rg

        # 生成报告
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        player_dir = os.path.join(os.environ.get("BADMINTON_REPORTS_DIR",
                                "/Users/youqifang/Desktop/小程序/reports"), player_name)
        os.makedirs(player_dir, exist_ok=True)
        pdf_path = os.path.join(player_dir, f"报告_{ts}.pdf")

        report_data = _build_report_data(player_name, shots, results, report_type)
        rg.make_report(report_data, pdf_path)

        _update_job(job_id, "running", 85, "正在保存档案...")

        # 保存到球员历史
        from src import player_db as pdb
        avg_q = sum(s.get("quality", 0) for s in shots) / max(len(shots), 1)

        session_data = {
            "id": ts,
            "player_name": player_name,
            "created_at": datetime.now().isoformat(),
            "status": "completed",
            "video_duration": 0,
            "shots_count": len(shots),
            "avg_quality": round(avg_q, 1),
            "report_path": pdf_path,
            "report_type": report_type,
            "shots": shots,
        }
        pdb.add_session(player_name, session_data, frames_dir)

        _update_job(job_id, "running", 95, "正在推送微信...")

        # 微信推送
        try:
            import asyncio
            asyncio.run(ra.send_wechat_report(pdf_path, player_name, len(shots), avg_q))
        except Exception as e:
            log.warning(f"微信推送失败: {e}")

        _update_job(job_id, "completed", 100, "分析完成", result={
            "session_id": ts,
            "shots_count": len(shots),
            "avg_quality": round(avg_q, 1),
            "report_path": pdf_path,
        })

    except Exception as e:
        log.exception(f"分析任务 {job_id} 失败")
        _update_job(job_id, "failed", 0, f"分析失败: {e}")


def _build_report_data(player_name: str, shots: list, raw_results: dict, report_type: str) -> dict:
    """从 shots 组装报告数据。"""
    return {
        "player_name": player_name,
        "report_type": report_type,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "shots": shots,
        "total_rallies": raw_results.get("rally_count", 1),
        "duration_sec": raw_results.get("duration", 0),
        "avg_quality": sum(s.get("quality", 0) for s in shots) / max(len(shots), 1) if shots else 0,
    }


def _update_job(job_id: str, status: str, progress: int, message: str, result=None):
    if job_id in _jobs:
        _jobs[job_id].update({
            "status": status,
            "progress": progress,
            "message": message,
            "result": result,
        })

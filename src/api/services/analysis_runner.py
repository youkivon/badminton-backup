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

from src import run_analysis as ra
from src import player_db as pdb
from src import report_generator as rg

log = logging.getLogger(__name__)

# ── 全局任务池 & Job 存储 ───────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict = {}  # job_id → JobStatus dict


# ── 公开 API ────────────────────────────────────────────────────────────────

def submit_job(player_name: str, video_path: str, report_type: str = "full",
                customer_side: str = "") -> str:
    """提交分析任务，返回 job_id。customer_side 指定客户所在侧（near/far）。"""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "任务已接收",
        "result": None,
    }
    _executor.submit(_run_analysis, job_id, player_name, video_path, report_type, customer_side)
    return job_id


def get_job_status(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


# ── 内部逻辑 ────────────────────────────────────────────────────────────────

def _run_analysis(job_id: str, player_name: str, video_path: str, report_type: str,
                  customer_side: str = ""):
    """在线程中运行完整分析流程。"""
    try:
        _update_job(job_id, "running", 5, "正在提取视频帧...")

        # 调用已有分析脚本
        # 构造输出目录
        frames_dir = f"/tmp/bad_shots/target_frames/{job_id}"
        os.makedirs(frames_dir, exist_ok=True)

        _update_job(job_id, "running", 10, "正在抽帧...")

        # 抽帧
        ra.extract_smart_frames(video_path, frames_dir, fps=4, max_ball=150, max_noball=20)

        _update_job(job_id, "running", 30, "正在 VLM 分析...")

        # VLM 分析（使用缓存的帧）
        results = ra.load_or_run_analysis(
            frames_dir, False, None, None, job_id,
            player_name, customer_side
        )
        shots = results if isinstance(results, list) else results.get("shots", [])
        _update_job(job_id, "running", 70, "正在生成报告...")

        # ── 聚合 error_history（跨shot汇总 E-code 频率）────────────────────
        from collections import Counter
        err_counter = Counter()
        for s in shots:
            for e in (s.get("errors") or []):
                err_counter[e.strip()] += 1

        # ── 查前一次 session，计算各 error 的改善/加重状态 ─────────────────
        prev_errs = {}
        try:
            prev_sessions = pdb.get_history(player_name)
            if prev_sessions:
                prev_errs = prev_sessions[-1].get("error_history", {})
        except Exception:
            pass

        error_history = {}
        for err, cnt in err_counter.most_common(20):
            prev_count = prev_errs.get(err, {}).get("count", 0) if isinstance(prev_errs, dict) else 0
            if prev_count == 0:
                status = "new"
            elif cnt < prev_count:
                status = "improved"
            elif cnt > prev_count:
                status = "worsened"
            else:
                status = "same"
            error_history[err] = {"count": cnt, "prev_count": prev_count, "status": status}

        # ── 保存 ────────────────────────────────────────────────────────────
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
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
            "error_history": error_history,
            "total_errors": sum(err_counter.values()),
            "unique_errors": len(err_counter),
        }

        # ── 报告生成（放在 add_session 之后，避免 add_session 读取不到 shots）──
        _update_job(job_id, "running", 85, "正在生成报告...")
        ts_report = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        player_dir = os.path.join(os.environ.get("BADMINTON_REPORTS_DIR",
                                "/Users/youqifang/Desktop/小程序/reports"), player_name)
        os.makedirs(player_dir, exist_ok=True)
        pdf_path = os.path.join(player_dir, f"报告_{ts_report}.pdf")
        report_data = _build_report_data(player_name, shots, results, report_type)
        rg.make_report(report_data, pdf_path)
        session_data["report_path"] = pdf_path

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

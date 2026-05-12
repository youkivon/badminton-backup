# -*- coding: utf-8 -*-
"""
pytest tests for badminton API.
必须先运行: pip install pytest flask requests
"""
import os, sys, json, time, tempfile
from datetime import datetime

import pytest

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

# ── 辅助 ─────────────────────────────────────────────────────────────────────

TEST_PLAYERS_DIR = tempfile.mkdtemp(prefix="badminton_test_players_")
TEST_REPORTS_DIR = tempfile.mkdtemp(prefix="badminton_test_reports_")


@pytest.fixture
def client():
    """创建测试用 Flask client（延迟导入避免循环）。"""
    # 重定向存储路径
    os.environ["BADMINTON_PLAYERS_DIR"] = TEST_PLAYERS_DIR
    os.environ["BADMINTON_REPORTS_DIR"] = TEST_REPORTS_DIR

    from src.api.app import create_app
    import src.api.routes.players as pbp
    import src.player_db as pdb

    # 直接修改模块级变量，让已 import 的引用也生效
    pdb.PLAYERS_DIR = TEST_PLAYERS_DIR

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── 球员 CRUD ─────────────────────────────────────────────────────────────────

def test_create_and_list_player(client):
    """创建球员 → 列出球员"""
    # 创建
    rv = client.post("/api/players",
                     json={"name": "测试球员", "play_style": "单打后场", "level": "初级"})
    assert rv.status_code == 201
    data = rv.get_json()
    assert data["name"] == "测试球员"
    assert "created_at" in data

    # 重复创建 → 409
    rv2 = client.post("/api/players", json={"name": "测试球员"})
    assert rv2.status_code == 409

    # 列出
    rv3 = client.get("/api/players")
    assert rv3.status_code == 200
    players = rv3.get_json()["players"]
    assert any(p["name"] == "测试球员" for p in players)


def test_get_player(client):
    """获取球员档案"""
    client.post("/api/players", json={"name": "张三", "level": "中级"})

    rv = client.get("/api/players/张三")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["name"] == "张三"
    assert data.get("total_sessions", 0) == 0
    assert data.get("badges") == []

    # 不存在 → 404
    rv4 = client.get("/api/players/不存在的球员")
    assert rv4.status_code == 404


def test_delete_player(client):
    """删除球员"""
    client.post("/api/players", json={"name": "待删除球员"})

    rv = client.delete("/api/players/待删除球员")
    assert rv.status_code == 204

    # 确认删除
    rv2 = client.get("/api/players/待删除球员")
    assert rv2.status_code == 404


# ── 历史记录 ─────────────────────────────────────────────────────────────────

def test_history_empty(client):
    """无历史时返回空列表"""
    client.post("/api/players", json={"name": "新球员"})

    rv = client.get("/api/players/新球员/history")
    assert rv.status_code == 200
    assert rv.get_json()["sessions"] == []


# ── 进度数据 ─────────────────────────────────────────────────────────────────

def test_progress_empty(client):
    """无历史时返回空趋势"""
    client.post("/api/players", json={"name": "新球员2"})

    rv = client.get("/api/players/新球员2/progress")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["total_sessions"] == 0
    assert data["enough_data"] is False


# ── 视频质检 ─────────────────────────────────────────────────────────────────

def test_video_quality_check(client):
    """视频质检接口"""
    # 创建一个假视频文件（不是真实 MP4，但够测试接口）
    video_path = os.path.join(TEST_REPORTS_DIR, "test_video.mp4")
    with open(video_path, "wb") as f:
        f.write(b"fake mp4 data for testing")

    with open(video_path, "rb") as f:
        rv = client.post("/api/upload/video",
                         data={"video": (f, "test.mp4")},
                         content_type="multipart/form-data")

    # 接口存在即可（真实视频才校验分辨率）
    assert rv.status_code in (200, 400)


# ── 分析任务（模拟，不实际运行 VLM）────────────────────────────────────────

def test_analyze_returns_job_id(client):
    """提交分析任务，返回 job_id"""
    client.post("/api/players", json={"name": "分析测试球员"})

    video_path = os.path.join(TEST_REPORTS_DIR, "test_video2.mp4")
    with open(video_path, "wb") as f:
        f.write(b"fake video for analysis test")

    with open(video_path, "rb") as f:
        rv = client.post(
            f"/api/players/分析测试球员/analyze",
            data={"video": (f, "test.mp4")},
            content_type="multipart/form-data"
        )

    assert rv.status_code == 202
    data = rv.get_json()
    assert "job_id" in data
    assert data["status"] == "pending"


def test_job_status_polling(client):
    """轮询任务状态"""
    client.post("/api/players", json={"name": "轮询球员"})

    video_path = os.path.join(TEST_REPORTS_DIR, "test_video3.mp4")
    with open(video_path, "wb") as f:
        f.write(b"fake video for polling test")

    with open(video_path, "rb") as f:
        rv = client.post(
            f"/api/players/轮询球员/analyze",
            data={"video": (f, "test.mp4")},
            content_type="multipart/form-data"
        )

    job_id = rv.get_json()["job_id"]

    # 轮询状态
    rv2 = client.get(f"/api/jobs/{job_id}")
    assert rv2.status_code == 200
    data2 = rv2.get_json()
    assert "status" in data2
    # status 应为 pending / running / completed / failed 之一


# ── 错误处理 ─────────────────────────────────────────────────────────────────

def test_get_nonexistent_player(client):
    """404 球员"""
    rv = client.get("/api/players/宇宙不存在的人")
    assert rv.status_code == 404
    assert "error" in rv.get_json()


def test_create_player_missing_name(client):
    """缺少 name 字段 → 400"""
    rv = client.post("/api/players", json={"level": "中级"})
    assert rv.status_code == 400

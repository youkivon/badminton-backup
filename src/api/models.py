# -*- coding: utf-8 -*-
"""
数据模型（请求/响应 Pydantic-lite dataclass）。
实际验证用 marshmallow 或 pydantic，这里简化。
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List


# ── 球员 ─────────────────────────────────────────────────────────────────────

@dataclass
class PlayerProfile:
    play_style: str = ""
    level: str = ""
    tags: List[str] = ""


@dataclass
class Player:
    name: str
    created_at: str
    last_analysis: Optional[str] = None
    session_count: int = 0
    badges: List[str] = ""
    profile: PlayerProfile = None

    def __post_init__(self):
        if self.profile is None:
            self.profile = PlayerProfile()
        if isinstance(self.profile, dict):
            self.profile = PlayerProfile(**self.profile)

    def to_dict(self):
        d = asdict(self)
        d["profile"] = asdict(self.profile)
        return d


# ── 分析记录 ─────────────────────────────────────────────────────────────────

@dataclass
class AnalysisSession:
    id: str
    player_name: str
    created_at: str
    status: str  # completed / failed / running
    video_duration: int = 0
    shots_count: int = 0
    avg_quality: float = 0.0
    report_path: str = ""
    error: Optional[str] = None

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v != ""}


# ── Job ──────────────────────────────────────────────────────────────────────

@dataclass
class JobStatus:
    job_id: str
    status: str  # pending / running / completed / failed
    progress: int = 0
    message: str = ""
    result: Optional[dict] = None

# 羽毛球视频分析小程序 - API 规范

## 概述

Flask 后端，服务微信小程序。视频上传后后台异步分析，完成后推送微信通知。

**基础路径**: `http://localhost:5000/api/`

---

## 数据模型

### Player
```json
{
  "name": "张三",
  "created_at": "2026-05-11T10:00:00Z",
  "last_analysis": "2026-05-11T10:30:00Z",
  "session_count": 3,
  "badges": ["first_analysis", "streak_3"],
  "profile": {
    "play_style": "双打前场",
    "level": "中级",
    "tags": ["握拍过紧"]
  }
}
```

### AnalysisSession
```json
{
  "id": "2026-05-11_103000",
  "player_name": "张三",
  "created_at": "2026-05-11T10:30:00Z",
  "status": "completed",
  "video_duration": 60,
  "shots_count": 12,
  "avg_quality": 7.2,
  "report_path": "/reports/张三_2026-05-11_103000.pdf",
  "error": null
}
```

### JobStatus
```json
{
  "job_id": "uuid",
  "status": "pending|running|completed|failed",
  "progress": 50,
  "message": "正在分析第 5/12 帧",
  "result": { ... }
}
```

---

## 接口清单

### 球员管理

#### POST /api/players
创建球员档案。

**Request**: `{"name": "张三", "play_style": "双打前场", "level": "中级"}`
**Response 201**: `{"name": "张三", "created_at": "..."}`
**Response 400**: `{"error": "球员已存在"}`

#### GET /api/players
列出所有球员。

**Response 200**: `{"players": [{"name": "张三", "session_count": 3}, ...]}`

#### GET /api/players/\<name\>
获取球员完整档案。

**Response 200**: `Player` 对象（含 badges）
**Response 404**: `{"error": "球员不存在"}`

#### DELETE /api/players/\<name\>
删除球员（及其所有历史）。

**Response 204**: 空
**Response 404**: `{"error": "球员不存在"}`

---

### 视频分析

#### POST /api/players/\<name\>/analyze
上传视频并触发异步分析。

**Request**: `multipart/form-data`, 字段 `video`（MP4 文件，≤10MB）
**Query 参数**:
- `report_type`: `tactical` | `technical` | `full`（默认 `full`）

**Response 202**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "视频已接收，等待分析"
}
```

**分析流程**（后台）:
1. 视频质检（分辨率≥720p，时长≤10分钟）
2. 抽帧 → VLM 分析
3. 生成 PDF
4. 保存到球员历史
5. 推送微信通知

**Response 400**: `{"error": "视频不合规：分辨率不足720p"}`
**Response 413**: `{"error": "文件过大"}`

#### GET /api/jobs/\<job_id\>
查询分析任务状态。

**Response 200**:
```json
{
  "job_id": "550e8400-...",
  "status": "running",
  "progress": 45,
  "message": "正在分析第 5/12 帧"
}
```

#### GET /api/players/\<name\>/history
获取历史分析列表。

**Response 200**:
```json
{
  "sessions": [
    {"id": "2026-05-11_103000", "created_at": "...", "shots_count": 12, "avg_quality": 7.2},
    {"id": "2026-05-05_090000", "created_at": "...", "shots_count": 8, "avg_quality": 6.8}
  ]
}
```

#### GET /api/players/\<name\>/history/\<session_id\>
获取单次分析详情（含各项评分）。

**Response 200**: `AnalysisSession` 完整对象
**Response 404**: `{"error": "记录不存在"}`

#### GET /api/players/\<name\>/report/\<session_id\>
下载 PDF 报告。

**Response 200**: PDF 文件流
**Response 404**: `{"error": "报告不存在"}`

#### GET /api/players/\<name\>/progress
获取进步曲线数据（各维度历史评分）。

**Response 200**:
```json
{
  "player_name": "张三",
  "dimensions": {
    "发力": [{"date": "2026-05-01", "score": 6.5}, {"date": "2026-05-11", "score": 7.2}],
    "步伐": [...],
    "闪腕": [...]
  },
  "total_trend": [{"date": "2026-05-01", "score": 6.8}, {"date": "2026-05-11", "score": 7.2}]
}
```

---

### 视频质检（不分析）

#### POST /api/upload/video
仅上传 + 质检，不触发分析。

**Request**: `multipart/form-data`, 字段 `video`
**Response 200**:
```json
{
  "valid": true,
  "duration": 60,
  "resolution": "1920x1080",
  "fps": 30,
  "message": "视频合格"
}
```
**Response 200** (不合格):
```json
{
  "valid": false,
  "reason": "分辨率不足720p（当前：640x480）"
}
```

---

## WebSocket（可选，轮询备选）

若后续需要实时进度推送，可加 WebSocket。但第一版用轮询（GET /api/jobs/\<job_id\>）即可。

---

## 微信通知

分析完成后，调用 `run_analysis.send_wechat_report()` 推送 PDF 到微信。

---

## 错误码

| HTTP 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 201 | 创建成功 |
| 204 | 删除成功（无内容） |
| 400 | 请求参数错误 / 视频不合规 |
| 404 | 资源不存在 |
| 409 | 冲突（如球员名已存在） |
| 413 | 文件过大 |
| 500 | 服务器内部错误 |

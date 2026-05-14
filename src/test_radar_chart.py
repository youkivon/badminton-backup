# -*- coding: utf-8 -*-
"""测试五维雷达图渲染"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from report_generator import make_report
import tempfile

# 构造最小测试数据
test_data = {
    "player_name": "测试球员",
    "video": "测试视频.mp4",
    "date": "2026-05-14",
    "duration": "3分20秒",
    "avg_quality": 7.2,
    "shots": [
        {"发力链": 7.5, "闪腕": 6.0, "步伐": 8.0, "拍面控制": 7.0, "整体协调": 6.5, "type": "正手抽球"},
        {"发力链": 8.0, "闪腕": 7.5, "步伐": 7.0, "拍面控制": 8.5, "整体协调": 7.0, "type": "反手抽球"},
        {"发力链": 6.5, "闪腕": 8.0, "步伐": 6.0, "拍面控制": 7.5, "整体协调": 8.0, "type": "正手搓球"},
    ],
    "sessions": [],
    "progress": {"enough_data": False},
    "quality_trend": "上升",
}

output_path = os.path.join(tempfile.gettempdir(), "test_radar_chart.pdf")
print(f"生成测试PDF: {output_path}")

make_report(test_data, output_path)
print("测试PDF生成完成!")
print(f"文件大小: {os.path.getsize(output_path)} bytes")

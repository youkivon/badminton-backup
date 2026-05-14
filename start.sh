#!/bin/bash
# 启动羽毛球视频分析 API 服务
# 用法: ./start.sh 或 bash start.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 读取 .env 文件（如果存在）
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# 检查 key 是否存在
if [ -z "$SILICONFLOW_API_KEY" ]; then
    echo "❌ 错误: SILICONFLOW_API_KEY 未设置"
    echo "请在 .env 文件中设置，或运行: export SILICONFLOW_API_KEY='你的key'"
    echo "示例: echo \"SILICONFLOW_API_KEY=sk-xxx\" > .env"
    exit 1
fi

echo "✅ Key 已加载: ${SILICONFLOW_API_KEY:0:10}..."
cd "$SCRIPT_DIR"
python3 src/api/app.py
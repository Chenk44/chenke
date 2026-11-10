#!/usr/bin/env bash
# macOS / Linux 一键启动
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "→ 创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi

PY=.venv/bin/python
echo "→ 检查依赖 ..."
$PY -m pip install --quiet -r requirements.txt

echo "→ 灌入深圳地点数据 ..."
$PY -m scripts.seed

echo
echo "  就绪：http://127.0.0.1:8000"
echo "  接口文档：http://127.0.0.1:8000/docs"
echo

exec $PY -m uvicorn app.main:app --app-dir backend --reload

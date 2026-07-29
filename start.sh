#!/usr/bin/env bash
# Pronoia 一键启动（开发模式）：后端 :8000 + 前端 :5173
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then cp .env.example .env; echo "已创建 .env，请填入 ARK_API_KEY"; fi

echo "==> 安装后端依赖"
pip install -q -r backend/requirements.txt

echo "==> 启动后端 http://localhost:8000"
(cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!

echo "==> 安装前端依赖并启动 http://localhost:5173"
cd frontend
if [ ! -d node_modules ]; then npm install; fi
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait

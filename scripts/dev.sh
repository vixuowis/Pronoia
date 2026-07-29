#!/usr/bin/env bash
# 一键拉起 Pronoia 后端 (8000) + 前端 (5173)
# 用法: ./scripts/dev.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv/bin/python"
LOG_DIR="$ROOT/.run"
mkdir -p "$LOG_DIR"

# 端口探测：杀掉仍占用的旧进程
for port in 8000 5173; do
  pid=$(lsof -t -i:$port 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "[dev.sh] 端口 $port 被占用，先 kill $pid"
    kill -9 $pid 2>/dev/null || true
  fi
done
sleep 1

# 后端
echo "[dev.sh] 启动后端 (uvicorn 8000) ..."
cd "$ROOT/backend"
nohup "$VENV" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$LOG_DIR/backend.pid"

# 前端
echo "[dev.sh] 启动前端 (vite 5173) ..."
cd "$ROOT/frontend"
nohup npm run dev -- --host 127.0.0.1 --port 5173 \
  > "$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$LOG_DIR/frontend.pid"

sleep 3
echo ""
echo "----- 状态 -----"
for port in 8000 5173; do
  if lsof -i:$port >/dev/null 2>&1; then
    echo "  ✓ :$port 已就绪"
  else
    echo "  ✗ :$port 未就绪（查看 $LOG_DIR/{backend,frontend}.log）"
  fi
done
echo ""
echo "后端:  http://127.0.0.1:8000  ·  日志: $LOG_DIR/backend.log  ·  PID: $(cat $LOG_DIR/backend.pid)"
echo "前端:  http://127.0.0.1:5173  ·  日志: $LOG_DIR/frontend.log  ·  PID: $(cat $LOG_DIR/frontend.pid)"
echo ""
echo "停止:  kill \$(cat $LOG_DIR/backend.pid $LOG_DIR/frontend.pid)"

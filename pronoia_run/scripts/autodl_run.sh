#!/usr/bin/env bash
# ============================================================
# AutoDL 一键启动 Team full 推理（断点续跑，已有 957 条会自动跳过）
# 用法：
#   git clone https://github.com/vixuowis/Pronoia.git
#   cd Pronoia && git checkout pronoia-data-v3
#   bash pronoia_run/scripts/autodl_run.sh
# ============================================================
set -euo pipefail

# ---------- 自动定位仓库根目录 ----------
REPO=$(cd "$(dirname "$0")/../.." && pwd)
echo "[run] REPO=$REPO"

# ---------- 1) .env ----------
if [ ! -f "$REPO/.env" ]; then
  echo "[run] ❌ $REPO/.env 不存在！请先创建："
  echo '  cat > .env << EOF'
  echo '  ARK_API_URL=https://ark.cn-beijing.volces.com/api/coding/v3'
  echo '  ARK_API_KEY=你的密钥'
  echo '  ARK_MODEL=deepseek-v4-flash'
  echo '  EOF'
  exit 1
fi
set -a; source "$REPO/.env"; set +a
echo "[run] ARK_API_KEY=${ARK_API_KEY:0:8}..."

# ---------- 2) 依赖 ----------
pip install -q openai akshare python-dotenv yfinance pandas requests 2>&1 | tail -3

# ---------- 3) 路径 ----------
EVENTS="$REPO/pronoia_run/data_v3/events_enriched.jsonl"
OUT="$REPO/pronoia_run/data_v3/audit/research_cache_team.jsonl"
CKPT="$REPO/pronoia_run/team_traj_v3"
LOG="$REPO/pronoia_run/logs/team_batch.log"
mkdir -p "$(dirname "$OUT")" "$CKPT" "$(dirname "$LOG")"

# ---------- 4) 验证输入 ----------
LINES=$(wc -l < "$EVENTS")
echo "[run] 输入事件: $LINES 条"

DONE=0
[ -f "$OUT" ] && DONE=$(grep -c '"ok": true' "$OUT" 2>/dev/null || echo 0)
echo "[run] 已完成: $DONE 条 → 断点续跑剩余 $((LINES - DONE)) 条"

# ---------- 5) 启动 ----------
cd "$REPO/backend"
CONC=${CONCURRENCY:-32}
echo "[run] 启动 team_research_batch concurrency=$CONC"
echo "[run] 日志: tail -f $LOG"

nohup python3 "$REPO/backtesting/rlvr/scripts/team_research_batch.py" \
  --events "$EVENTS" \
  --out "$OUT" \
  --ckpt-dir "$CKPT" \
  --concurrency "$CONC" >> "$LOG" 2>&1 &

PID=$!
echo "[run] PID=$PID"
echo "[run] 看进度: tail -f $LOG | grep -E 'PROG|DONE|RESUME|PLAN'"
echo "[run] 进度脚本: bash $REPO/pronoia_run/scripts/progress.sh"

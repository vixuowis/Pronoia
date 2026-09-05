#!/usr/bin/env bash
# d5 启动包装：source .env → 启动 team_research_batch
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

set -a
if [ -f "$ROOT/.env" ]; then
  source "$ROOT/.env"
fi
set +a

LOG="$ROOT/pronoia_run/logs/team_batch.log"
mkdir -p "$(dirname "$LOG")"
: > "$LOG"

cd "$ROOT/backend"
nohup python3 "$ROOT/backtesting/rlvr/scripts/team_research_batch.py" \
  --events "$ROOT/pronoia_run/data_v3/events_enriched.jsonl" \
  --out "$ROOT/pronoia_run/data_v3/audit/research_cache_team.jsonl" \
  --ckpt-dir "$ROOT/pronoia_run/team_traj_v3" \
  --concurrency 32 >> "$LOG" 2>&1 &
echo $!

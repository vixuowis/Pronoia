#!/usr/bin/env bash
# d5 启动包装：source .env → 启动 team_research_batch
set -a
if [ -f /workspace/.env ]; then
  source /workspace/.env
fi
set +a

LOG=/workspace/pronoia_run/logs/team_batch.log
: > "$LOG"

cd /workspace/backend
nohup python3 /workspace/backtesting/rlvr/scripts/team_research_batch.py \
  --events /workspace/pronoia_run/data_v3/events_enriched.jsonl \
  --out /workspace/pronoia_run/data_v3/audit/research_cache_team.jsonl \
  --ckpt-dir /workspace/pronoia_run/team_traj_v3 \
  --concurrency 32 >> "$LOG" 2>&1 &
echo $!

#!/bin/bash
# run_team_forward.sh — 跑 Team 全管线生成 research_cache + trajectory
set -a
source /root/Pronoia/.env
set +a
export FEVER_BT_FAST=1   # 3 专家白名单 + 跳过 hypothesis/verify
export PYTHONPATH="/root/Pronoia/backend:/root/Pronoia:${PYTHONPATH:-}"

cd /root/Pronoia/backend

exec /root/miniconda3/bin/python /root/Pronoia/backtesting/rlvr/scripts/team_research_batch.py \
    --events /root/Pronoia/pronoia_run/forward_test/events_forward.jsonl \
    --out /root/Pronoia/pronoia_run/forward_test/research_cache_team.jsonl \
    --ckpt-dir /root/Pronoia/pronoia_run/team_traj_forward \
    --concurrency 8 \
    --timeout 1800 \
    "$@"

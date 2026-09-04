#!/bin/bash
# Baseline (no research) claims generation for today's events
exec /root/miniconda3/bin/python /root/Pronoia/gen_forward_claims_research.py \
    --events /root/Pronoia/pronoia_run/today_test/events_today.jsonl \
    --research "" \
    --out /root/Pronoia/pronoia_run/today_test/claims_today_baseline.jsonl \
    --max-model-len 4096 \
    --temperature 0.95

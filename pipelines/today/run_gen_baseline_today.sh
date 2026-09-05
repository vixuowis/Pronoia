#!/bin/bash
# Baseline (no research) claims generation for today's events
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PYTHON:-python3}"

exec "$PY" "$ROOT/pipelines/forward_claims/gen_forward_claims.py" \
    --events "$ROOT/pronoia_run/today_test/events_today.jsonl" \
    --out "$ROOT/pronoia_run/today_test/claims_today_baseline.jsonl" \
    --max-model-len 4096 \
    --temperature 0.95

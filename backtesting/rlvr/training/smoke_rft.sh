#!/usr/bin/env bash
# smoke_rft.sh — Pronoia-RLVR RFT 单专家 smoke test（快速验证 pipeline 不报错）。
#
# 用法：
#   bash backtesting/rlvr/training/smoke_rft.sh cn_short
#   bash backtesting/rlvr/training/smoke_rft.sh ALL      # 跑所有 6 位专家 dry-run
#
# 说明：
#   · 默认 --dry-run（即使依赖齐全也不真正 train，只走数据+reward smoke test）；
#   · 要真实训练时，删去 --dry-run 并确保 pip install transformers datasets peft trl accelerate。
set -euo pipefail

EXPERT="${1:-cn_short}"
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"

EVENTS="${ROOT}/backtesting/rlvr/data/rlvr_train_v1_5000/events.jsonl"
LABELS="${ROOT}/backtesting/rlvr/data/rlvr_train_v1_5000/labels.jsonl"
OUT="${ROOT}/backtesting/rlvr/training/outputs/smoke_rft"

mkdir -p "${OUT}"
cd "${ROOT}"

echo "[SMOKE] workspace root = ${ROOT}"
echo "[SMOKE] expert       = ${EXPERT}"
echo "[SMOKE] events       = ${EVENTS}"
echo "[SMOKE] labels       = ${LABELS}"
echo "[SMOKE] out          = ${OUT}"
echo

python3 backtesting/rlvr/training/grpo_trainer.py \
    --mode step1 \
    --expert "${EXPERT}" \
    --events "${EVENTS}" \
    --labels "${LABELS}" \
    --out-dir "${OUT}" \
    --dry-run

echo
echo "[SMOKE OK] 产物目录：${OUT}"
ls -la "${OUT}" 2>/dev/null || true

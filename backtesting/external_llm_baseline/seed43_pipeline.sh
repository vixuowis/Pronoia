#!/bin/bash
# seed43_pipeline.sh — 多种子验证（WWW 论文 P0#3）：v6.2-vanilla seed=43
# 训练 → OOS 生成（t=0.6）→ 评估，与主实验完全同口径。
set -u
export PATH=/root/miniconda3/envs/unsloth/bin:$PATH
export UNSLOTH_VLLM_NO_FLASHINFER=1
export PAPV_VANILLA_REWARD=1          # v6.2-vanilla：关闭全部 v6.1 修正项

RUN=/root/Pronoia/pronoia_run
OUT=$RUN/papv_v62_seed43
ADAP=$OUT/papv_mixed
LOG=$RUN/v62_seed43_pipeline.log
PY=/root/miniconda3/envs/unsloth/bin/python

echo "[TRAIN] $(date) seed=43 vanilla 训练开始" >> $LOG
$PY /root/Pronoia/backtesting/rlvr/training/remote_scripts/papv_train_remote.py \
  --data-dir $RUN/data_v61_train \
  --out-dir $OUT \
  --use-vllm --use-unsloth --seed 43 \
  >> $LOG 2>&1
echo "[TRAIN-DONE] $(date) rc=$?" >> $LOG

if [ ! -f $ADAP/adapter_model.safetensors ]; then
  echo "[ERROR] 最终 LoRA 不存在: $ADAP" >> $LOG
  exit 1
fi
sleep 30

echo "[GEN] $(date) seed43 adapter t=0.6 生成" >> $LOG
$PY /root/Pronoia/gen_oos_v61.py \
  --side adapter --adapter $ADAP --batch 64 --temperature 0.6 \
  --out $RUN/oos_v62_seed43_t06_completions.jsonl >> $LOG 2>&1
echo "[GEN-DONE] $(date)" >> $LOG

cat $RUN/oos_v62_seed43_t06_completions.jsonl $RUN/oos_v61_base_t06_completions.jsonl \
  > $RUN/oos_v62_seed43_full_t06.jsonl
echo "[EVAL] $(date) 评估开始" >> $LOG
$PY /root/Pronoia/backtesting/rlvr/evaluation/eval_papv_suite.py \
  --data-dir $RUN/data_v61_test \
  --completions $RUN/oos_v62_seed43_full_t06.jsonl \
  --out $RUN/eval_papv_v62_seed43_t06_report.json >> $LOG 2>&1
echo "[ALL-DONE] $(date)" >> $LOG

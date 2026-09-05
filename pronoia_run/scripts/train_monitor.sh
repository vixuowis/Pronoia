#!/usr/bin/env bash
# train_monitor.sh — PAPV v4 后训练质量监控（远程 4090）
# 输出：进程状态 / reward 曲线（最近步 vs 前期均值）/ KL / 完成长度 / 数据采集进度
set -u
SSH="python3 /workspace/backtesting/rlvr/scripts/remote_ssh.py"
LOG=/root/pronoia/papv_v4_run1.log

echo "===== 1. 进程状态 ====="
$SSH "ps aux | grep -E 'papv_train_remote|team_research_batch' | grep -v grep | awk '{print \$2, \$3\"%cpu\", \$11, \$NF}' | head -5" --timeout 60

echo; echo "===== 2. 训练日志尾部 ====="
$SSH "tail -5 $LOG" --timeout 60

echo; echo "===== 3. Reward/质量指标（trainer_state 最近步） ====="
$SSH "bash -c 'CKPT=\$(ls -td /root/pronoia/papv_v4_run1/papv_mixed/checkpoint-* 2>/dev/null | head -1); if [ -n \"\$CKPT\" ] && [ -f \"\$CKPT/trainer_state.json\" ]; then /root/miniconda3/bin/python -c \"
import json,sys
st=json.load(open(\\\"\$CKPT/trainer_state.json\\\"))
hist=st[\\\"log_history\\\"]
keys=[\\\"loss\\\",\\\"reward\\\",\\\"kl\\\",\\\"completions/mean_terminated_length\\\",\\\"completions/clipped_ratio\\\"]
print(f\\\"step={st[\\\'global_step\\\']} / {st[\\\'max_steps\\\']}\\\")
n=len(hist)
if n>=10:
    early=[h for h in hist[:n//3] if \\\"reward\\\" in h]
    late=[h for h in hist[-n//3:] if \\\"reward\\\" in h]
    er=sum(h[\\\"reward\\\"] for h in early)/max(len(early),1)
    lr_=sum(h[\\\"reward\\\"] for h in late)/max(len(late),1)
    print(f\\\"reward 前段均值={er:.4f}  最近段均值={lr_:.4f}  Δ={lr_-er:+.4f}\\\")
for h in hist[-3:]:
    s=\\\" \\\".join(f\\\"{k}={h[k]:.4f}\\\" for k in keys if k in h)
    print(f\\\"step {h.get(\\\'step\\\')}: {s}\\\")
\"; else echo 尚无 checkpoint（前 50 步内）; fi'" --timeout 90

echo; echo "===== 4. 数据采集进度（v4 team cache） ====="
$SSH "wc -l /root/Pronoia/pronoia_run/data_v3/audit/research_cache_team_v4.jsonl; ls /root/Pronoia/pronoia_run/team_traj_v4 | wc -l; tail -1 /root/Pronoia/pronoia_run/logs/team_batch_v4.log | head -c 300" --timeout 60

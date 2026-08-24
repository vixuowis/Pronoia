#!/usr/bin/env python3
"""extract_metrics.py — 从 papv_v4_run1.log 提取逐步训练指标 → JSON。"""
import re
import json

log = open('/root/pronoia/papv_v4_run1.log', errors='replace').read()
rows = []
for line in log.split('\n'):
    if "'reward'" not in line or "'loss'" not in line:
        continue
    d = {}
    for k in ['loss', 'grad_norm', 'reward', 'reward_std', 'kl', 'epoch',
              'learning_rate', 'num_tokens',
              'completions/mean_terminated_length',
              'completions/clipped_ratio']:
        m = re.search(re.escape(k) + r"': ([-0-9.eE]+)", line)
        if m:
            d[k] = float(m.group(1))
    m = re.search(r"'step': (\d+)", line)
    if m:
        d['step'] = int(m.group(1))
    rows.append(d)

print(json.dumps(rows))

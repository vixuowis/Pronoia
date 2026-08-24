#!/usr/bin/env python3
"""model_claim_acc_v2.py — 增加 thr==0 方向类断言的同口径子集统计。"""
import json
import re
import sys
sys.path.insert(0, '/tmp')
exec(open('/tmp/model_claim_acc.py').read().split("total_ok = total_n = 0")[0])

total_ok = total_n = 0
d0_ok = d0_n = 0          # 模型阈值=0 的方向类断言
d0_car_ok = d0_car_n = 0
d0_ret_ok = d0_ret_n = 0
half = {'前半': [0, 0], '后半': [0, 0]}
half0 = {'前半': [0, 0], '后半': [0, 0]}
steps_sorted = sorted({r['step'] for r in rollouts})
mid = steps_sorted[len(steps_sorted) // 2] if steps_sorted else 0

for ro in rollouts:
    ev = find_event(ro['p'])
    if not ev:
        continue
    lab = labels.get(ev.get('event_id'))
    if not lab:
        continue
    claims = CLAIM_RE.findall(ro['c'])
    if not claims:
        continue
    for metric, op, thr, judge, conf in claims:
        try:
            conf = float(conf)
        except ValueError:
            continue
        v = lab.get(metric)
        if v is None:
            continue
        try:
            t = float(thr.rstrip('%'))
        except ValueError:
            continue
        if op == '>': prop = v > t
        elif op == '<': prop = v < t
        elif op == '>=': prop = v >= t
        else: prop = v <= t
        correct = (judge.upper() == 'TRUE') == prop
        total_ok += int(correct); total_n += 1
        h = '前半' if ro['step'] <= mid else '后半'
        half[h][0] += int(correct); half[h][1] += 1
        if t == 0.0:
            d0_ok += int(correct); d0_n += 1
            half0[h][0] += int(correct); half0[h][1] += 1
            if metric.startswith('car'):
                d0_car_ok += int(correct); d0_car_n += 1
            elif metric.startswith('ret'):
                d0_ret_ok += int(correct); d0_ret_n += 1

print(json.dumps({
    'all': [total_ok, total_n, round(total_ok / max(total_n, 1), 4)],
    '方向类(thr=0)': [d0_ok, d0_n, round(d0_ok / max(d0_n, 1), 4)],
    '方向类-car': [d0_car_ok, d0_car_n, round(d0_car_ok / max(d0_car_n, 1), 4)],
    '方向类-ret': [d0_ret_ok, d0_ret_n, round(d0_ret_ok / max(d0_ret_n, 1), 4)],
    '方向类-前半': [half0['前半'][0], half0['前半'][1], round(half0['前半'][0] / max(half0['前半'][1], 1), 4)],
    '方向类-后半': [half0['后半'][0], half0['后半'][1], round(half0['后半'][0] / max(half0['后半'][1], 1), 4)],
    '全部-前半': [half['前半'][0], half['前半'][1], round(half['前半'][0] / max(half['前半'][1], 1), 4)],
    '全部-后半': [half['后半'][0], half['后半'][1], round(half['后半'][0] / max(half['后半'][1], 1), 4)],
}, ensure_ascii=False, indent=1))

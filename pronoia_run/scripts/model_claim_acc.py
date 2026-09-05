#!/usr/bin/env python3
"""model_claim_acc.py — 训练日志 rollout claim vs GT 结算统计。"""
import json
import re

LOG = '/root/pronoia/papv_v4_run1.log'
LABELS = '/root/pronoia/data_v4/labels.jsonl'
EVENTS = '/root/pronoia/data_v4/events_enriched.jsonl'

# ---- 加载事件与标签 ----
labels = {}
for line in open(LABELS):
    r = json.loads(line)
    if r.get('event_id'):
        labels[r['event_id']] = r

sym_events = {}   # symbol -> [event dict]
for line in open(EVENTS):
    r = json.loads(line)
    sym = str(r.get('symbol') or '').strip()
    if sym:
        sym_events.setdefault(sym, []).append(r)

# ---- 解析日志表格 ----
txt = open(LOG, errors='replace').read()
blocks = re.split(r'╭──+ Step (\d+) ──+╮', txt)
rollouts = []
for i in range(1, len(blocks), 2):
    step = int(blocks[i]); body = blocks[i + 1]
    cur = None
    for line in body.split('\n'):
        if '│' not in line or line.count('│') != 6:
            continue
        parts = [p.strip() for p in line.split('│')]
        c1, c2, c3 = parts[2], parts[3], parts[4]
        if c3:  # reward 非空 → 新 rollout
            cur = {'step': step, 'p': c1, 'c': c2, 'r': c3}
            rollouts.append(cur)
        elif cur is not None:
            cur['p'] += c1
            cur['c'] += c2

print(f'parsed rollouts: {len(rollouts)}', file=__import__('sys').stderr)

CLAIM_RE = re.compile(
    r'CLAIM-\d+\s*[:：]\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|>|<)\s*(-?[\d.]+%?)'
    r'[^|]*\|\s*判断\s*[:：]\s*(TRUE|FALSE)\s*\|\s*置信度\s*[:：]\s*([\d.]+)',
    re.IGNORECASE)

def find_event(prompt):
    # CN 6位代码
    m = re.search(r'\b(\d{6})\b', prompt)
    sym = None
    if m:
        sym = m.group(1)
    else:
        # US ticker：形如 "Symbol: AAPL"
        m2 = re.search(r'Symbol[:：]\s*([A-Z]{1,6})\b', prompt)
        if m2:
            sym = m2.group(1)
    if not sym or sym not in sym_events:
        return None
    cands = sym_events[sym]
    if len(cands) == 1:
        return cands[0]
    # 标题前缀匹配
    tm = re.search(r'标题[：:]\s*([^\n]{4,30})', prompt)
    if tm:
        pref = tm.group(1).strip().rstrip('…').strip()
        hits = [e for e in cands if str(e.get('title') or '').startswith(pref[:10])]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return hits[0]
    return cands[0]

def settle(claims, lab):
    ok = n = 0
    by_fam = {}
    by_conf = {}
    for metric, op, thr, judge, conf in claims:
        v = lab.get(metric)
        try:
            conf = float(conf)
        except ValueError:
            continue
        if v is None:
            continue
        thr_s = thr.rstrip('%')
        try:
            t = float(thr_s)
        except ValueError:
            continue
        if op == '>':
            prop = v > t
        elif op == '<':
            prop = v < t
        elif op == '>=':
            prop = v >= t
        else:
            prop = v <= t
        correct = (judge.upper() == 'TRUE') == prop
        n += 1
        ok += int(correct)
        fam = metric.split('_t')[0]
        d = by_fam.setdefault(fam, [0, 0]); d[0] += int(correct); d[1] += 1
        cb = '>=0.75' if conf >= 0.75 else ('0.65-0.75' if conf >= 0.65 else '0.55-0.65' if conf >= 0.55 else '<0.55')
        d2 = by_conf.setdefault(cb, [0, 0]); d2[0] += int(correct); d2[1] += 1
    return ok, n, by_fam, by_conf

total_ok = total_n = 0
matched = 0
by_fam_all = {}
by_conf_all = {}
by_half = {'前半': [0, 0], '后半': [0, 0]}
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
    matched += 1
    ok, n, by_fam, by_conf = settle(claims, lab)
    total_ok += ok; total_n += n
    for k, v in by_fam.items():
        d = by_fam_all.setdefault(k, [0, 0]); d[0] += v[0]; d[1] += v[1]
    for k, v in by_conf.items():
        d = by_conf_all.setdefault(k, [0, 0]); d[0] += v[0]; d[1] += v[1]
    half = '前半' if ro['step'] <= mid else '后半'
    by_half[half][0] += ok; by_half[half][1] += n

out = {
    'rollouts_total': len(rollouts),
    'rollouts_matched': matched,
    'claims_settled': total_n,
    'claims_correct': total_ok,
    'accuracy': round(total_ok / max(total_n, 1), 4),
    'by_family': {k: [v[0], v[1], round(v[0] / max(v[1], 1), 4)] for k, v in by_fam_all.items()},
    'by_conf': {k: [v[0], v[1], round(v[0] / max(v[1], 1), 4)] for k, v in by_conf_all.items()},
    'by_half': {k: [v[0], v[1], round(v[0] / max(v[1], 1), 4)] for k, v in by_half.items()},
    'mid_step': mid,
}
print(json.dumps(out, ensure_ascii=False, indent=1))

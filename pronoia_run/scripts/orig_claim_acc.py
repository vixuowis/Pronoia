#!/usr/bin/env python3
"""orig_claim_acc.py — 原始 Team v4 horizons 断言 vs GT 结算统计。"""
import json
import sys

CACHE = '/root/Pronoia/pronoia_run/data_v3/audit/research_cache_team_v4.jsonl'
LABELS = '/root/pronoia/data_v4/labels.jsonl'

# labels: event_id -> dict
labels = {}
for line in open(LABELS):
    r = json.loads(line)
    eid = r.get('event_id') or r.get('id')
    if eid:
        labels[eid] = r

METRICS = ['ret_t3', 'ret_t7', 'ret_t15', 'ret_t30', 'ret_t60',
           'car_t3', 'car_t7', 'car_t15', 'car_t30', 'car_t60']

stats = {
    'total_events': 0, 'joined': 0,
    'n_claims': 0, 'n_neutral': 0, 'n_settled': 0, 'n_correct': 0,
    'by_family': {}, 'by_conf': {}, 'by_metric': {}, 'by_dir': {},
}

def bucket(c):
    if c is None:
        return 'none'
    if c < 0.55: return 'c<0.55'
    if c < 0.65: return '0.55-0.65'
    if c < 0.75: return '0.65-0.75'
    return '>=0.75'

for line in open(CACHE):
    try:
        r = json.loads(line)
    except Exception:
        continue
    stats['total_events'] += 1
    eid = r.get('event_id')
    lab = labels.get(eid)
    if lab is None:
        continue
    stats['joined'] += 1
    hz = r.get('horizons') or {}
    for m in METRICS:
        h = hz.get(m)
        if not h:
            continue
        stats['n_claims'] += 1
        d = str(h.get('direction') or 'neutral').lower()
        conf = h.get('confidence')
        fam = 'ret' if m.startswith('ret') else 'car'
        key_b = f'{fam}|{d}'
        if d == 'neutral':
            stats['n_neutral'] += 1
            stats['by_dir'][key_b] = stats['by_dir'].get(key_b, 0) + 1
            continue
        v = lab.get(m)
        if v is None:
            continue
        stats['n_settled'] += 1
        # direction up => 命题 v>0；down => v<0
        prop_true = (v > 0) if d == 'up' else (v < 0)
        correct = bool(prop_true)
        if correct:
            stats['n_correct'] += 1
        for tgt, key, ok in [('by_family', fam, correct), ('by_metric', m, correct), ('by_conf', bucket(conf), correct)]:
            d0 = stats[tgt].setdefault(key, [0, 0])
            d0[0] += int(ok)
            d0[1] += 1
        # 方向级结算计数
        stats['by_dir'][f'{fam}|{d}|ok'] = stats['by_dir'].get(f'{fam}|{d}|ok', 0) + int(correct)
        stats['by_dir'][f'{fam}|{d}|n'] = stats['by_dir'].get(f'{fam}|{d}|n', 0) + 1

out = {
    'total_events': stats['total_events'],
    'joined': stats['joined'],
    'n_claims': stats['n_claims'],
    'n_neutral': stats['n_neutral'],
    'n_settled': stats['n_settled'],
    'n_correct': stats['n_correct'],
    'accuracy': round(stats['n_correct'] / max(stats['n_settled'], 1), 4),
    'neutral_rate': round(stats['n_neutral'] / max(stats['n_claims'], 1), 4),
    'by_family': {k: [v[0], v[1], round(v[0] / max(v[1], 1), 4)] for k, v in stats['by_family'].items()},
    'by_metric': {k: [v[0], v[1], round(v[0] / max(v[1], 1), 4)] for k, v in stats['by_metric'].items()},
    'by_conf': {k: [v[0], v[1], round(v[0] / max(v[1], 1), 4)] for k, v in stats['by_conf'].items()},
    'by_dir': stats['by_dir'],
}
print(json.dumps(out, ensure_ascii=False, indent=1))

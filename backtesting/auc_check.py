#!/usr/bin/env python3
"""Clean AUC computation: O(n^2) pairwise + rank-based cross-check."""
import json

preds = {}
for line in open('/workspace/backtesting/preds_cn_us_1000_v1.jsonl'):
    d = json.loads(line); preds[d['event_id']] = d
labels = {}
for line in open('/workspace/backtesting/labels_cn_us_1000_v1.jsonl'):
    d = json.loads(line); labels[d['event_id']] = d

def valid(v): return v is not None and v != ''

def auc_pairwise(pairs):
    """Ground truth: count concordant/discordant/tied pairs."""
    n1 = sum(y for _, y in pairs); n0 = len(pairs) - n1
    if not n1 or not n0: return None
    num = 0.0
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    for a in pos:
        for b in neg:
            if a > b: num += 1
            elif a == b: num += 0.5
    return num / (n1 * n0)

def auc_rank(pairs):
    """Rank-based with proper tie handling (average ranks)."""
    n1 = sum(y for _, y in pairs); n0 = len(pairs) - n1
    if not n1 or not n0: return None
    sp = sorted(pairs)
    rank = [0.0] * len(sp)
    i = 0
    while i < len(sp):
        j = i
        while j < len(sp) and sp[j][0] == sp[i][0]: j += 1
        avg = (i + j - 1) / 2.0 + 1  # average of ranks i+1 .. j (1-based)
        for k in range(i, j): rank[k] = avg
        i = j
    s1 = sum(rank[k] for k in range(len(sp)) if sp[k][1] == 1)
    return (s1 - n1 * (n1 + 1) / 2) / (n1 * n0)

def build_pairs(hz, ids=None):
    ids = ids or preds.keys()
    pairs = []
    for e in ids:
        p = preds[e]; lb = labels.get(e)
        if not lb or not valid(lb.get(f'label_{hz}')): continue
        gt = lb[f'label_{hz}']
        if gt == 'neutral' or p['pred_direction'] == 'neutral': continue
        pairs.append((p['confidence'] if p['pred_direction'] == 'up' else -p['confidence'], 1 if gt == 'up' else 0))
    return pairs

def fmt(hz, ids=None):
    pairs = build_pairs(hz, ids)
    a1 = auc_pairwise(pairs); a2 = auc_rank(pairs)
    if a1 is None: return 'n/a'
    assert abs(a1 - a2) < 1e-9, f'MISMATCH {hz}: {a1} vs {a2}'
    return f'{a1:.3f} (n={len(pairs)})'

print('== per-horizon AUC (valid labels, both non-neutral) ==')
for hz in ['t1','t3','t5','t7','t15','t30','t60','avg_short','avg_mid','avg_long','avg_all']:
    print(f'{hz}: {fmt(hz)}')

print('\n== per market x horizon AUC ==')
for hz in ['t3','t7','t15','t30','t60','avg_all']:
    for mk in ['CN','US']:
        ids = [e for e, l in labels.items() if l.get('market') == mk]
        print(f'{hz} {mk}: {fmt(hz, ids)}')

print('\n== per event-type AUC (t3 / avg_all) ==')
ets = sorted(set(l.get('event_type_l2') for l in labels.values()))
for et in ets:
    ids = [e for e, l in labels.items() if l.get('event_type_l2') == et]
    print(f'{et}: t3={fmt("t3", ids)} | avg_all={fmt("avg_all", ids)}')

print('\n== per market x etype AUC (t3 / avg_all) ==')
for mk in ['CN','US']:
    for et in ets:
        ids = [e for e, l in labels.items() if l.get('market') == mk and l.get('event_type_l2') == et]
        if not ids: continue
        print(f'{mk}·{et}: t3={fmt("t3", ids)} | avg_all={fmt("avg_all", ids)}')

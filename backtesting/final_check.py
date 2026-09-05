#!/usr/bin/env python3
"""Final verification: t60 market corrected, consensus66, Wilson LBs."""
import json, math

preds = {}
for line in open('/workspace/backtesting/preds_cn_us_1000_v1.jsonl'):
    d = json.loads(line); preds[d['event_id']] = d
labels = {}
for line in open('/workspace/backtesting/labels_cn_us_1000_v1.jsonl'):
    d = json.loads(line); labels[d['event_id']] = d

def valid(v): return v is not None and v != ''

def stats(hz, ids=None):
    ids = ids or preds.keys()
    ns = k_s = n_nn = k_nn = n_len = k_len = 0
    for eid in ids:
        p = preds[eid]; lb = labels.get(eid)
        if not lb or not valid(lb.get(f'label_{hz}')): continue
        gt = lb[f'label_{hz}']; pr = p['pred_direction']
        ns += 1
        if pr == gt: k_s += 1
        if pr != 'neutral':
            n_nn += 1
            if pr == gt: k_nn += 1
        if pr != 'neutral' and gt != 'neutral':
            n_len += 1
            if pr == gt: k_len += 1
    return ns, k_s, n_nn, k_nn, n_len, k_len

print('== t60 per market (valid labels only) ==')
for mk in ['CN', 'US']:
    ids = [e for e, l in labels.items() if l.get('market') == mk]
    ns, k_s, n_nn, k_nn, n_len, k_len = stats('t60', ids)
    print(f'{mk}: strict {k_s}/{ns}={k_s/ns*100:.1f}% | NN {k_nn}/{n_nn}={k_nn/n_nn*100:.1f}% | lenient {k_len}/{n_len}={k_len/n_len*100:.1f}%')

print('\n== t30 per market (sanity) ==')
for mk in ['CN', 'US']:
    ids = [e for e, l in labels.items() if l.get('market') == mk]
    ns, k_s, n_nn, k_nn, n_len, k_len = stats('t30', ids)
    print(f'{mk}: strict {k_s}/{ns}={k_s/ns*100:.1f}% | lenient {k_len}/{n_len}={k_len/n_len*100:.1f}%')

print('\n== consensus66 ==')
ns, k_s, n_nn, k_nn, n_len, k_len = stats('consensus66')
print(f'consensus66: strict {k_s}/{ns}={k_s/ns*100:.1f}% | NN {k_nn}/{n_nn}={k_nn/n_nn*100:.1f}% | lenient {k_len}/{n_len}={k_len/n_len*100:.1f}%')

print('\n== Wilson LBs ==')
def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (c - h) * 100
for k, n, lab in [(393,1000,'t3 strict'), (314,1000,'avg_all strict'), (239,989,'t60 strict'),
                  (249,397,'t3 NN'), (269,580,'company t3 strict'), (124,420,'macro t3 strict'),
                  (219,580,'company avg_all strict'), (95,420,'macro avg_all strict')]:
    print(f'{lab}: {k}/{n}, Wilson LB = {wilson(k,n):.1f}%')

print('\n== 公司类 vs 宏观类 (t3 / avg_all) ==')
COMPANY = ['并购/分拆/再融资', '财报超预期/不及预期', '公司指引上调/下调']
MACRO = ['政策利率调整', '增长/就业数据意外', '通胀数据意外']
for name, group in [('公司类', COMPANY), ('宏观类', MACRO)]:
    ids = [e for e, l in labels.items() if l.get('event_type_l2') in group]
    for hz in ['t3', 'avg_all']:
        ns, k_s, n_nn, k_nn, n_len, k_len = stats(hz, ids)
        print(f'{name} {hz}: strict {k_s}/{ns}={k_s/ns*100:.1f}% | NN {k_nn}/{n_nn}={k_nn/n_nn*100:.1f}% | lenient {k_len}/{n_len}={k_len/n_len*100:.1f}%')

print('\n== 出手率 per market / per etype ==')
for mk in ['CN', 'US']:
    ids = [e for e, l in labels.items() if l.get('market') == mk]
    nn = sum(1 for e in ids if preds[e]['pred_direction'] != 'neutral')
    print(f'{mk}: 出手 {nn}/{len(ids)} = {nn/len(ids)*100:.1f}%')

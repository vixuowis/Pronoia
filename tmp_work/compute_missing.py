#!/usr/bin/env python3
"""Compute all corrected AUC values + confusion matrices + aggregates for doc rewrite."""
import json, math, os

preds = {}
for line in open('/workspace/backtesting/preds_cn_us_1000_v1.jsonl'):
    d = json.loads(line); preds[d['event_id']] = d
labels = {}
for line in open('/workspace/backtesting/labels_cn_us_1000_v1.jsonl'):
    d = json.loads(line); labels[d['event_id']] = d

def valid(v): return v is not None and v != ''

def signed_conf(p):
    return p['confidence'] if p['pred_direction'] == 'up' else (-p['confidence'] if p['pred_direction'] == 'down' else 0.0)

def auc_pairwise(pairs):
    n1 = sum(y for _, y in pairs); n0 = len(pairs) - n1
    if not n1 or not n0: return None
    num = 0.0
    pos = [s for s, y in pairs if y == 1]; neg = [s for s, y in pairs if y == 0]
    for a in pos:
        for b in neg:
            if a > b: num += 1
            elif a == b: num += 0.5
    return num / (n1 * n0)

def auc(hz, ids=None):
    """AUC up-vs-down on samples where BOTH pred and GT non-neutral."""
    ids = ids or preds.keys()
    pairs = []
    for eid in ids:
        p = preds[eid]; lb = labels.get(eid)
        if not lb or not valid(lb.get(f'label_{hz}')): continue
        gt = lb[f'label_{hz}']; pr = p['pred_direction']
        if pr == 'neutral' or gt == 'neutral': continue
        pairs.append((signed_conf(p), 1 if gt == 'up' else 0))
    if len(pairs) < 2: return None, len(pairs)
    return auc_pairwise(pairs), len(pairs)

HZ_ALL = ['t1','t3','t5','t7','t15','t30','t60','avg_short','avg_mid','avg_long','avg_all']
HZ_MAIN = ['t3','t7','t15','t30','t60','avg_all']

print('== AUC per market x horizon (both non-neutral) ==')
for mk in ['CN','US']:
    ids = [e for e,l in labels.items() if l.get('market')==mk]
    for hz in HZ_MAIN:
        a, n = auc(hz, ids)
        print(f'{mk} {hz}: AUC={a:.3f} (n={n})' if a else f'{mk} {hz}: n/a (n={n})')

print('\n== AUC per event type x (t3, avg_all) ==')
ets = sorted(set(l.get('event_type_l2') for l in labels.values()))
for et in ets:
    ids = [e for e,l in labels.items() if l.get('event_type_l2')==et]
    a3, n3 = auc('t3', ids); aa, na = auc('avg_all', ids)
    s3 = f'AUC={a3:.3f} (n={n3})' if a3 else f'n/a (n={n3})'
    sa = f'AUC={aa:.3f} (n={na})' if aa else f'n/a (n={na})'
    print(f'{et}: t3 {s3} | avg_all {sa}')

print('\n== AUC per market x event type (t3, avg_all) ==')
for mk in ['CN','US']:
    for et in ets:
        ids = [e for e,l in labels.items() if l.get('market')==mk and l.get('event_type_l2')==et]
        a3, n3 = auc('t3', ids); aa, na = auc('avg_all', ids)
        s3 = f'{a3:.3f}({n3})' if a3 else f'n/a({n3})'
        sa = f'{aa:.3f}({na})' if aa else f'n/a({na})'
        print(f'{mk}·{et}: t3 {s3} | avg_all {sa}')

print('\n== 公司类 vs 宏观类 AUC ==')
COMPANY = ['并购/分拆/再融资','财报超预期/不及预期','公司指引上调/下调']
MACRO = ['政策利率调整','增长/就业数据意外','通胀数据意外']
for name, group in [('公司类',COMPANY),('宏观类',MACRO)]:
    ids = [e for e,l in labels.items() if l.get('event_type_l2') in group]
    for hz in ['t3','avg_all']:
        a, n = auc(hz, ids)
        print(f'{name} {hz}: AUC={a:.3f} (n={n})' if a else f'{name} {hz}: n/a (n={n})')

print('\n== 公司类-only overall (t3/avg_all strict & AUC), 580 条 ==')
ids = [e for e,l in labels.items() if l.get('event_type_l2') in COMPANY]
for hz in ['t3','avg_all']:
    ns=k=0
    for eid in ids:
        p=preds[eid]; lb=labels[eid]
        if not valid(lb.get(f'label_{hz}')): continue
        ns+=1; k += (p['pred_direction']==lb[f'label_{hz}'])
    a,n = auc(hz, ids)
    print(f'company-only {hz}: strict {k}/{ns}={k/ns*100:.1f}% | AUC={a:.3f}(n={n})')

print('\n== Confusion matrices (t3, avg_all) ==')
for hz in ['t3','avg_all']:
    cm = {(a,b):0 for a in ['up','neutral','down'] for b in ['up','neutral','down']}
    for eid, p in preds.items():
        lb = labels.get(eid)
        if not lb or not valid(lb.get(f'label_{hz}')): continue
        cm[(p['pred_direction'], lb[f'label_{hz}'])] += 1
    print(f'--- {hz} (pred\\gt) ---')
    print(f"gt:      up={sum(cm[(a,'up')] for a in ['up','neutral','down'])}, neutral={sum(cm[(a,'neutral')] for a in ['up','neutral','down'])}, down={sum(cm[(a,'down')] for a in ['up','neutral','down'])}")
    for a in ['up','neutral','down']:
        print(f"pred {a:7s}: up={cm[(a,'up')]:4d}, neutral={cm[(a,'neutral')]:4d}, down={cm[(a,'down')]:4d}  (row={sum(cm[(a,b)] for b in ['up','neutral','down'])})")

print('\n== null car_t60 count ==')
n_null = sum(1 for l in labels.values() if not valid(l.get('label_t60')))
print(f'label_t60 null: {n_null}')
n_null_cn = sum(1 for l in labels.values() if l.get('market')=='CN' and not valid(l.get('label_t60')))
print(f'  of which CN: {n_null_cn}')

print('\n== ckpt files ==')
d = '/workspace/backtesting/_trajectory_ckpt_tf_cn_us_1000_v1'
files = os.listdir(d)
print(f'ckpt files: {len(files)}; json: {sum(1 for f in files if f.endswith(".json"))}')

print('\n== F1 avg_all per class verify ==')
from collections import Counter
for hz in ['t3','avg_all']:
    tp=Counter(); fp=Counter(); fn=Counter()
    for eid,p in preds.items():
        lb = labels.get(eid)
        if not lb or not valid(lb.get(f'label_{hz}')): continue
        gt = lb[f'label_{hz}']; pr = p['pred_direction']
        for c in ['up','neutral','down']:
            if pr==c and gt==c: tp[c]+=1
            elif pr==c and gt!=c: fp[c]+=1
            elif pr!=c and gt==c: fn[c]+=1
    f1s=[]
    for c in ['up','neutral','down']:
        P = tp[c]/(tp[c]+fp[c]) if tp[c]+fp[c] else 0
        R = tp[c]/(tp[c]+fn[c]) if tp[c]+fn[c] else 0
        F = 2*P*R/(P+R) if P+R else 0
        f1s.append(F)
        print(f'{hz} {c}: P={P*100:.1f}% R={R*100:.1f}% F1={F:.3f} (TP={tp[c]} FP={fp[c]} FN={fn[c]})')
    print(f'{hz} macro F1 = {sum(f1s)/3:.3f}')

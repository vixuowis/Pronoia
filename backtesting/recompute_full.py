#!/usr/bin/env python3
"""统一口径全量重算。口径定义：
- Strict ACC: pred_direction == label_hx（含 neutral==neutral 判对），分母 = 全部有标签样本
- 出手率: pred != neutral 占比
- 出手 ACC (NN Pred ACC): pred != neutral 的样本中 pred == label（GT 为 neutral 即错）
- Lenient ACC: pred 与 GT 均非 neutral 时 pred == GT
- AUC: pred 与 GT 均非 neutral 的样本上，score = +conf(pred=up)/-conf(pred=down)，up vs down 二分类
"""
import json, math
from collections import Counter

BASE = "/workspace/backtesting"
preds = {}
for line in open(f"{BASE}/preds_cn_us_1000_v1.jsonl"):
    d = json.loads(line); preds[d["event_id"]] = d
labels = {}
for line in open(f"{BASE}/labels_cn_us_1000_v1.jsonl"):
    d = json.loads(line); labels[d["event_id"]] = d

HZ = ["t1","t3","t5","t7","t15","t30","t60","avg_short","avg_mid","avg_long","avg_all"]

def stats(hz, ids=None):
    ids = ids or preds.keys()
    ns=k_s=k_nn=n_nn=n_len=k_len=n_gtneu=0
    for eid in ids:
        p = preds[eid]; lb = labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None: continue
        gt = lb[f"label_{hz}"]; pr = p["pred_direction"]
        ns += 1
        if pr == gt: k_s += 1
        if pr != "neutral":
            n_nn += 1
            if pr == gt: k_nn += 1
        if pr != "neutral" and gt != "neutral":
            n_len += 1
            if pr == gt: k_len += 1
        if gt == "neutral": n_gtneu += 1
    return dict(n=ns, k_strict=k_s, n_nn=n_nn, k_nn=k_nn, n_len=n_len, k_len=k_len, n_gtneu=n_gtneu)

def pct(k, n): return f"{k}/{n} = {k/n*100:.1f}%" if n else "-"

print("### 1. Per-horizon")
for hz in HZ:
    s = stats(hz)
    print(f"{hz:10s} strict {pct(s['k_strict'],s['n'])} | NN-pred-ACC {pct(s['k_nn'],s['n_nn'])} | lenient {pct(s['k_len'],s['n_len'])} | GT-neutral {s['n_gtneu']}")

print("\n### 2. Per-market x horizon (strict | lenient)")
for hz in ["t3","t7","t15","avg_all","t60"]:
    for mk in ["CN","US"]:
        ids = [e for e,l in labels.items() if l.get("market")==mk]
        s = stats(hz, ids)
        print(f"{hz:8s} {mk}: strict {pct(s['k_strict'],s['n'])} | lenient {pct(s['k_len'],s['n_len'])} | GT-neutral {s['n_gtneu']}/{s['n']}")

print("\n### 3. Per-event-type (t3 & avg_all): strict | NN | lenient | pred-neutral-ratio")
ets = sorted(set(l.get("event_type_l2") for l in labels.values()))
for et in ets:
    ids = [e for e,l in labels.items() if l.get("event_type_l2")==et]
    s3 = stats("t3", ids); sa = stats("avg_all", ids)
    neu = sum(1 for e in ids if preds[e]["pred_direction"]=="neutral")
    print(f"{et}: n={len(ids)} predNeu={neu/len(ids)*100:.0f}%")
    print(f"   t3: strict {pct(s3['k_strict'],s3['n'])} | NN {pct(s3['k_nn'],s3['n_nn'])} | lenient {pct(s3['k_len'],s3['n_len'])} | GTneu {s3['n_gtneu']}")
    print(f"   avg_all: strict {pct(sa['k_strict'],sa['n'])} | NN {pct(sa['k_nn'],sa['n_nn'])} | lenient {pct(sa['k_len'],sa['n_len'])} | GTneu {sa['n_gtneu']}")

print("\n### 3b. 公司类 vs 宏观类 聚合")
COMPANY = ["并购/分拆/再融资","财报超预期/不及预期","公司指引上调/下调"]
MACRO = ["政策利率调整","增长/就业数据意外","通胀数据意外"]
for name, group in [("公司类(指引/并购/财报)", COMPANY), ("宏观类(利率/就业/通胀)", MACRO)]:
    ids = [e for e,l in labels.items() if l.get("event_type_l2") in group]
    s3 = stats("t3", ids); sa = stats("avg_all", ids)
    print(f"{name} n={len(ids)}: t3 strict {pct(s3['k_strict'],s3['n'])}, avg_all strict {pct(sa['k_strict'],sa['n'])}, t3 lenient {pct(s3['k_len'],s3['n_len'])}")

print("\n### 4. Per market x event-type (strict t3 / avg_all)")
for mk in ["CN","US"]:
    for et in ets:
        ids = [e for e,l in labels.items() if l.get("market")==mk and l.get("event_type_l2")==et]
        if not ids: continue
        s3 = stats("t3", ids); sa = stats("avg_all", ids)
        print(f"{mk}·{et}: n={len(ids)} t3-strict {pct(s3['k_strict'],s3['n'])} | avg_all-strict {pct(sa['k_strict'],sa['n'])}")

print("\n### 5. CAR buckets (|car_t3| & |car_avg_all|)")
BUCKETS = [(0,0.005,"<0.5% XSMALL"),(0.005,0.01,"0.5-1% SMALL"),(0.01,0.03,"1-3% MED"),(0.03,0.05,"3-5% LARGE"),(0.05,0.10,"5-10% XL"),(0.10,99,"≥10% XXL")]
for hz in ["t3","avg_all"]:
    print(f"--- |car_{hz}| buckets ---")
    for lo,hi,name in BUCKETS:
        ids = [e for e,l in labels.items() if l.get(f"car_{hz}") is not None and lo <= abs(l[f"car_{hz}"]) < hi]
        s = stats(hz, ids)
        # lenient on this bucket + 出手ACC
        print(f"{name:14s} n={len(ids):4d} strict {pct(s['k_strict'],s['n'])} | lenient {pct(s['k_len'],s['n_len'])} | NN {pct(s['k_nn'],s['n_nn'])}")

print("\n### 6. Threshold sweep (t3 & avg_all)")
for hz in ["t3","avg_all"]:
    print(f"--- conf sweep on {hz} ---")
    for th in [0.50,0.55,0.60,0.65,0.70,0.75,0.80]:
        ids = [e for e,p in preds.items() if p["pred_direction"]!="neutral" and p["confidence"]>=th]
        s = stats(hz, ids)
        print(f"conf>={th:.2f}: cover {len(ids)} ({len(ids)/10:.1f}%) | NN-ACC {pct(s['k_nn'],s['n_nn'])} | lenient {pct(s['k_len'],s['n_len'])}")

print("\n### 7. AUC per horizon (signed conf, both non-neutral)")
def auc(pairs):
    n1=sum(y for _,y in pairs); n0=len(pairs)-n1
    if not n1 or not n0: return None
    sp=sorted(pairs); rank={}; r=1; i=0
    while i<len(sp):
        j=i
        while j<len(sp) and sp[j][0]==sp[i][0]: j+=1
        ar=(r+r+j-i-1)/2
        for k in range(i,j): rank[id(sp[k])]=ar
        r+=j-i; i=j
    s1=sum(rank[id(x)] for x in pairs if x[1]==1)
    return (s1-n1*(n1+1)/2)/(n1*n0)
for hz in HZ:
    pairs=[]
    for eid,p in preds.items():
        lb=labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None: continue
        gt=lb[f"label_{hz}"]
        if gt=="neutral" or p["pred_direction"]=="neutral": continue
        pairs.append((p["confidence"] if p["pred_direction"]=="up" else -p["confidence"], 1 if gt=="up" else 0))
    a=auc(pairs)
    print(f"{hz:10s} AUC={a:.3f} (n={len(pairs)})" if a else f"{hz:10s} n/a")

print("\n### 7b. AUC per market (t3/avg_all/t60)")
for hz in ["t3","avg_all","t60"]:
    for mk in ["CN","US"]:
        pairs=[]
        for eid,p in preds.items():
            lb=labels.get(eid)
            if not lb or lb.get("market")!=mk or lb.get(f"label_{hz}") is None: continue
            gt=lb[f"label_{hz}"]
            if gt=="neutral" or p["pred_direction"]=="neutral": continue
            pairs.append((p["confidence"] if p["pred_direction"]=="up" else -p["confidence"], 1 if gt=="up" else 0))
        a=auc(pairs)
        print(f"{hz:8s} {mk}: AUC={a:.3f} (n={len(pairs)})" if a else f"{hz:8s} {mk}: n/a")

print("\n### 7c. AUC per event-type (t3)")
for et in ets:
    pairs=[]
    for eid,p in preds.items():
        lb=labels.get(eid)
        if not lb or lb.get("event_type_l2")!=et or lb.get("label_t3") is None: continue
        gt=lb["label_t3"]
        if gt=="neutral" or p["pred_direction"]=="neutral": continue
        pairs.append((p["confidence"] if p["pred_direction"]=="up" else -p["confidence"], 1 if gt=="up" else 0))
    a=auc(pairs)
    print(f"{et}: AUC={a:.3f} (n={len(pairs)})" if a else f"{et}: n/a")

print("\n### 8. Wilson LB for key strict numbers")
def wilson(k,n,z=1.96):
    if n==0: return 0
    p=k/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return c-h
for k,n,lab in [(393,1000,"t3 strict"),(314,1000,"avg_all strict"),(239,1000,"t60 strict"),(249,397,"t3 NN-ACC")]:
    print(f"{lab}: {k}/{n}, Wilson LB = {wilson(k,n)*100:.1f}%")

print("\n### 9. F1 per class (t3 & avg_all)")
def f1_detail(hz):
    tp=Counter(); fp=Counter(); fn=Counter()
    for eid,p in preds.items():
        lb=labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None: continue
        y,yh=lb[f"label_{hz}"],p["pred_direction"]
        if y==yh: tp[y]+=1
        else: fp[yh]+=1; fn[y]+=1
    out=[]
    for c in ["up","down","neutral"]:
        pr=tp[c]/(tp[c]+fp[c]) if tp[c]+fp[c] else 0
        rc=tp[c]/(tp[c]+fn[c]) if tp[c]+fn[c] else 0
        f1=2*pr*rc/(pr+rc) if pr+rc else 0
        out.append(f"{c}: P={pr:.3f} R={rc:.3f} F1={f1:.3f}")
    macro=sum(2*(tp[c]/(tp[c]+fp[c]) if tp[c]+fp[c] else 0)*(tp[c]/(tp[c]+fn[c]) if tp[c]+fn[c] else 0)/((tp[c]/(tp[c]+fp[c]) if tp[c]+fp[c] else 0)+(tp[c]/(tp[c]+fn[c]) if tp[c]+fn[c] else 0)+1e-12) if (tp[c]+fp[c]) and (tp[c]+fn[c]) else 0 for c in ["up","down","neutral"])/3
    return out, macro
for hz in ["t3","avg_all"]:
    out,macro=f1_detail(hz)
    print(f"{hz}: macro={macro:.3f} | " + " | ".join(out))

print("\n### 10. Confusion (t3 & avg_all) - verified")
for hz in ["t3","avg_all"]:
    cm=Counter()
    for eid,p in preds.items():
        lb=labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None: continue
        cm[(p["pred_direction"],lb[f"label_{hz}"])]+=1
    print(f"{hz}: pred\\gt up={sum(v for (a,b),v in cm.items() if b=='up')}, neutral={sum(v for (a,b),v in cm.items() if b=='neutral')}, down={sum(v for (a,b),v in cm.items() if b=='down')}")

print("\n### 11. consensus66 & Spearman")
s=stats("consensus66") if any("label_consensus66" in l for l in [labels[list(labels)[0]]]) else None
key = list(labels.keys())[0]
print("label keys sample:", [k for k in labels[key].keys() if "consensus" in k or "label" in k][:20])
def spearman(xs,ys):
    def rank(v):
        srt=sorted(range(len(v)),key=lambda i:v[i]); r=[0.]*len(v); i=0
        while i<len(srt):
            j=i
            while j<len(srt) and v[srt[j]]==v[srt[i]]: j+=1
            for k in range(i,j): r[srt[k]]=(i+j+1)/2
            i=j
        return r
    rx,ry=rank(xs),rank(ys)
    mx,my=sum(rx)/len(rx),sum(ry)/len(ry)
    num=sum((a-mx)*(b-my) for a,b in zip(rx,ry))
    den=math.sqrt(sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry))
    return num/den if den else 0
for hz in ["t1","t3","t7","t15","t30","t60","avg_all"]:
    xs,ys=[],[]
    for eid,p in preds.items():
        lb=labels.get(eid)
        if not lb or lb.get(f"car_{hz}") is None: continue
        xs.append(p["confidence"]); ys.append(abs(lb[f"car_{hz}"]))
    print(f"spearman {hz}: rho={spearman(xs,ys):.3f} (n={len(xs)})")

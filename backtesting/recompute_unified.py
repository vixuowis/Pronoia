#!/usr/bin/env python3
"""统一口径重算：Strict ACC = pred_direction == label_tN（含 neutral==neutral 判对）
Lenient ACC = 双方都非 neutral 时 pred == label"""
import json, math
from collections import defaultdict, Counter

BASE = "/workspace/backtesting"
preds = {}
with open(f"{BASE}/preds_cn_us_1000_v1.jsonl") as f:
    for line in f:
        d = json.loads(line)
        preds[d["event_id"]] = d

labels = {}
with open(f"{BASE}/labels_cn_us_1000_v1.jsonl") as f:
    for line in f:
        d = json.loads(line)
        labels[d["event_id"]] = d

events = {}
with open(f"{BASE}/events_cn_us_1000_v1.jsonl") as f:
    for line in f:
        d = json.loads(line)
        events[d["event_id"]] = d

HORIZONS = ["t1", "t3", "t5", "t7", "t15", "t30", "t60", "avg_short", "avg_mid", "avg_long", "avg_all"]

def strict_acc(hz):
    n = k = 0
    for eid, p in preds.items():
        lb = labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None:
            continue
        n += 1
        if p["pred_direction"] == lb[f"label_{hz}"]:
            k += 1
    return n, k

def lenient_acc(hz):
    n = k = 0
    for eid, p in preds.items():
        lb = labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None:
            continue
        pred, gt = p["pred_direction"], lb[f"label_{hz}"]
        if pred != "neutral" and gt != "neutral":
            n += 1
            if pred == gt:
                k += 1
    return n, k

print("=== 全量 Strict / Lenient ACC（统一口径）===")
print(f"{'horizon':<12}{'strict':<18}{'lenient':<18}")
res = {}
for hz in HORIZONS:
    ns, ks = strict_acc(hz)
    nl, kl = lenient_acc(hz)
    res[hz] = (ns, ks, nl, kl)
    print(f"{hz:<12}{ks}/{ns} = {ks/ns*100:.1f}%   {kl}/{nl} = {kl/nl*100:.1f}%" if nl else f"{hz:<12}{ks}/{ns} = {ks/ns*100:.1f}%   -")

# pred=neutral 占比
neu = sum(1 for p in preds.values() if p["pred_direction"] == "neutral")
print(f"\npred=neutral: {neu}/1000 = {neu/10:.1f}%")
gt_neu_t3 = sum(1 for lb in labels.values() if lb.get("label_t3") == "neutral")
gt_neu_all = sum(1 for lb in labels.values() if lb.get("label_avg_all") == "neutral")
print(f"GT neutral t3: {gt_neu_t3}, avg_all: {gt_neu_all}")

# 混淆矩阵 T+3 与 avg_all
for hz in ["t3", "avg_all"]:
    cm = Counter()
    for eid, p in preds.items():
        lb = labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None:
            continue
        cm[(p["pred_direction"], lb[f"label_{hz}"])] += 1
    print(f"\n混淆矩阵 {hz} (pred \\ gt): up/down/neutral")
    for pred in ["up", "down", "neutral"]:
        row = [cm[(pred, gt)] for gt in ["up", "down", "neutral"]]
        print(f"  {pred:<8} {row[0]:<6} {row[1]:<6} {row[2]:<6}")

# AUC (up vs down 二分类，用 confidence * sign)
def auc(hz):
    pairs = []
    for eid, p in preds.items():
        lb = labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None:
            continue
        gt = lb[f"label_{hz}"]
        if gt == "neutral" or p["pred_direction"] == "neutral":
            continue
        score = p["confidence"] if p["pred_direction"] == "up" else -p["confidence"]
        pairs.append((score, 1 if gt == "up" else 0))
    n1 = sum(y for _, y in pairs)
    n0 = len(pairs) - n1
    if not n1 or not n0:
        return None, len(pairs)
    rank = {}
    spairs = sorted(pairs)
    i = 0
    r = 1
    while i < len(spairs):
        j = i
        while j < len(spairs) and spairs[j][0] == spairs[i][0]:
            j += 1
        avg_r = (r + r + j - i - 1) / 2
        for k2 in range(i, j):
            rank[id(spairs[k2])] = avg_r
        r += j - i
        i = j
    s1 = sum(rank[id(x)] for x in pairs if x[1] == 1)
    return (s1 - n1 * (n1 + 1) / 2) / (n1 * n0), len(pairs)

print("\n=== AUC (up vs down, 双方非 neutral) ===")
for hz in HORIZONS:
    a, n = auc(hz)
    if a:
        print(f"{hz:<12} AUC={a:.3f} (n={n})")

# Spearman conf vs |CAR|
def spearman(xs, ys):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j < len(s) and v[s[j]] == v[s[i]]:
                j += 1
            for k2 in range(i, j):
                r[s[k2]] = (i + j + 1) / 2
            i = j
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0

print("\n=== Spearman (conf vs |CAR|) ===")
for hz in ["t3", "t7", "t15", "avg_all"]:
    xs, ys = [], []
    for eid, p in preds.items():
        lb = labels.get(eid)
        if not lb or lb.get(f"car_{hz}") is None:
            continue
        xs.append(p["confidence"])
        ys.append(abs(lb[f"car_{hz}"]))
    print(f"{hz:<12} rho={spearman(xs, ys):.3f} (n={len(xs)})")

# F1 macro 3-class
def f1_macro(hz):
    labels_set = ["up", "down", "neutral"]
    tp = Counter(); fp = Counter(); fn = Counter()
    for eid, p in preds.items():
        lb = labels.get(eid)
        if not lb or lb.get(f"label_{hz}") is None:
            continue
        y, yhat = lb[f"label_{hz}"], p["pred_direction"]
        if y == yhat:
            tp[y] += 1
        else:
            fp[yhat] += 1
            fn[y] += 1
    f1s = []
    for c in labels_set:
        prec = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0
        rec = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0)
    return sum(f1s) / 3, f1s

print("\n=== F1 macro (3-class strict) ===")
for hz in ["t3", "avg_all"]:
    fm, f1s = f1_macro(hz)
    print(f"{hz:<12} macro={fm:.3f} (up={f1s[0]:.3f}, down={f1s[1]:.3f}, neutral={f1s[2]:.3f})")

# 分市场
print("\n=== 分市场 Strict ACC ===")
for hz in ["t3", "t7", "t15", "avg_all"]:
    for mkt in ["CN", "US"]:
        n = k = 0
        nl = kl = 0
        for eid, p in preds.items():
            lb = labels.get(eid)
            if not lb or lb.get("market") != mkt or lb.get(f"label_{hz}") is None:
                continue
            n += 1
            if p["pred_direction"] == lb[f"label_{hz}"]:
                k += 1
            if p["pred_direction"] != "neutral" and lb[f"label_{hz}"] != "neutral":
                nl += 1
                if p["pred_direction"] == lb[f"label_{hz}"]:
                    kl += 1
        print(f"{hz:<10} {mkt}: strict {k}/{n}={k/n*100:.1f}%  lenient {kl}/{nl}={kl/nl*100:.1f}%" if nl else f"{hz:<10} {mkt}: strict {k}/{n}={k/n*100:.1f}%")

# 分事件类型（labels 里的 event_type_l2 / events 里的类型字段）
print("\n=== labels 中事件类型字段采样 ===")
et_keys = Counter()
for lb in labels.values():
    et_keys[lb.get("event_type_l2", "?")] += 1
for et, c in et_keys.most_common(20):
    print(f"  {et}: {c}")

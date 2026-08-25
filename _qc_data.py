"""远程数据质检：完整度 / 结构分布 / 推理链质量 / 基础泄漏审计。"""
import json
import os
import collections
import re

BASE = "/root/pronoia/data_v5"
CACHE = os.path.join(BASE, "research_cache.jsonl")
EVS = os.path.join(BASE, "events_enriched.jsonl")
LBS = os.path.join(BASE, "labels.jsonl")

def read(p, n=None):
    rows = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if n and len(rows) >= n:
                break
    return rows

rep = {}
rep["n_research"] = sum(1 for _ in open(CACHE))

evs = read(EVS)
lbs = read(LBS)
by_eid = {}
for e in evs:
    by_eid[str(e.get("event_id") or "")] = e
rep["n_events"] = len(evs)
rep["n_labels"] = len(lbs)

# ---- 完整度 ----
need = ["event_id", "rationale", "ok"]
nan_rat = 0
no_rat = 0
no_claim = 0
sample_with = 0
with open(CACHE) as f:
    for line in f:
        r = json.loads(line)
        if r.get("ok") is not True:
            sample_with += 1
            continue
        if not r.get("rationale"):
            no_rat += 1
        claims = r.get("claims")
        # claims 可能是字符串
        ctxt = r.get("rationale") or ""
        if isinstance(claims, str):
            n_claims = len(re.findall(r"(?i)\b(ret|car)_t\d+\b", claims))
        elif isinstance(claims, list):
            n_claims = len(claims)
        elif isinstance(ctxt, str):
            n_claims = len(re.findall(r"(?i)\b(ret|car)_t\d+\b", ctxt))
        else:
            n_claims = 0
        if n_claims == 0:
            no_claim += 1
rep["research_not_ok"] = sample_with
rep["rationale_missing"] = no_rat
rep["no_claim_in_rationale"] = no_claim

# ---- 推理链长度 ----
lens = []
with open(CACHE) as f:
    for line in f:
        r = json.loads(line)
        rat = r.get("rationale") or ""
        lens.append(len(rat))
if lens:
    q = lambda arr, p: sorted(arr)[int(p * (len(arr) - 1))]
    rep["rationale_len"] = {"n": len(lens), "min": min(lens), "p10": q(lens, .1),
                            "median": q(lens, .5), "p90": q(lens, .9), "max": max(lens)}

# ---- 指标族分布（从全量 rationale 提断言） ----
metric_fam = collections.Counter()
horizons = collections.Counter()
with open(CACHE) as f:
    for line in f:
        r = json.loads(line)
        ctxt = r.get("rationale") or ""
        for m in re.findall(r"(?i)\b(ret|car)_t(\d+)\b", ctxt):
            fam, h = m[0].lower(), int(m[1])
            metric_fam[fam] += 1
            horizons[h] += 1
rep["metric_family"] = dict(metric_fam)
rep["horizons"] = {str(k): v for k, v in sorted(horizons.items())}

# ---- 标签方向分布 ----
dirs = collections.Counter()
conf = []
with open(LBS) as f:
    for line in f:
        l = json.loads(line)
        if isinstance(l.get("direction"), (int, float)):
            dirs[l["direction"]] += 1
        c = l.get("confidence")
        if isinstance(c, (int, float)):
            conf.append(c)
rep["label_direction"] = dict(dirs)
if conf:
    q = lambda arr, p: sorted(arr)[int(p * (len(arr) - 1))]
    rep["label_conf"] = {"n": len(conf), "min": round(min(conf), 3), "median": round(q(conf, .5), 3), "max": round(max(conf), 3)}

print(json.dumps(rep, ensure_ascii=False, indent=2))

# ---- 抽样 5 条理性链开头 ----
print("\n===== 抽样推理链（前 5 条，各截 300 字）=====")
shown = 0
with open(CACHE) as f:
    for line in f:
        r = json.loads(line)
        eid = str(r.get("event_id") or "")
        e = by_eid.get(eid, {})
        ymd = e.get("event_date") or e.get("published_at") or e.get("date") or "?"
        rat = r.get("rationale") or ""
        head = rat[:300].replace("\n", " ")
        print(f"\n--- {eid} | ok={r.get('ok')} | date={ymd} | len={len(rat)} ---")
        print(head)
        shown += 1
        if shown >= 5:
            break
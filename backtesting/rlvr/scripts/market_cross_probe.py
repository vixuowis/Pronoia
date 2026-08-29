"""market_cross_probe.py — market 维度交叉分析：market × event_type / horizon 代理 / n_claims 等."""
import json
from collections import defaultdict

RUN = "/root/Pronoia/pronoia_run"
r62 = json.load(open(f"{RUN}/eval_papv_v62_t06_report.json"))
r61 = json.load(open(f"{RUN}/eval_papv_v61_t06_report.json"))

ev62 = {e["event_id"]: e for e in r62["ev_detail"]}
ev61 = {e["event_id"]: e for e in r61["ev_detail"]}
print(f"[ev_detail] v62={len(ev62)} v61={len(ev61)}")
print("[ev_detail entry keys]", sorted(next(iter(ev62.values())).keys()))
e = next(iter(ev62.values()))
for k in ("market", "event_type", "ticker", "symbol"):
    if k in e:
        print(f"  sample {k} =", e[k])

# 找 market 字段
mk = None
for cand in ("market", "mk", "region"):
    if cand in e:
        mk = cand
        break
if mk is None:
    # 从 event_id 前缀猜：trn2_cn_ / trn2_us_
    def getm(ev):
        eid = str(ev.get("event_id") or "")
        return "CN" if "_cn_" in eid else ("US" if "_us_" in eid else "?")
    mk = "_eid_"
else:
    def getm(ev):
        return str(ev.get(mk) or "?")

common = [k for k in ev62 if k in ev61]  # ev62/ev61 现在都是 dict
print("[n common]", len(common))

def acc_of(ev, side):
    v = ev.get(f"{side}_acc")
    return v

def agg(keys, src, side="adapter"):
    num = den = 0.0
    for k in keys:
        ev = src[k]
        w = max(ev.get("n_settleable") or 0, 1)
        a = acc_of(ev, side)
        if a is None:
            continue
        num += a * w
        den += w
    return (num / den if den else 0.0), int(den)

# market 总览
print("\n===== market 总览（事件级加权 acc） =====")
bym = defaultdict(list)
for k in common:
    bym[getm(ev62[k])].append(k)
for m, ks in sorted(bym.items()):
    b, nb = agg(ks, ev62, "base")
    v6, _ = agg(ks, ev62)
    v1, _ = agg(ks, ev61)
    print(f"  {m}: n_ev={len(ks)} n_claims={nb} base={b:.3f} v61={v1:.3f} v62={v6:.3f}")

# market × event_type
print("\n===== market × event_type =====")
cross = defaultdict(list)
for k in common:
    cross[(getm(ev62[k]), ev62[k].get("event_type") or "未知")].append(k)
rows = []
for (m, t), ks in cross.items():
    if len(ks) < 5:
        continue
    b, nb = agg(ks, ev62, "base")
    v6, _ = agg(ks, ev62)
    v1, _ = agg(ks, ev61)
    rows.append((m, t, len(ks), nb, b, v1, v6))
rows.sort(key=lambda x: (x[0], -x[2]))
for m, t, n, nb, b, v1, v6 in rows:
    print(f"  {m} | {t:<20} n_ev={n:>4} n_claims={nb:>5} base={b:.3f} v61={v1:.3f} v62={v6:.3f} Δ={v6-b:+.3f}")

# 小样本类型也列出
print("\n----- 小样本（n_ev<5，仅计数） -----")
for (m, t), ks in sorted(cross.items()):
    if len(ks) < 5:
        print(f"  {m} | {t:<20} n_ev={len(ks)}")

# market × n_claims / n_settleable 桶
print("\n===== market × n_claims =====")
cross2 = defaultdict(list)
for k in common:
    nc = ev62[k].get("n_claims") or 0
    bucket = str(nc) if nc <= 4 else "5+"
    cross2[(getm(ev62[k]), bucket)].append(k)
for (m, b_), ks in sorted(cross2.items()):
    v6, nb = agg(ks, ev62)
    b, _ = agg(ks, ev62, "base")
    print(f"  {m} | n_claims={b_}  n_ev={len(ks):>4} base={b:.3f} v62={v6:.3f}")

# market × TRUE占比 / 全对全错
print("\n===== market × 极端事件 =====")
for m, ks in sorted(bym.items()):
    full = sum(1 for k in ks if (ev62[k].get("adapter_acc") or 0) >= 0.999)
    zero = sum(1 for k in ks if (ev62[k].get("adapter_acc") or 0) <= 0.001)
    print(f"  {m}: 全对 {full} ({full/len(ks)*100:.1f}%)  全错 {zero} ({zero/len(ks)*100:.1f}%)")

# market × 时间分布（按年月）看 OOS 切分
print("\n===== market × 年份（若有日期字段） =====")
date_field = None
for cand in ("event_date", "date", "ann_date", "ts"):
    if cand in e:
        date_field = cand
        break
if date_field:
    yy = defaultdict(list)
    for k in common:
        d = str(ev62[k].get(date_field) or "")
        if len(d) >= 4:
            yy[(getm(ev62[k]), d[:4])].append(k)
    for (m, y), ks in sorted(yy.items()):
        v6, _ = agg(ks, ev62)
        print(f"  {m} {y}: n_ev={len(ks)} v62={v6:.3f}")
else:
    print("  [无日期字段，跳过]")

# market × horizon 代理：用 ev_detail 中 per-family/horizon？检查是否有
print("\n[检查 ev_detail 是否含 per-horizon 明细]", [k for k in ev62[0].keys() if "hzn" in k.lower() or "horizon" in k.lower()])
print("[检查 report 顶层是否含 by_market]", list(r62["sides"]["adapter"].keys()))

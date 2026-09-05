"""cat_analysis.py — 分类效果分布 + 好坏条件分析（vanilla vs v61-b vs base）."""
import json
from collections import defaultdict

RUN = "/root/Pronoia/pronoia_run"

r62 = json.load(open(f"{RUN}/eval_papv_v62_t06_report.json"))
r61 = json.load(open(f"{RUN}/eval_papv_v61_t06_report.json"))
m62 = {e["event_id"]: e for e in r62["ev_detail"]}
m61 = {e["event_id"]: e for e in r61["ev_detail"]}
common = [k for k in m62 if k in m61]


def acc(src, k, side="adapter_acc"):
    v = src[k].get(side)
    return v


def agg(keys, src, side="adapter_acc"):
    num = den = 0.0
    for k in keys:
        w = max(src[k].get("n_settleable") or 0, 1)
        v = acc(src, k, side)
        num += (v if v is not None else 0.0) * w
        den += w
    return num / den if den else 0.0


# ---- 1. 分类分布 ----
print("=" * 70)
print("【1】按 event_type 分布（n>=10，按 vanilla-base 提升排序）")
bytype = defaultdict(list)
for k in common:
    bytype[m62[k].get("event_type") or "未知"].append(k)

rows = []
for t, ks in bytype.items():
    if len(ks) < 10:
        continue
    b = agg(ks, m62, "base_acc")
    v62 = agg(ks, m62)
    v61 = agg(ks, m61)
    rows.append((t, len(ks), b, v61, v62))
rows.sort(key=lambda x: -(x[4] - x[2]))
print(f"{'类型':<24}{'n':>5}{'base':>8}{'v61b':>8}{'v62':>8}{'Δ62':>8}{'Δ61':>8}")
for t, n, b, v61, v62 in rows:
    print(f"{t:<24}{n:>5}{b:>8.3f}{v61:>8.3f}{v62:>8.3f}{v62-b:>+8.3f}{v61-b:>+8.3f}")

print()
print("【1b】按 market 分布")
bymkt = defaultdict(list)
for k in common:
    bymkt[m62[k].get("market") or "未知"].append(k)
for mk, ks in sorted(bymkt.items()):
    b = agg(ks, m62, "base_acc")
    print(f"  {mk}: n={len(ks)} base={b:.3f} v61b={agg(ks, m61):.3f} v62={agg(ks, m62):.3f}")

# ---- 2. 好坏条件分析 ----
print()
print("=" * 70)
print("【2】条件分析：什么时候表现好/差（vanilla）")

# 2a. 按 n_claims 分桶
print("\n[2a] 按断言数分桶（vanilla acc, base acc）")
bync = defaultdict(list)
for k in common:
    nc = m62[k].get("n_claims") or 0
    bync[min(nc, 8)].append(k)
for nc in sorted(bync):
    ks = bync[nc]
    print(f"  n_claims={nc}: n={len(ks)} base={agg(ks, m62, 'base_acc'):.3f} v62={agg(ks, m62):.3f}")

# 2b. 按 n_settleable（可结算性）
print("\n[2b] 按可结算断言数分桶")
byns = defaultdict(list)
for k in common:
    ns = m62[k].get("n_settleable") or 0
    byns[min(ns, 6)].append(k)
for ns in sorted(byns):
    ks = byns[ns]
    print(f"  n_settleable={ns}: n={len(ks)} base={agg(ks, m62, 'base_acc'):.3f} v62={agg(ks, m62):.3f}")

# 2c. 极端事件：全对 vs 全错
print("\n[2c] 极端事件分布（vanilla）")
full = [k for k in common if acc(m62, k) is not None and acc(m62, k) == 1.0]
zero = [k for k in common if acc(m62, k) is not None and acc(m62, k) == 0.0]
print(f"  全对(=1.0): {len(full)} ({len(full)/len(common)*100:.1f}%)")
print(f"  全错(=0.0): {len(zero)} ({len(zero)/len(common)*100:.1f}%)")
# 全错事件的类型分布
zt = defaultdict(list)
for k in zero:
    zt[m62[k].get("event_type") or "未知"].append(k)
print("  全错事件 top 类型:")
for t, ks in sorted(zt.items(), key=lambda x: -len(x[1]))[:6]:
    print(f"    {t}: {len(ks)}")
# 全对事件的类型分布
ft = defaultdict(list)
for k in full:
    ft[m62[k].get("event_type") or "未知"].append(k)
print("  全对事件 top 类型:")
for t, ks in sorted(ft.items(), key=lambda x: -len(x[1]))[:6]:
    print(f"    {t}: {len(ks)}")

# 2d. v62 与 v61 分歧事件
print("\n[2d] v62 vs v61 分歧事件（|Δacc|>=0.5）")
div = [k for k in common
       if acc(m62, k) is not None and acc(m61, k) is not None
       and abs(acc(m62, k) - acc(m61, k)) >= 0.5]
print(f"  分歧数: {len(div)}")
dv = defaultdict(list)
for k in div:
    dv[m62[k].get("event_type") or "未知"].append(k)
for t, ks in sorted(dv.items(), key=lambda x: -len(x[1]))[:6]:
    w62 = agg(ks, m62)
    w61 = agg(ks, m61)
    print(f"    {t}: n={len(ks)} v62={w62:.3f} v61b={w61:.3f}")

# ---- 3. case study 候选 ----
print()
print("=" * 70)
print("【3】case 候选")
# 3a. v62 完胜 v61 的全对事件（vanilla 全对、v61 全错）
win = [k for k in common
       if acc(m62, k) == 1.0 and acc(m61, k) == 0.0 and (m62[k].get("n_settleable") or 0) >= 3]
print(f"\n[case-A 候选] vanilla全对&v61全错(n_settle>=3): {len(win)}")
for k in win[:5]:
    e = m62[k]
    print(f"  {k} | {e.get('event_type')} | {e.get('title')} | ns={e.get('n_settleable')}")

# 3b. 反向：v61 全对 vanilla 全错
lose = [k for k in common
        if acc(m61, k) == 1.0 and acc(m62, k) == 0.0 and (m62[k].get("n_settleable") or 0) >= 3]
print(f"\n[case-B 候选] v61全对&vanilla全错(n_settle>=3): {len(lose)}")
for k in lose[:5]:
    e = m62[k]
    print(f"  {k} | {e.get('event_type')} | {e.get('title')} | ns={e.get('n_settleable')}")

# 3c. 难负里 vanilla 大幅优于 base
hard_kw = ("中标", "扭亏", "预增", "定增", "回购")
hardwin = [k for k in common
           if any(w in (m62[k].get("title") or "") for w in hard_kw)
           and acc(m62, k) == 1.0 and (m62[k].get("base_acc") or 1) <= 0.34
           and (m62[k].get("n_settleable") or 0) >= 3]
print(f"\n[case-C 候选] 难负: vanilla全对&base<=0.33: {len(hardwin)}")
for k in hardwin[:5]:
    e = m62[k]
    print(f"  {k} | {e.get('event_type')} | {e.get('title')} | base={e.get('base_acc')}")

# 3d. 难负里 vanilla 仍全错
hardlose = [k for k in common
            if any(w in (m62[k].get("title") or "") for w in hard_kw)
            and acc(m62, k) == 0.0 and (m62[k].get("n_settleable") or 0) >= 3]
print(f"\n[case-D 候选] 难负: vanilla仍全错: {len(hardlose)}")
for k in hardlose[:5]:
    e = m62[k]
    print(f"  {k} | {e.get('event_type')} | {e.get('title')} | base={e.get('base_acc')}")

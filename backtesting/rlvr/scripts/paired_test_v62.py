"""paired_test_v62.py — v6.2-vanilla vs v6.1-b 配对 bootstrap + 难负子集。"""
import json
import random

RUN = "/root/Pronoia/pronoia_run"

r62 = json.load(open(f"{RUN}/eval_papv_v62_t06_report.json"))
r61 = json.load(open(f"{RUN}/eval_papv_v61_t06_report.json"))

m62 = {e["event_id"]: e for e in r62["ev_detail"]}
m61 = {e["event_id"]: e for e in r61["ev_detail"]}
common = [k for k in m62 if k in m61]
print("共同事件数:", len(common))

# base 一致性 sanity check
diff_base = [k for k in common
             if m62[k].get("base_acc") is not None
             and m61[k].get("base_acc") is not None
             and abs(m62[k]["base_acc"] - m61[k]["base_acc"]) > 1e-9]
print("base_acc 不一致数:", len(diff_base))

# 加权每事件（n_settleable 为权重 → 事件级断言准确率）
def wstats(keys, src):
    num = den = 0.0
    for k in keys:
        e = src[k]
        w = max(e.get("n_settleable") or 0, 1)
        acc = e.get("adapter_acc")
        num += (acc if acc is not None else 0.0) * w
        den += w
    return num / den if den else 0.0

acc62 = wstats(common, m62)
acc61 = wstats(common, m61)
print(f"v62-vanilla acc = {acc62:.4f}")
print(f"v61-b      acc = {acc61:.4f}")
print(f"Δ(v62-v61) = {acc62 - acc61:+.4f}")

# 配对 bootstrap（事件级重采样，权重随事件）
random.seed(42)
diffs = []
n = len(common)
for _ in range(2000):
    samp = [common[random.randrange(n)] for _ in range(n)]
    diffs.append(wstats(samp, m62) - wstats(samp, m61))
diffs.sort()
lo, hi = diffs[49], diffs[1950]
print(f"bootstrap 95%CI: [{lo:+.4f}, {hi:+.4f}]")

# 逐事件胜负（None 视为缺失，跳过）
def a62(k):
    return m62[k].get("adapter_acc")

def a61(k):
    return m61[k].get("adapter_acc")

pair = [(a62(k), a61(k)) for k in common if a62(k) is not None and a61(k) is not None]
wins62 = sum(1 for x, y in pair if x > y)
wins61 = sum(1 for x, y in pair if x < y)
print(f"逐事件(可比较 {len(pair)}): v62 胜 {wins62} / v61 胜 {wins61} / 平 {len(pair)-wins62-wins61}")
print(f"adapter_acc 缺失: v62={sum(1 for k in common if a62(k) is None)} v61={sum(1 for k in common if a61(k) is None)}")

# 难负子集（关键词：中标/扭亏/预增/定增/回购/中标公告）
HARD_KW = ("中标", "扭亏", "预增", "定增", "回购", "中标公告")
hard = [k for k in common
        if any(w in (m62[k].get("title") or "") for w in HARD_KW)
        or any(w in (m62[k].get("event_type") or "") for w in HARD_KW)]
print(f"\n难负子集 n={len(hard)}")
if hard:
    print(f"  v62-vanilla acc = {wstats(hard, m62):.4f}")
    print(f"  v61-b      acc = {wstats(hard, m61):.4f}")
    bs = [m62[k].get("base_acc") for k in hard if m62[k].get("base_acc") is not None]
    if bs:
        print(f"  base       acc = {sum(bs)/len(bs):.4f} (n={len(bs)})")

# 格式失败率对比（fmt）
s62 = r62["sides"].get("adapter", {})
s61 = r61["sides"].get("adapter", {})
print(f"\nfmt: v62={s62.get('fmt')} v61={s61.get('fmt')}")
print(f"可结算断言: v62={s62.get('n_settleable')} v61={s61.get('n_settleable')}")

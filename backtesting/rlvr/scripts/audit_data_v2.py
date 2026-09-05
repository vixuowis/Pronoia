#!/usr/bin/env python3
"""audit_data_v2.py — Pronoia 训练数据严谨性审计（7 项硬检查）。

用法：python3 audit_data_v2.py <data_dir>
"""
import json
import sys
from collections import Counter
from pathlib import Path

def read_jsonl(p):
    rows = []
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                print(f"  [BAD-JSON] {p.name} 行{i}: {e}")
    return rows

def main(d: Path):
    evs = read_jsonl(d / "events_enriched.jsonl")
    lbs = {r.get("event_id"): r for r in read_jsonl(d / "labels.jsonl")}
    rcs = {r.get("event_id"): r for r in read_jsonl(d / "research_cache.jsonl")}
    print(f"=== 表规模 ===\nevents={len(evs)} labels={len(lbs)} cache={len(rcs)}")

    eid_evs = [e.get("event_id") for e in evs]
    dup = [k for k, v in Counter(eid_evs).items() if v > 1]
    print(f"event_id 重复: {len(dup)}")
    join1 = sum(1 for e in eid_evs if e in lbs)
    join2 = sum(1 for e in eid_evs if e in rcs)
    print(f"三表 join: events∩labels={join1} events∩cache={join2}")

    # ---- 检查1：事件正文质量（占位符检测）----
    print("\n=== 检查1：事件正文真实性 ===")
    PLACEHOLDER_PAT = ["待执行", "预期:机构", "前值:当前", "XXXX", "TODO", "placeholder", "N/A | N/A"]
    ph_cnt, short_cnt, empty_cnt = 0, 0, 0
    for e in evs:
        t = str(e.get("event_text") or "")
        if not t.strip() or t.strip() in ("（无正文，仅标题）", "无"):
            empty_cnt += 1
        elif any(p in t for p in PLACEHOLDER_PAT):
            ph_cnt += 1
        elif len(t) < 60:
            short_cnt += 1
    print(f"空正文: {empty_cnt} | 占位符: {ph_cnt} | 过短(<60字): {short_cnt} | 合计问题: {empty_cnt+ph_cnt+short_cnt}/{len(evs)}")

    # ---- 检查2：标题-标的语义匹配抽查 ----
    print("\n=== 检查2：标题含标的名称/代码比例 ===")
    name_hit = 0
    checked = 0
    for e in evs:
        title = str(e.get("title") or "")
        sym = str(e.get("symbol") or "")
        name = str(e.get("symbol_name") or e.get("name") or "")
        if not sym:
            continue
        checked += 1
        if (sym[-6:] if sym.startswith(("sh", "sz", "bj")) else sym) in title or (name and name in title):
            name_hit += 1
    print(f"标题含代码或名称: {name_hit}/{checked} ({100*name_hit/max(1,checked):.1f}%)")

    # ---- 检查3：labels 数值分布合理性 ----
    print("\n=== 检查3：labels K线结算数值 ===")
    import math
    bad_car, checked = 0, 0
    car7 = []
    for e in evs:
        lb = lbs.get(e.get("event_id"))
        if not lb:
            continue
        checked += 1
        v = lb.get("car_t7")
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        if abs(v) > 1.0:  # CAR 超过 ±100% 可疑
            bad_car += 1
        car7.append(v)
    n = len(car7)
    print(f"car_t7 有值: {n}/{checked} | |car|>100%: {bad_car}")
    if n:
        m = sum(car7) / n
        sd = (sum((x - m) ** 2 for x in car7) / n) ** 0.5
        p5 = sorted(car7)[n // 20]
        p95 = sorted(car7)[19 * n // 20]
        zeros = sum(1 for x in car7 if x == 0.0)
        print(f"car_t7: mean={m:+.4f} sd={sd:.4f} p5={p5:+.3f} p95={p95:+.3f} 零值={zeros}")
        # ret 与 bm_ret 一致性: car ≈ ret - bm（粗略）
        diffs = []
        for e in evs[:500]:
            lb = lbs.get(e.get("event_id"))
            if lb and lb.get("ret_t7") is not None and lb.get("bm_ret_t7") is not None and lb.get("car_t7") is not None:
                diffs.append(abs(lb["car_t7"] - (lb["ret_t7"] - lb["bm_ret_t7"])))
        if diffs:
            print(f"car ≈ ret-bm 残差: mean={sum(diffs)/len(diffs):.4f} max={max(diffs):.4f} (市场模型残差应小且非零)")

    # ---- 检查4：量价特征真实性 ----
    print("\n=== 检查4：量价特征 ===")
    vol_missing, vol_bad = 0, 0
    regs = Counter()
    for r in rcs.values():
        vf = r.get("vol_features") or {}
        if not vf.get("vol_regime"):
            vol_missing += 1
        else:
            regs[vf["vol_regime"]] += 1
        vr = vf.get("vol_t0_ratio")
        if vr is not None and not (0.01 < vr < 50):
            vol_bad += 1
    print(f"缺失: {vol_missing}/{len(rcs)} | 异常值: {vol_bad} | regime分布: {dict(regs)}")

    # ---- 检查5：research_cache 内容充实度 ----
    print("\n=== 检查5：前置研究上下文充实度 ===")
    empty_market = empty_bench = empty_bucket = empty_scen = empty_evid = 0
    for r in rcs.values():
        if not (r.get("market_ctx") or {}).get("ok"):
            empty_market += 1
        b = r.get("benchmark_ctx") or {}
        if not (b.get("benchmark_stats") or {}).get("ok"):
            empty_bench += 1
        if (r.get("bucket_stats") or {}).get("n_prior", 0) < 3:
            empty_bucket += 1
        if not r.get("scenarios"):
            empty_scen += 1
        if not r.get("evidence_items"):
            empty_evid += 1
    N = len(rcs)
    print(f"market_ctx 缺失: {empty_market}/{N} | benchmark 缺失: {empty_bench}/{N}")
    print(f"bucket_stats<3: {empty_bucket}/{N} | scenarios 空: {empty_scen}/{N} | evidence 空: {empty_evid}/{N}")

    # ---- 检查6：正文重复度（换皮数据检测）----
    print("\n=== 检查6：正文去重检测 ===")
    texts = Counter(str(e.get("event_text") or "")[:80] for e in evs)
    top3 = texts.most_common(3)
    uniq = len(texts)
    print(f"前80字符唯一数: {uniq}/{len(evs)} ({100*uniq/len(evs):.1f}%) | TOP3 重复: {[(t[:30], c) for t, c in top3]}")

    # ---- 检查7：时间分布（真实事件流应有自然时间分布）----
    print("\n=== 检查7：时间分布 ===")
    by_month = Counter(str(e.get("event_time", ""))[:7] for e in evs)
    print(f"月度覆盖: {len(by_month)} 个月 | 最少月: {min(by_month.items(), key=lambda x: x[1])} | 最多月: {max(by_month.items(), key=lambda x: x[1])}")

    # ---- 抽样展示 3 条完整样本 ----
    print("\n=== 抽样 3 条（event + label + cache 摘要）===")
    import random
    random.seed(7)
    for e in random.sample(evs, 3):
        eid = e.get("event_id")
        lb, rc = lbs.get(eid, {}), rcs.get(eid, {})
        print(f"\n--- {eid} ---")
        print(f"  {str(e.get('title'))[:60]} | {e.get('symbol')} {e.get('event_time','')[:10]} {e.get('market')}/{e.get('event_type_l2')}")
        print(f"  正文[{len(str(e.get('event_text') or ''))}字]: {str(e.get('event_text') or '')[:100]}...")
        print(f"  car_t7={lb.get('car_t7')} ret_t7={lb.get('ret_t7')} p={lb.get('car_t7_pvalue')}")
        vf = (rc.get("vol_features") or {})
        print(f"  vol_regime={vf.get('vol_regime')} vol_t0_ratio={vf.get('vol_t0_ratio')}")
        mc = rc.get("market_ctx") or {}
        print(f"  market: mom20={mc.get('mom_20d_pct')} vol20={mc.get('vol_20d_ann_pct')}")

if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/root/pronoia/data_v2"))

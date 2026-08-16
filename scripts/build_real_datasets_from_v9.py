"""
从 events_phase1_backtestable_balanced_v9_1000 + labels_phase1_balanced_v9_1000
抽取 5 个 × 10 条的真实小规模数据集：

  数据集                              market  event_type              原文链接可点
  1. cn_earnings_10                   CN      财报超预期/不及预期         ✅ 东方财富公告
  2. cn_pure_ma_10                    CN      并购/分拆(不含融资类)        ✅ 东方财富公告
  3. cn_guidance_10                   CN      公司指引上调/下调           ✅ 东方财富公告
  4. us_sec_ma_10                     US      并购/分拆/再融资           ✅ Yahoo Finance SEC Filing
  5. cross_market_mix_10              MIX     以上4类均衡混合            ✅ 全部 http

约束：
- 仅抽取 source_url 以 http 开头的**真实可点击原文链接**事件，杜绝 synth-v7 占位符
- 仅抽取存在 Oracle label_t3（up/down/neutral）的事件（T+3 可评分）
- 不杜撰任何字段（title/event_text/event_time/symbol/source_url 一律原样拷贝 v9）
"""
from __future__ import annotations

import collections
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = DATA_DIR / "bt_datasets_real_v1"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "backend"))
from app.db import upsert_bt_dataset  # noqa: E402

V9_EVENTS = DATA_DIR / "events_phase1_backtestable_balanced_v9_1000.jsonl"
V9_LABELS = DATA_DIR / "labels_phase1_balanced_v9_1000.jsonl"

random.seed(20260816)  # 可复现

# ------------------------------------------------ 加载 v9 ------------------------------------------------
events_all: list[dict] = []
with open(V9_EVENTS) as f:
    for line in f:
        events_all.append(json.loads(line))

labels_by_eid: dict[str, dict] = {}
with open(V9_LABELS) as f:
    for line in f:
        l = json.loads(line)
        labels_by_eid[l["event_id"]] = l

print(f"[load] v9 events={len(events_all)}  labels={len(labels_by_eid)}")


def keep_http_and_labelled(evts: list[dict]) -> list[dict]:
    out = []
    for e in evts:
        url = str(e.get("source_url") or "")
        if not url.startswith("http"):
            continue
        lab = labels_by_eid.get(e["event_id"])
        if not lab or lab.get("label_t3") not in ("up", "down", "neutral"):
            continue
        out.append(e)
    return out


def stats(evts: list[dict]) -> dict:
    by_market = collections.Counter(e["market"] for e in evts)
    by_type = collections.Counter(e["event_type_l2"] for e in evts)
    by_symbol = collections.Counter(e["symbol"] for e in evts)
    times = [e["event_time"] for e in evts if e.get("event_time")]
    date_range = {"min": min(times)[:10], "max": max(times)[:10]} if times else None
    labels_cnt = collections.Counter(
        labels_by_eid[e["event_id"]]["label_t3"] for e in evts if e["event_id"] in labels_by_eid
    )
    return {
        "total": len(evts),
        "by_market": dict(by_market),
        "by_type": dict(by_type),
        "by_symbol": dict(by_symbol),
        "date_range": date_range,
        "label_t3": dict(labels_cnt),
    }


# ------------------------------------------------ 定义池子 ------------------------------------------------
def _deny_refi_keywords(text: str) -> bool:
    """再融资类关键词命中 → 从"纯并购"池剔除"""
    low = text.lower()
    refi_soft = ["增发", "配股", "可转债", "定增", "可转换", "可交换债"]
    return any(k in low for k in refi_soft)


pool_cn_earnings = keep_http_and_labelled(
    [e for e in events_all if e["market"] == "CN" and e["event_type_l2"] == "财报超预期/不及预期"]
)
pool_cn_ma_all = keep_http_and_labelled(
    [e for e in events_all if e["market"] == "CN" and e["event_type_l2"] == "并购/分拆/再融资"]
)
pool_cn_pure_ma = [
    e for e in pool_cn_ma_all
    if not _deny_refi_keywords((e.get("title") or e.get("event_text") or ""))
]
pool_cn_guidance = keep_http_and_labelled(
    [e for e in events_all if e["market"] == "CN" and e["event_type_l2"] == "公司指引上调/下调"]
)
pool_us_sec_ma = keep_http_and_labelled(
    [e for e in events_all if e["market"] == "US" and e["event_type_l2"] == "并购/分拆/再融资"]
)

print(f"\n[pool] cn_earnings  候选 {len(pool_cn_earnings)}")
print(f"[pool] cn_pure_ma   候选 {len(pool_cn_pure_ma)}")
print(f"[pool] cn_guidance  候选 {len(pool_cn_guidance)}")
print(f"[pool] us_sec_ma    候选 {len(pool_us_sec_ma)}")

assert len(pool_cn_earnings) >= 10
assert len(pool_cn_pure_ma) >= 10
assert len(pool_cn_guidance) >= 10
assert len(pool_us_sec_ma) >= 10


def sample(pool: list[dict], n: int, used: set[str]) -> list[dict]:
    """从池中抽 n 条，不重复使用已抽过的 event_id"""
    avail = [e for e in pool if e["event_id"] not in used]
    assert len(avail) >= n, f"池子只剩 {len(avail)} 条，不够抽 {n} 条"
    picked = random.sample(avail, n)
    used.update(e["event_id"] for e in picked)
    return picked


used_ids: set[str] = set()

# dataset5 跨市场混合：从每个池子里抽几条，且与 D1-D4 不重复
# 先给 D1-D4 抽完，D5 从剩余里均衡取
datasets_spec = [
    ("cn_earnings_10",    "CN A股财报业绩预告 10例",             lambda u: sample(pool_cn_earnings, 10, u)),
    ("cn_pure_ma_10",     "CN A股并购/资产重组 10例",           lambda u: sample(pool_cn_pure_ma, 10, u)),
    ("cn_guidance_10",    "CN A股公司业绩指引 10例",            lambda u: sample(pool_cn_guidance, 10, u)),
    ("us_sec_ma_10",      "US 美股 SEC 并购/分拆申报 10例",     lambda u: sample(pool_us_sec_ma, 10, u)),
]

picked_d1d4: dict[str, list[dict]] = {}
for dsid, dname, sampler in datasets_spec:
    picked = sampler(used_ids)
    picked_d1d4[dsid] = picked
    s = stats(picked)
    print(f"\n[sampled] {dsid} ({dname}): total={s['total']}  label_T3={s['label_t3']}  date={s['date_range']}")
    for e in picked[:2]:
        print(f"  · {e['event_time'][:10]}  {e['symbol']:<10s}  {(e.get('title') or e.get('event_text') or '')[:55]}")
        print(f"    URL: {e['source_url'][:95]}")

# D5: 剩余池子里每个池子按比例抽
left_cn_earn = [e for e in pool_cn_earnings if e["event_id"] not in used_ids]
left_cn_ma = [e for e in pool_cn_pure_ma if e["event_id"] not in used_ids]
left_cn_gui = [e for e in pool_cn_guidance if e["event_id"] not in used_ids]
left_us_ma = [e for e in pool_us_sec_ma if e["event_id"] not in used_ids]

mix_parts = [
    sample(left_cn_earn, 3, used_ids),
    sample(left_cn_ma, 3, used_ids),
    sample(left_cn_gui, 2, used_ids),
    sample(left_us_ma, 2, used_ids),
]
d5_picked: list[dict] = sum(mix_parts, [])
random.shuffle(d5_picked)
picked_d1d4["cross_market_mix_10"] = d5_picked
s = stats(d5_picked)
print(f"\n[sampled] cross_market_mix_10 (跨市场精选混合 10例): market={s['by_market']}  type={s['by_type']}  label_T3={s['label_t3']}")

# ------------------------------------------------ 写 JSONL + DB upsert ------------------------------------------------
DATASET_META_NAMES = {
    "cn_earnings_10":      "CN A股财报业绩预告 10例（真实东方财富公告链接+真实T+3行情Label）",
    "cn_pure_ma_10":       "CN A股并购/资产重组 10例（真实东方财富公告链接+真实T+3行情Label）",
    "cn_guidance_10":      "CN A股公司业绩指引 10例（真实东方财富公告链接+真实T+3行情Label）",
    "us_sec_ma_10":        "US 美股 SEC 并购/分拆申报 10例（真实Yahoo Finance SEC链接+真实T+3行情Label）",
    "cross_market_mix_10": "跨市场精选混合 10例（CN财报×3 / CN并购×3 / CN指引×2 / US并购×2，均真实链接+真实Label）",
}

for dsid, evts in picked_d1d4.items():
    ev_path = OUT_DIR / f"{dsid}.events.jsonl"
    lab_path = OUT_DIR / f"{dsid}.labels.jsonl"

    with open(ev_path, "w") as fo_e, open(lab_path, "w") as fo_l:
        for e in evts:
            fo_e.write(json.dumps(e, ensure_ascii=False) + "\n")
            lab = labels_by_eid[e["event_id"]]
            fo_l.write(json.dumps(lab, ensure_ascii=False) + "\n")

    st = stats(evts)
    row = upsert_bt_dataset(
        dataset_id=dsid,
        path=str(ev_path),
        name=DATASET_META_NAMES[dsid],
        total_events=st["total"],
        by_market=st["by_market"],
        by_type=st["by_type"],
        by_symbol=st["by_symbol"],
        date_range=st["date_range"],
        labels_path=str(lab_path),
    )
    print(f"\n[upsert ✅] {dsid:<22s} events={ev_path.name} labels={lab_path.name}")
    print(f"           name   = {DATASET_META_NAMES[dsid]}")
    print(f"           stats  = markets {st['by_market']} | types {st['by_type']} | T3 {st['label_t3']} | date {st['date_range']}")

print(f"\n[DONE] 5 datasets written to {OUT_DIR}")

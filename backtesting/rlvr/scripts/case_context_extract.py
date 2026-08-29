"""case_context_extract.py — 导出 3 个 case 的完整事件描述 + 预计算研究上下文."""
import json

RUN = "/root/Pronoia/pronoia_run"
CASES = [
    "trn2_cn_002599_ef150f62",  # Case-1 盛通股份 扭亏 成功
    "trn2_cn_600489_87052dcb",  # Case-2 中金黄金 预增 失败
    "trn2_cn_000685_c88b33a6",  # Case-3 中山公用 预增 失败
]

evs = {}
for split in ("data_v61_test", "data_v61_train"):
    try:
        for line in open(f"{RUN}/{split}/events_enriched.jsonl", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            eid = str(e.get("event_id") or "")
            if eid in CASES:
                evs[eid] = e
    except FileNotFoundError:
        pass

rcs = {}
for split in ("data_v61_test", "data_v61_train"):
    try:
        for line in open(f"{RUN}/{split}/research_cache.jsonl", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            eid = str(r.get("event_id") or "")
            if eid in CASES:
                rcs[eid] = r
    except FileNotFoundError:
        pass

for eid in CASES:
    print("=" * 100)
    print(f"CASE: {eid}")
    e = evs.get(eid)
    if not e:
        print("[event] <未找到>")
        continue
    print("[EVENT keys]", sorted(e.keys()))
    # 全量事件（截断 3000）
    print("[EVENT json]", json.dumps(e, ensure_ascii=False)[:3000])
    r = rcs.get(eid)
    if not r:
        print("[RESEARCH] <无>")
        continue
    print("[RESEARCH keys]", sorted(r.keys()))
    print("[RESEARCH json]", json.dumps(r, ensure_ascii=False)[:4500])

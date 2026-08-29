"""case_extract.py — 提取 case study 全链路：prompt 事件、三方 completion、labels 结算."""
import json

RUN = "/root/Pronoia/pronoia_run"

CASES = [
    # case-C: 难负，vanilla 全对，base 只有 0.33（扭亏）
    "trn2_cn_002599_ef150f62",
    # case-D: 难负，vanilla 仍全错（预增）
    "trn2_cn_600489_87052dcb",
    # case-D: base=0 且 vanilla 全错（预增）
    "trn2_cn_000685_c88b33a6",
]


def load(path):
    d = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                d[j.get("event_id")] = j
            except Exception:
                pass
    return d


v62 = load(f"{RUN}/oos_v62_adapter_t06_completions.jsonl")
v61 = load(f"{RUN}/oos_v61_adapter_t06_completions.jsonl")
base = load(f"{RUN}/oos_v61_base_t06_completions.jsonl")

# labels（结算真值）
labels = {}
with open(f"{RUN}/data_v61_test/labels.jsonl", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
            labels[j.get("event_id")] = j
        except Exception:
            pass

for eid in CASES:
    print("=" * 80)
    print(f"CASE: {eid}")
    lb = labels.get(eid, {})
    print(f"[LABEL keys] {list(lb.keys())[:10]}")
    # 标签摘要（截断）
    lbs = json.dumps(lb, ensure_ascii=False)
    print(f"[LABEL] {lbs[:1500]}")
    for name, src in (("v62", v62), ("v61", v61), ("base", base)):
        c = src.get(eid)
        if not c:
            print(f"[{name}] <无>")
            continue
        text = c.get("completion") or ""
        print(f"\n----- [{name} completion] ({len(text)} chars) -----")
        print(text[:3500])
    print()

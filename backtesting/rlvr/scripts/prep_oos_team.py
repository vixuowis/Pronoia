#!/usr/bin/env python3
"""_prep_oos_team.py — 从全池筛选「剩余 OOS」（未入 v5 训练）事件，
生成 events 子集文件供 team_research_batch 补 rationale。

输出：
  audit/oos_events_for_team.jsonl        全部剩余 OOS
  audit/oos_events_smoke.jsonl          小批量(默认6条，US+宏观优先)验证用
优先级：US 宏观 > US 其他 > CN 宏观 > CN 其他，便于优先补覆盖缺口。
"""
import json
from pathlib import Path

V3 = Path("/workspace/pronoia_run/data_v3")
OUT = Path("/workspace/pronoia_run/data_v3/audit")
V5_LB = "/workspace/backtesting/rlvr/training/remote_scripts/data_v5_labels.jsonl"
MACRO = {"增长/就业数据意外", "通胀数据意外", "政策利率调整"}


def load_ids(p) -> set:
    out = set()
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if l:
            out.add(str(json.loads(l).get("event_id")))
    return out


def main():
    v5 = load_ids(V5_LB)
    events = [json.loads(l) for l in open(V3 / "events_enriched.jsonl", encoding="utf-8")
              if l.strip()]
    lbs = load_ids(V3 / "labels.jsonl")
    # 剩余 OOS：全池有 label 且不在 v5
    oos = [e for e in events if str(e.get("event_id")) in lbs
           and str(e.get("event_id")) not in v5]
    # 排序：US宏观>US>CN宏观>CN
    def score(e):
        mk = str(e.get("market") or "?").upper()
        et = e.get("event_type_l2") or e.get("event_type") or ""
        is_us = mk == "US"
        is_mac = et in MACRO
        return (0 if is_us else 1) * 2 + (0 if is_mac else 1)
    oos.sort(key=score)  # 越靠前越优先
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "oos_events_for_team.jsonl", "w", encoding="utf-8") as f:
        for e in oos:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    smoke = oos[:6]
    with open(OUT / "oos_events_smoke.jsonl", "w", encoding="utf-8") as f:
        for e in smoke:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    from collections import Counter
    mk = Counter(str(e.get("market")).upper() for e in oos)
    mac = sum(1 for e in oos if (e.get("event_type_l2") or e.get("event_type")) in MACRO)
    mk_s = Counter(str(e.get("market")).upper() for e in smoke)
    mac_s = sum(1 for e in smoke if (e.get("event_type_l2") or e.get("event_type")) in MACRO)
    print(f"剩余OOS总数={len(oos)} market={dict(mk)} 宏观={mac}")
    print(f"SMOKE 共{len(smoke)} market={dict(mk_s)} 宏观={mac_s}")
    print("-> audit/oos_events_for_team.jsonl | audit/oos_events_smoke.jsonl")


if __name__ == "__main__":
    main()
"""assemble_data_v6.py — 组装 v6 训练数据目录，并切出独立样本外（OOS）测试集。

输入（/workspace/pronoia_run）：
  data_v3/events_enriched.jsonl        事件正文（全量 5171）
  data_v3/labels.jsonl                 K线客观结算标签（全量 5171）
  data_v3/research_cache_fallback.jsonl  程序化统计上下文（全量 5171）
  data_v3/audit/combined_team_rationale.jsonl   旧 v4/v5 时代 Team rationale
  data_v3/audit/research_cache_team.jsonl       v4 时代 Team rationale（可选）
  data_v3/audit/oos_team_full.jsonl    本轮新采集的 OOS Team rationale（ok=true）

逻辑：
  1. 每一行 research_cache = (fallback 统计上下文) + rationale。
  2. rationale 优先级：本轮新采集 oos_team_full > combined_team_rationale > research_cache_team。
  3. 有 label + 有 rationale 的事件才进 v6 全量池。
  4. 按 (market, 宏观/非宏观) 分层切分：train 与 样本外测试集 test，event_id 不相交。
     test 默认 20%，且绝不进入训练。

输出：
  data_v6_train/  events_enriched.jsonl / labels.jsonl / research_cache.jsonl
  data_v6_test/   events_enriched.jsonl / labels.jsonl / research_cache.jsonl
  data_v6_split_meta.json   分层拆分 + market 分布简报

用法（本地组装，产出目录后上传远程 GPU 训练/评估）：
  /root/miniconda3/bin/python assemble_data_v6.py
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

V3 = Path("/workspace/pronoia_run/data_v3")
AUDIT = V3 / "audit"
OUTROOT = Path("/workspace/pronoia_run")

MACRO = {"增长/就业数据意外", "通胀数据意外", "政策利率调整"}


def read_jsonl(p: Path) -> list[dict]:
    rows = []
    if not p.exists():
        return rows
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(V3))
    ap.add_argument("--out", default=str(OUTROOT))
    ap.add_argument("--test-ratio", type=float, default=0.20)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    audit = src / "audit" if (src / "audit").exists() else OUTROOT / "data_v3" / "audit"

    evs = {str(r.get("event_id") or ""): r for r in read_jsonl(src / "events_enriched.jsonl")}
    lbs = {str(r.get("event_id") or ""): r for r in read_jsonl(src / "labels.jsonl")}
    stats = {str(r.get("event_id") or ""): r for r in read_jsonl(
        src / "research_cache_fallback.jsonl")}

    # rationale 按优先级合并
    def collect(path: Path) -> dict:
        d = {}
        for r in read_jsonl(path):
            if r.get("ok") and r.get("rationale"):
                d[str(r.get("event_id"))] = r["rationale"]
        return d

    rat_v4 = collect(audit / "research_cache_team_v4.jsonl")  # 新：v4 Team 全量（最高优先）
    rat_new = collect(audit / "oos_team_full.jsonl")          # 本轮新采集
    rat_combined = collect(audit / "combined_team_rationale.jsonl")
    rat_team = collect(audit / "research_cache_team.jsonl")

    print(f"[RAT] v4={len(rat_v4)} new={len(rat_new)} combined={len(rat_combined)} team={len(rat_team)}")

    # 组装全量池
    rows = []  # (event_id, event, label, rc)
    for eid, ev in evs.items():
        lb = lbs.get(eid)
        st = stats.get(eid)
        if lb is None or st is None:
            continue
        rat = (rat_v4.get(eid) or rat_new.get(eid) or rat_combined.get(eid) or rat_team.get(eid))
        if not rat:
            continue
        rc = dict(st)
        rc["event_id"] = eid
        rc["rationale"] = rat
        rows.append((eid, ev, lb, rc))
    print(f"[POOL] v6 全量可训练样本 = {len(rows)}")

    # 分层切分 train/OOS test
    def stratum(eid: str) -> str:
        ev = evs.get(eid) or {}
        mk = str(ev.get("market") or "?").upper()
        et = ev.get("event_type_l2") or ev.get("event_type") or ""
        mac = "macro" if et in MACRO else "stock"
        return f"{mk}_{mac}"

    by_stratum: dict[str, list[tuple]] = {}
    for row in rows:
        by_stratum.setdefault(stratum(row[0]), []).append(row)

    rng = random.Random(args.seed)
    train_eids: list[str] = []
    test_eids: list[str] = []
    for s, grp in by_stratum.items():
        rng.shuffle(grp)
        n_test = max(1, round(len(grp) * args.test_ratio))
        test_eids.extend(e[0] for e in grp[:n_test])
        train_eids.extend(e[0] for e in grp[n_test:])

    test_set, train_set = set(test_eids), set(train_eids)
    assert not (test_set & train_set), "train/test 不得重叠"

    def write_dir(d: Path, ids: list[str]) -> int:
        d.mkdir(parents=True, exist_ok=True)
        n = 0
        with open(d / "events_enriched.jsonl", "w", encoding="utf-8") as fe, \
             open(d / "labels.jsonl", "w", encoding="utf-8") as fl, \
             open(d / "research_cache.jsonl", "w", encoding="utf-8") as fr:
            for eid in ids:
                ev, lb, rc = next((x[1], x[2], x[3]) for x in rows if x[0] == eid)
                fe.write(json.dumps(ev, ensure_ascii=False) + "\n")
                fl.write(json.dumps(lb, ensure_ascii=False) + "\n")
                fr.write(json.dumps(rc, ensure_ascii=False) + "\n")
                n += 1
        return n

    train_dir, test_dir = out / "data_v6_train", out / "data_v6_test"
    n_train = write_dir(train_dir, train_eids)
    n_test = write_dir(test_dir, test_eids)

    # 简报 + 元数据
    def mkt_dist(ids):
        c = Counter(str(evs[i].get("market") or "?").upper() for i in ids)
        c_mac = Counter("macro" if (evs[i].get("event_type_l2") or evs[i].get("event_type")) in MACRO
                        else "stock" for i in ids)
        return dict(c), dict(c_mac)

    meta = {
        "pool": len(rows), "train": n_train, "test": n_test,
        "test_ratio": args.test_ratio, "seed": args.seed,
        "train_market": mkt_dist(train_eids)[0], "test_market": mkt_dist(test_eids)[0],
        "train_type": mkt_dist(train_eids)[1], "test_type": mkt_dist(test_eids)[1],
        "test_ids": test_eids,
    }
    with open(out / "data_v6_split_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[DONE] train={n_train} test={n_test} → {out}")
    print(f"       train_market={meta['train_market']}")
    print(f"       test_market ={meta['test_market']}")
    print(f"       train_type  ={meta['train_type']}")
    print(f"       test_type   ={meta['test_type']}")


if __name__ == "__main__":
    main()
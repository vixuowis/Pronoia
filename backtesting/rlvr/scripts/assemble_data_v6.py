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
import re
from collections import Counter
from pathlib import Path

V3 = Path("/workspace/pronoia_run/data_v3")
AUDIT = V3 / "audit"
OUTROOT = Path("/workspace/pronoia_run")

MACRO = {"增长/就业数据意外", "通胀数据意外", "政策利率调整"}

# v6.1 难负样本：程序性/正面事件但后续实际大涨——case study 中模型误杀的模式
_HARD_NEG_RE = re.compile(r"中标|扭亏|预增|定增获通过|不向下修正|收购进展")


def is_hard_negative(ev: dict, lb: dict) -> bool:
    """事件文本含利好关键词，且后续实际大涨（模型易带『程序性公告→判空』先验误杀）。"""
    txt = str(ev.get("title") or "") + " " + str(ev.get("body") or "")[:300]
    if not _HARD_NEG_RE.search(txt):
        return False
    rets = [lb.get(k) for k in ("ret_t3", "ret_t7", "ret_t15")
            if isinstance(lb.get(k), (int, float))]
    cars = [lb.get(k) for k in ("car_t3", "car_t7")
            if isinstance(lb.get(k), (int, float))]
    return (bool(rets) and max(rets) > 0.05) or (bool(cars) and max(cars) > 0.03)


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
    ap.add_argument("--split-by", choices=("stratified", "time"), default="stratified",
                    help="stratified: (market, 宏观/非宏观) 分层随机；time: 按事件时间排序取尾部为 OOS（跨 regime 稳健性验证）")
    ap.add_argument("--oversample-hard-neg", type=int, default=0,
                    help="难负样本（中标/扭亏/预增+后续大涨）在 train 中额外复制份数（0=关闭）")
    ap.add_argument("--out-name", default="data_v6",
                    help="输出目录前缀，产出 {name}_train / {name}_test / {name}_split_meta.json")
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

    if args.split_by == "time":
        # 时间切分：按事件时间全局排序，尾部 test_ratio 为 OOS（跨 regime 验证）
        def date_key(row: tuple) -> str:
            ev = evs.get(row[0]) or {}
            return str(ev.get("event_date") or ev.get("event_time") or "")
        rows_sorted = sorted(rows, key=date_key)
        n_test = max(1, round(len(rows_sorted) * args.test_ratio))
        test_eids = [r[0] for r in rows_sorted[-n_test:]]
        train_eids = [r[0] for r in rows_sorted[:-n_test]]
    else:
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

    # v6.1 难负样本重采样：仅 train 复制，test 保持原样
    n_hard_neg = sum(1 for eid in train_eids
                     if is_hard_negative(evs.get(eid) or {}, lbs.get(eid) or {}))
    if args.oversample_hard_neg > 0:
        extra = [eid for eid in train_eids
                 if is_hard_negative(evs.get(eid) or {}, lbs.get(eid) or {})] * args.oversample_hard_neg
        train_eids = train_eids + extra
        print(f"[HARDNEG] 难负样本 {n_hard_neg} 条 ×{args.oversample_hard_neg + 1} → train={len(train_eids)}")
    else:
        print(f"[HARDNEG] 难负样本（未重采样）= {n_hard_neg}")

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

    train_dir, test_dir = out / f"{args.out_name}_train", out / f"{args.out_name}_test"
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
        "split_by": args.split_by,
        "oversample_hard_neg": args.oversample_hard_neg,
        "n_hard_neg_train": n_hard_neg,
        "train_market": mkt_dist(train_eids)[0], "test_market": mkt_dist(test_eids)[0],
        "train_type": mkt_dist(train_eids)[1], "test_type": mkt_dist(test_eids)[1],
        "test_ids": test_eids,
    }
    with open(out / f"{args.out_name}_split_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[DONE] train={n_train} test={n_test} → {out}")
    print(f"       train_market={meta['train_market']}")
    print(f"       test_market ={meta['test_market']}")
    print(f"       train_type  ={meta['train_type']}")
    print(f"       test_type   ={meta['test_type']}")


if __name__ == "__main__":
    main()
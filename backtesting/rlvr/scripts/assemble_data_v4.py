"""assemble_data_v4.py — 组装 PAPV v4 训练数据目录（在远程 GPU 机器上运行）。

合并三路数据 → /root/pronoia/data_v4/：
  · events_enriched.jsonl（事件正文）
  · labels.jsonl（K 线客观结算标签）
  · research_cache.jsonl = 统计上下文（market_ctx/benchmark_ctx/bucket_stats/
    vol_features/...） + Team v4 rationale（多窗口推理链）

只收 team v4 ok=true 且有 label 的事件（训练快照；采集进程继续追加不影响本目录）。

用法：
  /root/miniconda3/bin/python assemble_data_v4.py \
      --src /root/Pronoia/pronoia_run/data_v3 \
      --team-cache /root/Pronoia/pronoia_run/data_v3/audit/research_cache_team_v4.jsonl \
      --out /root/pronoia/data_v4
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(p: Path) -> list[dict]:
    rows = []
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
    ap.add_argument("--src", required=True, help="含 events_enriched/labels 的目录（采集源，权威）")
    ap.add_argument("--stat-cache", default=None,
                    help="统计上下文 research_cache.jsonl 路径（缺省用 --src/research_cache.jsonl）")
    ap.add_argument("--team-cache", required=True, help="research_cache_team_v4.jsonl")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.src)
    evs = read_jsonl(src / "events_enriched.jsonl")
    lbs = {str(r.get("event_id")): r for r in read_jsonl(src / "labels.jsonl")}
    stat_path = Path(args.stat_cache) if args.stat_cache else (src / "research_cache.jsonl")
    stats = {str(r.get("event_id")): r for r in read_jsonl(stat_path)}
    team = {}
    for r in read_jsonl(Path(args.team_cache)):
        if r.get("ok") and r.get("rationale"):
            team[str(r.get("event_id"))] = r

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out / "events_enriched.jsonl", "w", encoding="utf-8") as fe, \
         open(out / "labels.jsonl", "w", encoding="utf-8") as fl, \
         open(out / "research_cache.jsonl", "w", encoding="utf-8") as fr:
        for e in evs:
            eid = str(e.get("event_id") or "")
            if eid not in team or eid not in lbs:
                continue
            rc = dict(stats.get(eid) or {})
            rc["event_id"] = eid
            rc["rationale"] = team[eid]["rationale"]
            fe.write(json.dumps(e, ensure_ascii=False) + "\n")
            fl.write(json.dumps(lbs[eid], ensure_ascii=False) + "\n")
            fr.write(json.dumps(rc, ensure_ascii=False) + "\n")
            n += 1

    # 简报
    mkts: dict[str, int] = {}
    for e in evs:
        eid = str(e.get("event_id") or "")
        if eid in team and eid in lbs:
            mkts[str(e.get("market") or "?").upper()] = mkts.get(str(e.get("market") or "?").upper(), 0) + 1
    print(f"[DONE] 组装 {n} 条 → {out}")
    print(f"       market 分布: {mkts}")
    print(f"       源: events={len(evs)} labels={len(lbs)} stat_cache={len(stats)} team_v4_ok={len(team)}")


if __name__ == "__main__":
    main()

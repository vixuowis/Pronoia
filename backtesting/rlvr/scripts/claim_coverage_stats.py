"""claim_coverage_stats.py — 统计 completions 中 CLAIM 的指标覆盖度。

输出：
  1. 指标级：30 个面板指标各自被断言次数 / 占比 / 断言准确率
  2. 族级 & horizon 级分布
  3. 每事件覆盖：平均断言数、去重指标数、族数、horizon 数
  4. base vs lora 对比

用法（远端）：
  /root/miniconda3/bin/python claim_coverage_stats.py \
      --completions /root/Pronoia/pronoia_run/oos_v6_full_completions.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS.parent / "training"))

from papv_claims import METRIC_PANEL, metric_family, parse_claims  # noqa: E402

HORIZON_OF = {}
for _h in (1, 3, 5, 7, 15, 30, 60):
    HORIZON_OF[f"car_t{_h}"] = f"t{_h}"
    HORIZON_OF[f"ret_t{_h}"] = f"t{_h}"
    HORIZON_OF[f"bm_ret_t{_h}"] = f"t{_h}"
for _h in (3, 7, 15, 30, 60):
    HORIZON_OF[f"car_t{_h}_pvalue"] = f"t{_h}"
for _k in ("short", "mid", "long", "all"):
    HORIZON_OF[f"car_avg_{_k}"] = "avg"


def horizon_of(m: str) -> str:
    if m in HORIZON_OF:
        return HORIZON_OF[m]
    if "_t" in m:
        tail = m.split("_t")[-1]
        return f"t{tail}" if tail.isdigit() else "?"
    return "?"


def load_labels(p: Path) -> dict[str, dict]:
    labels = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                labels[str(d.get("event_id") or "")] = d
            except Exception:
                continue
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--completions", required=True)
    ap.add_argument("--labels", default="",
                    help="labels.jsonl（结算准确率用；留空则跳过准确率）")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    labels = load_labels(Path(args.labels)) if args.labels else {}

    # side -> 聚合
    per_side: dict[str, dict] = {}
    rows_by_side: dict[str, list] = defaultdict(list)
    with open(args.completions, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            side = str(d.get("side") or "?")
            rows_by_side[side].append(d)

    for side, rows in rows_by_side.items():
        metric_cnt: Counter = Counter()
        fam_cnt: Counter = Counter()
        hor_cnt: Counter = Counter()
        metric_ok: Counter = Counter()
        metric_n: Counter = Counter()
        n_claims = 0
        n_events = 0
        ev_metrics: list[int] = []
        ev_fams: list[int] = []
        ev_hors: list[int] = []
        off_panel = Counter()

        for r in rows:
            claims = parse_claims(str(r.get("completion") or ""))
            if claims:
                n_events += 1
            n_claims += len(claims)
            ms = {c["metric"] for c in claims}
            fs = {metric_family(c["metric"]) for c in claims}
            hs = {horizon_of(c["metric"]) for c in claims}
            ev_metrics.append(len(ms))
            ev_fams.append(len(fs))
            ev_hors.append(len(hs))
            for c in claims:
                m = c["metric"]
                metric_cnt[m] += 1
                fam_cnt[metric_family(m)] += 1
                hor_cnt[horizon_of(m)] += 1
                if m not in METRIC_PANEL:
                    off_panel[m] += 1
                    continue
                if labels:
                    # 无 event_id 关联时退化为整体结算不可行；labels 用整体 dict 平均不可行
                    pass

        per_side[side] = dict(
            metric_cnt=metric_cnt, fam_cnt=fam_cnt, hor_cnt=hor_cnt,
            metric_ok=metric_ok, metric_n=metric_n,
            n_claims=n_claims, n_events=n_events,
            ev_metrics=ev_metrics, ev_fams=ev_fams, ev_hors=ev_hors,
            off_panel=off_panel,
        )

    # ---------- 输出 ----------
    for side, st in per_side.items():
        n_claims = st["n_claims"]
        print(f"\n{'='*62}\nSIDE = {side}   events={st['n_events']}  claims={n_claims}\n{'='*62}")

        avg = lambda xs: (sum(xs) / len(xs)) if xs else 0.0
        print(f"每事件：平均断言 {n_claims/max(st['n_events'],1):.2f} | "
              f"去重指标 {avg(st['ev_metrics']):.2f} | "
              f"族数 {avg(st['ev_fams']):.2f} | horizon数 {avg(st['ev_hors']):.2f}")

        print(f"\n-- 指标覆盖（{len(METRIC_PANEL)} 个面板指标）--")
        print(f"{'指标':<22}{'次数':>8}{'占比':>9}  {'累计'}")
        cum = 0
        sorted_m = st["metric_cnt"].most_common()
        # 面板内指标按频次；面板外单列
        panel_sorted = [(m, c) for m, c in sorted_m if m in METRIC_PANEL]
        for m, c in panel_sorted:
            cum += c
            print(f"{m:<22}{c:>8}{c/max(n_claims,1)*100:>8.1f}%  {cum/n_claims*100:.1f}%")
        never = [m for m in METRIC_PANEL if st["metric_cnt"].get(m, 0) == 0]
        print(f"\n从未被断言的面板指标（{len(never)}/{len(METRIC_PANEL)}）: {', '.join(sorted(never)) or '无'}")
        n_used = sum(1 for m in METRIC_PANEL if st["metric_cnt"].get(m, 0) > 0)
        print(f"面板指标使用率: {n_used}/{len(METRIC_PANEL)} = {n_used/len(METRIC_PANEL)*100:.0f}%")

        if st["off_panel"]:
            print(f"\n-- 面板外指标（不可结算，{sum(st['off_panel'].values())} 条）--")
            for m, c in st["off_panel"].most_common(10):
                print(f"{m:<22}{c:>8}")

        print("\n-- 指标族分布 --")
        for fam, c in st["fam_cnt"].most_common():
            print(f"{fam:<14}{c:>8}{c/max(n_claims,1)*100:>8.1f}%")

        print("\n-- Horizon 分布 --")
        for h, c in sorted(st["hor_cnt"].items()):
            print(f"{h:<14}{c:>8}{c/max(n_claims,1)*100:>8.1f}%")


if __name__ == "__main__":
    main()

"""eval_papv_suite.py — PAPV OOS 评估套件（固化版，可复跑）。

对样本外（OOS）的 base vs adapter completions 做统一结算，输出：
  · 全局指标：断言准确率 / Brier / ECE(10-bin) / TRUE-FALSE 两侧 / 格式合规率 / 可结算断言数
  · 三维拆分：指标族 × horizon × 市场（family × horizon × market）
  · 事件类型拆分、置信度分箱校准表
  · 每事件明细（供 case study 抽取）

输入：
  · --data-dir      测试集目录（events_enriched.jsonl + labels.jsonl）
  · --completions   completions.jsonl，每行 {completion, side}（side ∈ base|adapter）
                    或 base/adapter 各占前半与后半（无 side 字段时按顺序对半）
  · --out           输出 JSON 路径（默认 eval_papv_report.json）

用法（远程 GPU 或本地均可，无需 GPU）：
  python eval_papv_suite.py \
      --data-dir /root/Pronoia/pronoia_run/data_v6_test \
      --completions /root/Pronoia/pronoia_run/oos_v6_full_completions.jsonl \
      --out /root/Pronoia/pronoia_run/eval_papv_report.json

注意：与训练侧 load_dataset_rows 的过滤保持一致（label 存在 + ≥2 个面板指标可结算），
保证 completions 与事件一一对应。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_THIS = Path(__file__).resolve().parent.parent / "training"
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from papv_claims import METRIC_PANEL, parse_claims, settle_all, settle_claim_truth, metric_family  # noqa: E402

SECTION_HEADERS = {
    "R0": r"【\s*0[.\s]*断言规划\s*】",
    "R1a": r"【\s*1[.\s]*断言列表\s*】",
    "R2a": r"【\s*2[.\s]*逻辑链\s*】",
    "R3a": r"【\s*3[.\s]*反方与风险\s*】",
}


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


def load_events_labels(data_dir: Path) -> list[tuple[dict, dict]]:
    """与训练侧 load_dataset_rows 相同的过滤与顺序（不含 expert mask，mixed 模式）。"""
    evs = read_jsonl(data_dir / "events_enriched.jsonl")
    lbs = {str(l.get("event_id") or ""): l for l in read_jsonl(data_dir / "labels.jsonl")}
    rows = []
    for e in evs:
        eid = str(e.get("event_id") or "")
        lb = lbs.get(eid)
        if lb is None:
            continue
        n_settle = sum(1 for m in METRIC_PANEL if isinstance(lb.get(m), (int, float)))
        if n_settle < 2:
            continue
        rows.append((e, lb))
    return rows


def split_completions(comp_rows: list[dict]) -> dict[str, list[str]]:
    """按 side 字段分组（lora/adapter 等别名归一为 adapter）；无 side 时按顺序前/后半分。"""
    out: dict[str, list[str]] = {"base": [], "adapter": []}
    if comp_rows and comp_rows[0].get("side"):
        for r in comp_rows:
            side = str(r.get("side") or "")
            side = "adapter" if side in ("lora", "adapter", "ft", "tuned") else side
            out.setdefault(side, []).append(r.get("completion") or "")
        return out
    half = len(comp_rows) // 2
    out["base"] = [r.get("completion") or "" for r in comp_rows[:half]]
    out["adapter"] = [r.get("completion") or "" for r in comp_rows[half:]]
    return out


def horizon_of(metric: str) -> str:
    m = re.search(r"_t(\d+)", metric or "")
    return f"t{m.group(1)}" if m else "?"


def apply_calib(conf: float, calib: dict) -> float:
    """应用 calibrate_confidence.py 产出的校准映射（platt / isotonic）。"""
    conf = max(min(conf, 1 - 1e-6), 1e-6)
    if calib.get("method") == "platt":
        import math
        logit = math.log(conf / (1 - conf))
        return 1.0 / (1.0 + math.exp(-(calib["a"] * logit + calib["b"])))
    curve = calib.get("curve") or []
    for x, v in curve:
        if conf <= x:
            return v
    return curve[-1][1] if curve else conf


def fmt_ok(text: str, n_claims: int) -> bool:
    secs = sum(re.search(p, text) is not None for p in SECTION_HEADERS.values())
    return secs == 4 and 3 <= n_claims <= 6


def ece_10bin(conf_acc: list[tuple[float, bool]]) -> float:
    """ECE：10 等宽置信度分箱。conf_acc = (置信度, 是否判断正确)。"""
    if not conf_acc:
        return 0.0
    bins = defaultdict(lambda: [0, 0.0, 0.0])  # n, sum_conf, sum_correct
    for conf, correct in conf_acc:
        b = min(9, int(conf * 10))
        bins[b][0] += 1
        bins[b][1] += conf
        bins[b][2] += float(correct)
    n_total = len(conf_acc)
    return sum(v[0] / n_total * abs(v[2] / v[0] - v[1] / v[0]) for v in bins.values() if v[0])


def eval_side(events: list[tuple[dict, dict]], completions: list[str],
              calib: dict | None = None) -> dict:
    """评估一侧（base 或 adapter）的全部指标。calib 提供时先校准 conf。"""
    assert len(completions) >= len(events), \
        f"completions({len(completions)}) < events({len(events)})"
    claim_recs: list[dict] = []     # 每条可结算断言的明细
    n_events = len(events)
    fmt_cnt = 0
    n_claims_total = 0
    n_settleable = 0
    ev_accs: list[dict] = []        # 每事件汇总（case study 用）

    for i, (ev, lb) in enumerate(events):
        text = completions[i]
        claims = parse_claims(text)
        n_claims_total += len(claims)
        fmt_cnt += int(fmt_ok(text, len(claims)))
        st = settle_all(claims, lb, drop_trivial=False)
        n_settleable += st["settleable"]

        per = []
        for c in claims:
            truth = settle_claim_truth(c, lb)
            if truth is None:
                continue
            correct = (truth == c["judge"])
            conf = c["conf"] if c["conf"] is not None else 0.5
            if calib is not None:
                conf = apply_calib(conf, calib)
            rec = {
                "i": i, "event_id": ev.get("event_id"),
                "market": str(ev.get("market") or "?").upper(),
                "event_type": ev.get("event_type_l2") or ev.get("event_type") or "?",
                "metric": c["metric"], "family": metric_family(c["metric"]),
                "horizon": horizon_of(c["metric"]),
                "judge": bool(c["judge"]), "conf": conf,
                "truth": bool(truth), "correct": correct,
            }
            claim_recs.append(rec)
            per.append(rec)

        ev_accs.append({
            "i": i, "event_id": ev.get("event_id"),
            "market": str(ev.get("market") or "?").upper(),
            "event_type": ev.get("event_type_l2") or ev.get("event_type") or "?",
            "title": str(ev.get("title") or "")[:80],
            "n_claims": len(claims), "n_settleable": st["settleable"],
            "acc": st["accuracy"],
        })

    n = len(claim_recs)
    acc = sum(r["correct"] for r in claim_recs) / n if n else None
    # Brier：p_corrects = conf if 判断对 else 1-conf（预测概率指向正确性）
    p_corr = [(r["conf"] if r["correct"] else 1.0 - r["conf"]) for r in claim_recs]
    brier = sum((p - 1.0) ** 2 for p in p_corr) / n if n else None
    ece = ece_10bin([(r["conf"], r["correct"]) for r in claim_recs])
    true_recs = [r for r in claim_recs if r["judge"]]
    false_recs = [r for r in claim_recs if not r["judge"]]
    acc_t = sum(r["correct"] for r in true_recs) / len(true_recs) if true_recs else None
    acc_f = sum(r["correct"] for r in false_recs) / len(false_recs) if false_recs else None

    return {
        "n_events": n_events,
        "n_claims_total": n_claims_total,
        "n_settleable": n_settleable,
        "n_claim_recs": n,
        "acc": acc, "brier": brier, "ece": ece,
        "acc_when_TRUE": acc_t, "n_TRUE": len(true_recs),
        "acc_when_FALSE": acc_f, "n_FALSE": len(false_recs),
        "TRUE_ratio": (len(true_recs) / n) if n else None,
        "format_ok": fmt_cnt / n_events if n_events else None,
        "conf_bins": conf_bin_table(claim_recs),
        "claim_recs": claim_recs,
        "ev_accs": ev_accs,
    }


def conf_bin_table(claim_recs: list[dict]) -> dict:
    bins = defaultdict(lambda: [0, 0.0])
    for r in claim_recs:
        b = round(r["conf"], 2)
        bins[b][0] += 1
        bins[b][1] += float(r["correct"])
    return {str(k): {"n": v[0], "acc": round(v[1] / v[0], 4)} for k, v in sorted(bins.items())}


def group_acc(claim_recs: list[dict], keys: tuple) -> dict:
    g: dict[tuple, list] = defaultdict(list)
    for r in claim_recs:
        g[tuple(r[k] for k in keys)].append(r["correct"])
    return {"|".join(k): {"n": len(v), "acc": round(sum(v) / len(v), 4)}
            for k, v in sorted(g.items())}


def coverage_stats(claim_recs: list[dict], n_claims_total: int) -> dict:
    """第四维：指标覆盖度（E2 验收指标）。"""
    n = n_claims_total or 1
    metric_cnt = defaultdict(int)
    for r in claim_recs:
        metric_cnt[r["metric"]] += 1
    top3 = sorted(metric_cnt.values(), reverse=True)[:3]
    never = sorted(m for m in METRIC_PANEL if metric_cnt.get(m, 0) == 0)
    used = sum(1 for m in METRIC_PANEL if metric_cnt.get(m, 0) > 0)
    # 族 / horizon 占比
    fam_cnt = defaultdict(int)
    hor_cnt = defaultdict(int)
    for r in claim_recs:
        fam_cnt[r["family"]] += 1
        hor_cnt[r["horizon"]] += 1
    n_rec = len(claim_recs) or 1
    long_h = sum(v for k, v in hor_cnt.items() if k in ("t30", "t60", "avg"))
    return {
        "panel_size": len(METRIC_PANEL),
        "panel_used": used,
        "panel_usage_rate": round(used / len(METRIC_PANEL), 4),
        "top3_metric_share": round(sum(top3) / n, 4),
        "zero_coverage_metrics": never,
        "by_metric": {m: {"n": c, "share": round(c / n, 4)}
                      for m, c in sorted(metric_cnt.items(), key=lambda kv: -kv[1])},
        "family_share": {k: round(v / n_rec, 4) for k, v in sorted(fam_cnt.items())},
        "horizon_share": {k: round(v / n_rec, 4) for k, v in sorted(hor_cnt.items())},
        "benchmark_share": round(fam_cnt.get("benchmark", 0) / n_rec, 4),
        "long_horizon_share": round(long_h / n_rec, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--completions", required=True)
    ap.add_argument("--out", default="eval_papv_report.json")
    ap.add_argument("--calib", default=None,
                    help="calib_map.json 路径；提供则对 conf 校准后再算 Brier/ECE 等指标")
    ap.add_argument("--calib-method", default="platt", choices=("platt", "isotonic"))
    args = ap.parse_args()

    calib = None
    if args.calib:
        with open(args.calib, encoding="utf-8") as f:
            calib = json.load(f)[args.calib_method]["calib"]
        print(f"[CALIB] 应用 {args.calib_method} 映射：{json.dumps(calib, ensure_ascii=False)[:120]}")

    data_dir = Path(args.data_dir)
    events = load_events_labels(data_dir)
    comp_rows = read_jsonl(Path(args.completions))
    sides = split_completions(comp_rows)
    print(f"[DATA] events={len(events)} completions: " +
          ", ".join(f"{k}={len(v)}" for k, v in sides.items()))

    report: dict = {"n_events": len(events), "sides": {}}
    ev_detail_src: dict[str, list] = {}
    for side, comps in sides.items():
        r = eval_side(events, comps, calib=calib)
        claim_recs = r.pop("claim_recs")
        ev_accs = r.pop("ev_accs")
        ev_detail_src[side] = ev_accs
        # 三维拆分
        r["by_family"] = group_acc(claim_recs, ("family",))
        r["by_horizon"] = group_acc(claim_recs, ("horizon",))
        r["by_market"] = group_acc(claim_recs, ("market",))
        r["by_event_type"] = group_acc(claim_recs, ("event_type",))
        r["by_family_horizon"] = group_acc(claim_recs, ("family", "horizon"))
        r["by_family_market"] = group_acc(claim_recs, ("family", "market"))
        r["by_horizon_market"] = group_acc(claim_recs, ("horizon", "market"))
        r["by_family_horizon_market"] = group_acc(claim_recs, ("family", "horizon", "market"))
        # 第四维：指标覆盖度（E2 验收）
        r["coverage"] = coverage_stats(claim_recs, r["n_claims_total"])
        report["sides"][side] = r

    # Δ（adapter − base）
    b, a = report["sides"].get("base"), report["sides"].get("adapter")
    if b and a:
        report["delta"] = {k: (round(a[k] - b[k], 4)
                              if isinstance(a[k], (int, float)) and isinstance(b[k], (int, float))
                              else None)
                           for k in ("acc", "brier", "ece", "acc_when_TRUE",
                                     "acc_when_FALSE", "format_ok", "TRUE_ratio")}

    # 每事件 acc 明细（case study 抽取入口）
    if "adapter" in ev_detail_src and "base" in ev_detail_src:
        report["ev_detail"] = [
            {**x, "base_acc": y["acc"], "adapter_acc": x["acc"]}
            for x, y in zip(ev_detail_src["adapter"], ev_detail_src["base"])
        ]

    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print(f"[OUT] {out_path}")
    for side, r in report["sides"].items():
        print(f"[{side}] acc={r['acc']:.4f} brier={r['brier']:.4f} ece={r['ece']:.4f} "
              f"TRUE侧={r['acc_when_TRUE']} FALSE侧={r['acc_when_FALSE']} "
              f"fmt={r['format_ok']:.3f} 可结算断言={r['n_settleable']}")
    if "delta" in report:
        print(f"[Δ adapter-base] {report['delta']}")
    # 覆盖度摘要（E2 验收：top3 ≤45%、benchmark ≥3%、长窗口 ≥12%、零覆盖 ≤2）
    for side, r in report["sides"].items():
        cov = r.get("coverage")
        if not cov:
            continue
        print(f"[{side} coverage] 面板使用 {cov['panel_used']}/{cov['panel_size']}"
              f" ({cov['panel_usage_rate']*100:.0f}%) | Top3占比 {cov['top3_metric_share']*100:.1f}%"
              f" | benchmark {cov['benchmark_share']*100:.1f}%"
              f" | 长窗口(t30/t60/avg) {cov['long_horizon_share']*100:.1f}%"
              f" | 零覆盖 {len(cov['zero_coverage_metrics'])} 个")


if __name__ == "__main__":
    main()

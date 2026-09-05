#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settle_forward_research.py - Settle research claims vs existing labels (Step 8).

Reuses labels_forward.jsonl (Step 3), only settles claims_forward_research.jsonl,
outputs settlement_report_research.jsonl + comparison summary (vs no-research baseline).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import defaultdict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "backtesting" / "rlvr" / "training"))
sys.path.insert(0, str(_PROJECT_ROOT / "backtesting" / "rlvr" / "training" / "remote_scripts"))

from papv_claims import settle_all  # noqa: E402

FORWARD_DIR = _PROJECT_ROOT / "pronoia_run" / "forward_test"
LABELS_FILE = FORWARD_DIR / "labels_forward.jsonl"
CLAIMS_RESEARCH = FORWARD_DIR / "claims_forward_research.jsonl"
CLAIMS_BASELINE = FORWARD_DIR / "claims_forward.jsonl"
REPORT_RESEARCH = FORWARD_DIR / "settlement_report_research.jsonl"


def load_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    return out


def settle_claims(claims_rows, labels_by_eid):
    report_rows = []
    total_claims = total_settleable = total_correct = 0
    by_horizon = defaultdict(lambda: {"settleable": 0, "correct": 0})
    by_family = defaultdict(lambda: {"settleable": 0, "correct": 0})
    by_window = defaultdict(lambda: {"settleable": 0, "correct": 0, "claims": 0})
    by_type = defaultdict(lambda: {"settleable": 0, "correct": 0, "claims": 0})

    for cr in claims_rows:
        eid = cr.get("event_id", "")
        claims = cr.get("claims", [])
        lb = labels_by_eid.get(eid, {})
        result = settle_all(claims, lb, drop_trivial=False)
        total_claims += len(claims)
        total_settleable += result["settleable"]
        total_correct += result["correct"]
        win = cr.get("_window", "?")
        etype = cr.get("event_type_l2", "?")
        by_window[win]["claims"] += len(claims)
        by_window[win]["settleable"] += result["settleable"]
        by_window[win]["correct"] += result["correct"]
        by_type[etype]["claims"] += len(claims)
        by_type[etype]["settleable"] += result["settleable"]
        by_type[etype]["correct"] += result["correct"]
        for s in result.get("settlements", []):
            h = s.get("horizon", "?")
            fam = s.get("family", "?")
            by_horizon[h]["settleable"] += 1
            by_family[fam]["settleable"] += 1
            if s.get("correct"):
                by_horizon[h]["correct"] += 1
                by_family[fam]["correct"] += 1
        report_rows.append({
            "event_id": eid,
            "symbol": cr.get("symbol"),
            "market": cr.get("market"),
            "event_date": cr.get("event_date"),
            "_window": win,
            "event_type_l2": etype,
            "n_claims": len(claims),
            "settleable": result["settleable"],
            "correct": result["correct"],
            "accuracy": (result["correct"] / result["settleable"]) if result["settleable"] else None,
        })

    stats = {
        "total_claims": total_claims,
        "total_settleable": total_settleable,
        "total_correct": total_correct,
        "overall_accuracy": (total_correct / total_settleable) if total_settleable else 0,
        "by_horizon": {h: dict(v) for h, v in sorted(by_horizon.items())},
        "by_family": {f: dict(v) for f, v in sorted(by_family.items())},
        "by_window": {w: dict(v) for w, v in sorted(by_window.items())},
        "by_type": {t: dict(v) for t, v in sorted(by_type.items())},
    }
    return report_rows, stats


def main():
    labels = load_jsonl(LABELS_FILE)
    labels_by_eid = {r["event_id"]: r for r in labels}
    print(f"[SETTLE] labels={len(labels)}", flush=True)

    claims_r = load_jsonl(CLAIMS_RESEARCH)
    n_cr = sum(len(c.get("claims", [])) for c in claims_r)
    print(f"[SETTLE] research claims rows={len(claims_r)} total_claims={n_cr}", flush=True)
    rep_r, stats_r = settle_claims(claims_r, labels_by_eid)
    with open(REPORT_RESEARCH, "w", encoding="utf-8") as f:
        for r in rep_r:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    claims_b = load_jsonl(CLAIMS_BASELINE)
    n_cb = sum(len(c.get("claims", [])) for c in claims_b)
    print(f"[SETTLE] baseline claims rows={len(claims_b)} total_claims={n_cb}", flush=True)
    rep_b, stats_b = settle_claims(claims_b, labels_by_eid)

    print("\n" + "=" * 60, flush=True)
    print("[COMPARE: no-research (baseline) vs with-research]", flush=True)
    print("=" * 60, flush=True)
    print(f"  baseline: claims={stats_b['total_claims']} "
          f"settleable={stats_b['total_settleable']} "
          f"correct={stats_b['total_correct']} "
          f"acc={stats_b['overall_accuracy']*100:.1f}%", flush=True)
    print(f"  research: claims={stats_r['total_claims']} "
          f"settleable={stats_r['total_settleable']} "
          f"correct={stats_r['total_correct']} "
          f"acc={stats_r['overall_accuracy']*100:.1f}%", flush=True)
    delta = stats_r["overall_accuracy"] - stats_b["overall_accuracy"]
    tag = "UP" if delta > 0 else ("DOWN" if delta < 0 else "FLAT")
    print(f"  delta accuracy = {delta*100:+.1f} pp ({tag})", flush=True)

    print("\n--- by window ---", flush=True)
    all_w = sorted(set(stats_b["by_window"]) | set(stats_r["by_window"]))
    for w in all_w:
        b = stats_b["by_window"].get(w, {"settleable": 0, "correct": 0, "claims": 0})
        r = stats_r["by_window"].get(w, {"settleable": 0, "correct": 0, "claims": 0})
        ba = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        ra = (r["correct"] / r["settleable"] * 100) if r["settleable"] else 0
        print(f"  T-{w:>3}: base {b['correct']}/{b['settleable']}={ba:5.1f}%  "
              f"research {r['correct']}/{r['settleable']}={ra:5.1f}%  "
              f"d={ra-ba:+5.1f}", flush=True)

    print("\n--- by horizon ---", flush=True)
    all_h = sorted(set(stats_b["by_horizon"]) | set(stats_r["by_horizon"]))
    for h in all_h:
        b = stats_b["by_horizon"].get(h, {"settleable": 0, "correct": 0})
        r = stats_r["by_horizon"].get(h, {"settleable": 0, "correct": 0})
        ba = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        ra = (r["correct"] / r["settleable"] * 100) if r["settleable"] else 0
        print(f"  t{h:>3}: base {b['correct']}/{b['settleable']}={ba:5.1f}%  "
              f"research {r['correct']}/{r['settleable']}={ra:5.1f}%  "
              f"d={ra-ba:+5.1f}", flush=True)

    print("\n--- by family ---", flush=True)
    all_f = sorted(set(stats_b["by_family"]) | set(stats_r["by_family"]))
    for f in all_f:
        b = stats_b["by_family"].get(f, {"settleable": 0, "correct": 0})
        r = stats_r["by_family"].get(f, {"settleable": 0, "correct": 0})
        ba = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        ra = (r["correct"] / r["settleable"] * 100) if r["settleable"] else 0
        print(f"  {f:>14}: base {b['correct']}/{b['settleable']}={ba:5.1f}%  "
              f"research {r['correct']}/{r['settleable']}={ra:5.1f}%  "
              f"d={ra-ba:+5.1f}", flush=True)

    print("\n--- by event_type ---", flush=True)
    all_t = sorted(set(stats_b["by_type"]) | set(stats_r["by_type"]))
    for t in all_t:
        b = stats_b["by_type"].get(t, {"settleable": 0, "correct": 0, "claims": 0})
        r = stats_r["by_type"].get(t, {"settleable": 0, "correct": 0, "claims": 0})
        ba = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        ra = (r["correct"] / r["settleable"] * 100) if r["settleable"] else 0
        print(f"  {t:>20}: base {b['correct']}/{b['settleable']}={ba:5.1f}%  "
              f"research {r['correct']}/{r['settleable']}={ra:5.1f}%  "
              f"d={ra-ba:+5.1f}", flush=True)

    cmp_path = FORWARD_DIR / "settlement_compare.json"
    with open(cmp_path, "w", encoding="utf-8") as f:
        json.dump({"baseline": stats_b, "research": stats_r,
                   "delta_accuracy": delta}, f, ensure_ascii=False, indent=2)
    print(f"\n[REPORT] research -> {REPORT_RESEARCH}", flush=True)
    print(f"[REPORT] compare   -> {cmp_path}", flush=True)


if __name__ == "__main__":
    main()

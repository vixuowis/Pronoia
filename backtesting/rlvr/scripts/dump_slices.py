"""dump_slices.py — 导出 by_family / by_horizon / by_family_horizon / conf_bins / coverage."""
import json

RUN = "/root/Pronoia/pronoia_run"

for tag in ("v62", "v61"):
    r = json.load(open(f"{RUN}/eval_papv_{tag}_t06_report.json"))
    a = r["sides"]["adapter"]
    b = r["sides"]["base"]
    print("=" * 70)
    print(f"### {tag} adapter")
    print("[by_family]")
    for k, v in a["by_family"].items():
        bk = b["by_family"].get(k, {})
        print(f"  {k:<12} n={v['n']:>5} acc={v['acc']:.3f}  (base {bk.get('acc', float('nan')):.3f})")
    print("[by_horizon]")
    for k, v in a["by_horizon"].items():
        bk = b["by_horizon"].get(k, {})
        print(f"  {k:<6} n={v['n']:>5} acc={v['acc']:.3f}  (base {bk.get('acc', float('nan')):.3f})")
    print("[by_family_horizon] (adapter)")
    for k, v in a["by_family_horizon"].items():
        if v["n"] >= 30:
            print(f"  {k:<16} n={v['n']:>5} acc={v['acc']:.3f}")
    print("[conf_bins adapter]")
    for k, v in a["conf_bins"].items():
        if v["n"] >= 20:
            print(f"  conf={k}: n={v['n']:>5} acc={v['acc']:.3f}")
    print("[coverage]")
    cov = a["coverage"]
    print("  family_share:", cov["family_share"])
    print("  horizon_share:", cov["horizon_share"])
    print("  top3_metric_share:", cov["top3_metric_share"],
          " benchmark:", cov["benchmark_share"],
          " long_h:", cov["long_horizon_share"],
          " zero_cov:", len(cov["zero_coverage_metrics"]))
    print("  by_metric top10:", list(cov["by_metric"].items())[:10])
    print("[by_event_type adapter]")
    for k, v in sorted(a["by_event_type"].items(), key=lambda kv: -kv[1]["n"]):
        bk = b["by_event_type"].get(k, {})
        print(f"  {k:<22} n={v['n']:>5} acc={v['acc']:.3f} (base {bk.get('acc', float('nan')):.3f})")

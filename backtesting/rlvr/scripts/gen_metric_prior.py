"""gen_metric_prior.py — 从 OOS completions 生成指标先验准确率表（B7 奖励打折用）。

输入：completions jsonl（[base×N, lora×N] 事件序）+ 对应 oos data_dir
输出：JSON {metric: {"acc": float, "n": int}}，仅保留 n >= --min-n 的指标；
      附带元信息（生成时间、来源、阈值）。

用法（远端）：
  /root/miniconda3/bin/python gen_metric_prior.py \
      --oos-dir pronoia_run/data_v6_test \
      --completions pronoia_run/oos_v6_full_completions.jsonl \
      --side lora --min-n 30 \
      --out pronoia_run/metric_prior_v6.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS.parent / "training"))
sys.path.insert(0, str(_THIS.parent / "training" / "remote_scripts"))

from papv_claims import METRIC_PANEL, metric_family, parse_claims, settle_claim  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos-dir", required=True)
    ap.add_argument("--completions", required=True)
    ap.add_argument("--side", default="lora", choices=("lora", "base", "both"),
                    help="用哪一侧结算（both = 合并样本量）")
    ap.add_argument("--min-n", type=int, default=30,
                    help="样本量阈值：n < min-n 的指标不入表（小样本噪声）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    spec = importlib.util.spec_from_file_location(
        "papv_train_remote", _THIS.parent / "training" / "remote_scripts" / "papv_train_remote.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("/root/Qwen3-8B")
    rows = mod.load_dataset_rows(Path(args.oos_dir), "mixed", 0, tok=tok)
    n = len(rows)
    print(f"[DATA] oos rows = {n}")

    recs = []
    with open(args.completions, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))

    sides = ("lora",) if args.side == "lora" else \
            ("base",) if args.side == "base" else ("base", "lora")
    ok: Counter = Counter()
    tot: Counter = Counter()
    used = 0
    for s in sides:
        side_recs = [r for r in recs if r.get("side") in (s, "adapter")][:n]
        if len(side_recs) != n:
            print(f"[WARN] {s}: {len(side_recs)} != {n}, skip")
            continue
        used += 1
        for r, row in zip(side_recs, rows):
            try:
                label = json.loads(row.get("_label_json") or "{}")
            except Exception:
                continue
            for c in parse_claims(str(r.get("completion") or "")):
                m = c["metric"]
                if m not in METRIC_PANEL:
                    continue
                res = settle_claim(c, label)
                if res is None:
                    continue
                tot[m] += 1
                ok[m] += int(res)
    if not used:
        raise SystemExit("no side data used")

    prior: dict[str, dict] = {}
    for m, t in tot.most_common():
        if t < args.min_n:
            continue
        prior[m] = {"acc": round(ok[m] / t, 4), "n": t}

    out = {
        "_meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": args.completions,
            "oos_dir": args.oos_dir,
            "sides": list(sides),
            "min_n": args.min_n,
        },
        "metrics": prior,
    }
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {args.out}  ({len(prior)} metrics, min_n={args.min_n})")

    # 摘要：弱指标（B7 打折候选）
    weak = {m: d for m, d in prior.items() if d["acc"] < 0.55}
    strong = {m: d for m, d in prior.items() if d["acc"] >= 0.75}
    print("\n弱指标（acc<0.55，B7 打折候选）:")
    for m, d in sorted(weak.items(), key=lambda kv: kv[1]["acc"]):
        print(f"  {m:<20} acc={d['acc']:.3f} n={d['n']}")
    print("\n强指标（acc>=0.75，可倾斜）:")
    for m, d in sorted(strong.items(), key=lambda kv: -kv[1]["acc"]):
        print(f"  {m:<20} acc={d['acc']:.3f} n={d['n']}")
    print(f"\n未入表（n<{args.min_n}）: "
          f"{sorted(set(tot) - set(prior))}")


if __name__ == "__main__":
    main()

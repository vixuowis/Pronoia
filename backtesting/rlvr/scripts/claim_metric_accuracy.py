"""claim_metric_accuracy.py — 按指标结算断言准确率（低覆盖指标值不值得补）。

completions 顺序 = [base×N（事件序）, lora×N（事件序）]，与
load_dataset_rows(oos_dir) 顺序一致，直接 zip 结算。

用法（远端）：
  /root/miniconda3/bin/python claim_metric_accuracy.py \
      --oos-dir pronoia_run/data_v6_test \
      --completions pronoia_run/oos_v6_full_completions.jsonl
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
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
    base_recs = [r for r in recs if r.get("side") == "base"][:n]
    lora_recs = [r for r in recs if r.get("side") in ("lora", "adapter")][:n]
    print(f"[DATA] completions base={len(base_recs)} lora={len(lora_recs)}")

    for side_name, side_recs in (("base", base_recs), ("lora", lora_recs)):
        if len(side_recs) != n:
            print(f"[WARN] {side_name}: {len(side_recs)} != {n}, skip")
            continue
        ok: Counter = Counter()
        tot: Counter = Counter()
        unsettleable = 0
        for r, row in zip(side_recs, rows):
            try:
                label = json.loads(row.get("_label_json") or "{}")
            except Exception:
                continue
            for c in parse_claims(str(r.get("completion") or "")):
                m = c["metric"]
                res = settle_claim(c, label) if m in METRIC_PANEL else None
                if res is None:
                    unsettleable += 1
                    continue
                tot[m] += 1
                ok[m] += int(res)

        print(f"\n{'='*66}\nSIDE = {side_name}   (不可结算断言 {unsettleable} 条)\n{'='*66}")
        print(f"{'指标':<20}{'n':>7}{'acc':>8}   族")
        for m, t in tot.most_common():
            acc = ok[m] / t if t else 0
            print(f"{m:<20}{t:>7}{acc:>8.3f}   {metric_family(m)}")


if __name__ == "__main__":
    main()

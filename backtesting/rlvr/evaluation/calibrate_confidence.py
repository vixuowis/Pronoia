"""calibrate_confidence.py — 保留集置信度校准（Platt / Isotonic）。

工作流（分离训练与校准）：
  1. 用「校准集」（保留集或 OOS 前半）的 (conf, correct) 对拟合映射；
  2. 输出 calib_map.json（映射参数 + 分箱查表）；
  3. eval_papv_suite.py --calib 应用后跑最终 OOS 结算。

用法：
  # 拟合并报告校准前后指标（fit 前半，eval 后半）
  python calibrate_confidence.py \
      --data-dir pronoia_run/data_v6_test \
      --completions pronoia_run/oos_v6_full_completions.jsonl \
      --side adapter --fit-ratio 0.5 \
      --out pronoia_run/calib_map.json

  # 校准后指标由 eval_papv_suite.py --calib 计算（见该脚本）
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from eval_papv_suite import (  # noqa: E402
    load_events_labels, split_completions, eval_side,
)


def fit_platt(pairs: list[tuple[float, bool]]) -> dict:
    """Platt scaling：logit(conf) 上的逻辑回归，闭式牛顿迭代。"""
    xs = [math.log(max(min(c, 1 - 1e-6), 1e-6) / (1 - max(min(c, 1 - 1e-6), 1e-6)))
          for c, _ in pairs]
    ys = [1.0 if ok else 0.0 for _, ok in pairs]
    a, b = 1.0, 0.0
    for _ in range(100):
        p = [1.0 / (1.0 + math.exp(-(a * x + b))) for x in xs]
        ga = sum((pi - yi) * xi for pi, yi, xi in zip(p, ys, xs))
        gb = sum(pi - yi for pi, yi in zip(p, ys))
        ha = sum(pi * (1 - pi) * xi * xi for pi, xi in zip(p, xs))
        hb = sum(pi * (1 - pi) * xi for pi, xi in zip(p, xs))
        hc = sum(pi * (1 - pi) for pi in p)
        det = ha * hc - hb * hb
        if abs(det) < 1e-12:
            break
        a -= (ga * hc - gb * hb) / det
        b -= (gb * ha - ga * hb) / det
    return {"method": "platt", "a": round(a, 6), "b": round(b, 6)}


def fit_isotonic(pairs: list[tuple[float, bool]], n_bins: int = 20) -> dict:
    """分箱保序回归：按 conf 分箱 → 箱内正确率 → 单调化（PAVA）。"""
    bins: dict[int, list[int]] = {}
    for c, ok in pairs:
        bins.setdefault(min(n_bins - 1, int(c * n_bins)), []).append(int(ok))
    xs, ws = [], []
    for k in sorted(bins):
        xs.append((k + 0.5) / n_bins)
        ws.append(sum(bins[k]) / len(bins[k]))
    # PAVA 单调化
    stack: list[list[float]] = []  # [value, weight, count]
    for x, w in zip(xs, ws):
        stack.append([w, 1.0, x])
        while len(stack) > 1 and stack[-1][0] < stack[-2][0]:
            v2, n2, x2 = stack.pop()
            v1, n1, x1 = stack.pop()
            n = n1 + n2
            stack.append([(v1 * n1 + v2 * n2) / n, n, (x1 * n1 + x2 * n2) / n])
    return {"method": "isotonic", "curve": [[round(x, 4), round(v, 4)] for v, n, x in stack]}


def apply_calib(conf: float, calib: dict) -> float:
    if calib["method"] == "platt":
        return 1.0 / (1.0 + math.exp(-(calib["a"] * math.log(max(min(conf, 1 - 1e-6), 1e-6)
                                                     / (1 - max(min(conf, 1 - 1e-6), 1e-6))) + calib["b"])))
    curve = calib["curve"]
    for x, v in curve:
        if conf <= x:
            return v
    return curve[-1][1]


def brier_ece(pairs: list[tuple[float, bool]]) -> tuple:
    n = len(pairs)
    brier = sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in pairs) / n
    bins: dict[int, list] = {}
    for c, ok in pairs:
        b = bins.setdefault(min(9, int(c * 10)), [0, 0.0, 0.0])
        b[0] += 1; b[1] += c; b[2] += float(ok)
    ece = sum(v[0] / n * abs(v[2] / v[0] - v[1] / v[0]) for v in bins.values())
    return round(brier, 4), round(ece, 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--completions", required=True)
    ap.add_argument("--side", default="adapter")
    ap.add_argument("--fit-ratio", type=float, default=0.5,
                    help="前 fit_ratio 事件拟合映射，其余评估校准效果")
    ap.add_argument("--out", default="calib_map.json")
    args = ap.parse_args()

    events = load_events_labels(Path(args.data_dir))
    comps = split_completions(
        [json.loads(l) for l in open(args.completions, encoding="utf-8") if l.strip()]
    )[args.side]
    print(f"[DATA] events={len(events)} side={args.side}")

    r = eval_side(events, comps)
    claim_recs = r["claim_recs"]
    n_fit = int(len(events) * args.fit_ratio)
    fit_pairs = [(c["conf"], c["correct"]) for c in claim_recs if c["i"] < n_fit]
    eval_pairs = [(c["conf"], c["correct"]) for c in claim_recs if c["i"] >= n_fit]
    print(f"[SPLIT] fit 断言={len(fit_pairs)}（前 {n_fit} 事件） eval 断言={len(eval_pairs)}")

    out = {"fit_n": len(fit_pairs), "eval_n": len(eval_pairs), "fit_ratio": args.fit_ratio}
    for name, fit in (("platt", fit_platt), ("isotonic", fit_isotonic)):
        calib = fit(fit_pairs)
        b0, e0 = brier_ece(eval_pairs)
        b1, e1 = brier_ece([(apply_calib(c, calib), ok) for c, ok in eval_pairs])
        out[name] = {"calib": calib, "before": {"brier": b0, "ece": e0},
                     "after": {"brier": b1, "ece": e1}}
        print(f"[{name}] Brier {b0}→{b1}  ECE {e0}→{e1}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OUT] {args.out}")


if __name__ == "__main__":
    main()

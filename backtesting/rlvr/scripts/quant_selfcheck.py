"""quant_selfcheck.py — Pronoia-RLVR §4.5 训练集 5 项定量自检。

5 项自检（任何一项 FAIL → 阻断训练，必须先修数据）：
  ✅ Q1 分层配额：Market × EventTypeL2 12 层实际比例 vs 评估集比例的 JS 散度 ≤ 0.02
  ✅ Q2 标签完整度：horizons_complete 比例 ≥ 0.90（即 90% 样本 5 主 horizon 全有效）
  ✅ Q3 RET↔CAR 一致性：t7 RET（事件后标的自身收益）与 CAR（相对基准超额）同号率 ≥ 0.70
  ✅ Q4 时间分布：2024-01 ~ 2026-06 样本覆盖 ≥ 18 个月（不能集中在某几个月）
  ✅ Q5 去重 & 泄漏：同评估集 event_id 交集 = 0；训练集内部重复率 = 0

输出：
    backtesting/rlvr/data/rlvr_train_v1_5000/selfcheck_report.json
    （含 PASS/FAIL 判定 + 每项详细数值）

用法：
    python3 backtesting/rlvr/scripts/quant_selfcheck.py \
        --train-events backtesting/rlvr/data/rlvr_train_v1_5000/events.jsonl \
        --train-labels backtesting/rlvr/data/rlvr_train_v1_5000/labels.jsonl \
        --eval-events  backtesting/events_cn_us_1000_v1.jsonl \
        --report       backtesting/rlvr/data/rlvr_train_v1_5000/selfcheck_report.json
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import sys
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from scene_match import ALL_SCENE_KEYS  # noqa: E402


THRESHOLDS = {
    "Q1_JS_DIVERGENCE_MAX": 0.02,
    "Q2_HORIZONS_COMPLETE_MIN": 0.90,
    "Q3_RET_CAR_AGREE_T7_MIN": 0.70,
    "Q4_MONTHS_COVERED_MIN": 18,
    "Q5_INTERNAL_DUP_MAX": 0,
    "Q5_EVAL_OVERLAP_MAX": 0,
}


def _read_jsonl(p: Path) -> list[dict]:
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception: continue
    return rows


def _layer_distribution(events: list[dict]) -> dict[tuple, float]:
    cnt = Counter((str(e.get("market") or "").upper(), str(e.get("event_type_l2") or "")) for e in events)
    total = max(1, sum(cnt.values()))
    dist = {}
    for k in ALL_SCENE_KEYS:
        dist[k] = cnt.get(k, 0) / total
    return dist


def _js_divergence(p: dict, q: dict) -> float:
    """Jensen-Shannon divergence（对称平滑版 KL）。∈ [0, ln2≈0.693]，越小越相似。"""
    keys = set(p.keys()) | set(q.keys())
    m = {k: 0.5 * (p.get(k, 0.0) + q.get(k, 0.0)) for k in keys}
    def _kl(a, b):
        s = 0.0
        for k in keys:
            ak = a.get(k, 0.0); bk = b.get(k, 1e-12)
            if ak > 0 and bk > 0:
                s += ak * math.log(ak / bk)
        return s
    return 0.5 * _kl(p, m) + 0.5 * _kl(q, m)


def run_checks(train_events: list[dict], train_labels: list[dict],
                eval_events: list[dict]) -> dict:
    results: dict = {"thresholds": THRESHOLDS, "pass_all": True}

    # ============ Q1：分层 JS 散度 ============
    train_dist = _layer_distribution(train_events)
    eval_dist  = _layer_distribution(eval_events)
    js_div = _js_divergence(train_dist, eval_dist)
    q1_pass = js_div <= THRESHOLDS["Q1_JS_DIVERGENCE_MAX"]
    results["Q1_layer_distribution"] = {
        "pass": q1_pass,
        "js_divergence": js_div,
        "threshold": THRESHOLDS["Q1_JS_DIVERGENCE_MAX"],
        "train_distribution": {f"{k[0]}|{k[1]}": round(v, 4) for k, v in train_dist.items()},
        "eval_distribution":  {f"{k[0]}|{k[1]}": round(v, 4) for k, v in eval_dist.items()},
    }
    if not q1_pass: results["pass_all"] = False

    # ============ Q2：horizons_complete 完整度 ============
    labels_map = {str(lb.get("event_id") or ""): lb for lb in train_labels}
    n_valid = 0; n_complete = 0
    for e in train_events:
        eid = str(e.get("event_id") or "")
        lb = labels_map.get(eid)
        if not lb: continue
        n_valid += 1
        if lb.get("horizons_complete"):
            n_complete += 1
    ratio = n_complete / max(1, n_valid)
    q2_pass = ratio >= THRESHOLDS["Q2_HORIZONS_COMPLETE_MIN"]
    results["Q2_horizons_complete"] = {
        "pass": q2_pass,
        "ratio": ratio,
        "n_complete": n_complete,
        "n_valid_labels": n_valid,
        "threshold": THRESHOLDS["Q2_HORIZONS_COMPLETE_MIN"],
    }
    if not q2_pass: results["pass_all"] = False

    # ============ Q3：RET↔CAR t7 同号率（事件后收益率 vs 相对超额收益）============
    agree = 0; total = 0
    for e in train_events:
        eid = str(e.get("event_id") or "")
        lb = labels_map.get(eid)
        if not lb: continue
        if isinstance(lb.get("ret_car_agree_t7"), bool):
            total += 1
            if lb["ret_car_agree_t7"]: agree += 1
    ratio = agree / max(1, total)
    q3_pass = (ratio >= THRESHOLDS["Q3_RET_CAR_AGREE_T7_MIN"]) and (total >= 100)
    results["Q3_ret_car_agree_t7"] = {
        "pass": q3_pass,
        "ratio": ratio,
        "agree_n": agree,
        "valid_n": total,
        "threshold": THRESHOLDS["Q3_RET_CAR_AGREE_T7_MIN"],
        "note": "n>=100 才有效；低于 70% 说明行情下载/复权路径异常",
    }
    if not q3_pass: results["pass_all"] = False

    # ============ Q4：月份覆盖 ============
    ym_counter = Counter()
    for e in train_events:
        dt = str(e.get("event_time") or e.get("event_date") or "")[:7]
        if dt and len(dt) == 7 and dt[4] == "-":
            ym_counter[dt] += 1
    months_covered = len(ym_counter)
    months_sorted = sorted(ym_counter.keys())
    q4_pass = months_covered >= THRESHOLDS["Q4_MONTHS_COVERED_MIN"]
    results["Q4_months_coverage"] = {
        "pass": q4_pass,
        "months_covered": months_covered,
        "threshold": THRESHOLDS["Q4_MONTHS_COVERED_MIN"],
        "span": f"{months_sorted[0]} ~ {months_sorted[-1]}" if months_sorted else "N/A",
        "monthly_count_top10": ym_counter.most_common(10),
    }
    if not q4_pass: results["pass_all"] = False

    # ============ Q5：去重 + 评估集无交集 ============
    # Q5a 内部重复率（按 symbol+date+type）
    dedup_keys = Counter()
    for e in train_events:
        sym = str(e.get("symbol") or "").strip()
        dt  = str(e.get("event_time") or e.get("event_date") or "")[:10]
        el2 = str(e.get("event_type_l2") or "").strip()
        dedup_keys[(sym, dt, el2)] += 1
    internal_dup_n = sum(v - 1 for v in dedup_keys.values() if v > 1)
    q5a_pass = internal_dup_n <= THRESHOLDS["Q5_INTERNAL_DUP_MAX"]

    # Q5b 评估集交集（按 event_id）
    eval_ids = {str(e.get("event_id") or "") for e in eval_events if e.get("event_id")}
    train_ids = [str(e.get("event_id") or "") for e in train_events if e.get("event_id")]
    overlap = set(train_ids) & eval_ids
    q5b_pass = len(overlap) <= THRESHOLDS["Q5_EVAL_OVERLAP_MAX"]

    q5_pass = q5a_pass and q5b_pass
    results["Q5_dedup_and_no_leakage"] = {
        "pass": q5_pass,
        "internal_duplicates": internal_dup_n,
        "internal_dup_threshold": THRESHOLDS["Q5_INTERNAL_DUP_MAX"],
        "eval_overlap_event_ids": sorted(list(overlap))[:20],
        "eval_overlap_n": len(overlap),
        "eval_overlap_threshold": THRESHOLDS["Q5_EVAL_OVERLAP_MAX"],
    }
    if not q5_pass: results["pass_all"] = False

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-events", required=True)
    ap.add_argument("--train-labels", required=True)
    ap.add_argument("--eval-events", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    te = _read_jsonl(Path(args.train_events))
    tl = _read_jsonl(Path(args.train_labels))
    ee = _read_jsonl(Path(args.eval_events))
    print(f"[INFO] train_events={len(te)} train_labels={len(tl)} eval_events={len(ee)}")

    report = run_checks(te, tl, ee)

    rep_path = Path(args.report)
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 终端打印摘要
    print("\n========== QUANT SELFCHECK ==========")
    for k in ["Q1_layer_distribution", "Q2_horizons_complete", "Q3_ret_car_agree_t7",
              "Q4_months_coverage", "Q5_dedup_and_no_leakage"]:
        r = report[k]
        status = "✅ PASS" if r["pass"] else "❌ FAIL"
        brief = ", ".join(f"{kk}={r[kk]}" for kk in r.keys()
                           if kk not in ("pass", "note", "train_distribution", "eval_distribution",
                                          "monthly_count_top10", "eval_overlap_event_ids"))
        print(f"  {status}  {k:<30}  {brief}")
    overall = "✅ ALL PASS (OK to proceed training)" if report["pass_all"] else "❌ FAIL (BLOCK training)"
    print(f"\n  >>> {overall}  <<<")
    print(f"[DONE] 完整报告 → {rep_path}")
    if not report["pass_all"]:
        import sys; sys.exit(1)


if __name__ == "__main__":
    main()

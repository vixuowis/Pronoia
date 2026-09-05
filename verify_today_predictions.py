#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_today_predictions.py — 2026-09-05 验证脚本（明日运行）。

流程：
  1. 从 akshare/yfinance 下载 events_today.jsonl 中每个事件截至明日收盘的 K 线
  2. 计算 RET/CAR/bm_ret/pvalue （t1/t3/t7/t15/t30/t60） — 写 labels_today.jsonl
  3. 用 labels 结算 claims_today.jsonl 中的所有断言 — 写 settlement_today.jsonl
  4. 输出汇总报告：准确率（按窗口、按 horizon、按类型拆分）

明日 09-05 收盘后执行：
    cd /root/Pronoia && /root/miniconda3/bin/python verify_today_predictions.py

（T+1 之外的 horizon 先显示「待验证」占位，后续多次运行会自动补齐。）
"""
from __future__ import annotations
import sys, json, datetime as dt, time
from pathlib import Path
from collections import defaultdict, Counter

sys.path.insert(0, "/root/Pronoia/backend")
sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training")
sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training/remote_scripts")

from app.event_backtest.labeller import (  # type: ignore
    _yf_ticker_for, _yf_benchmark_for,
    _fetch_yf_batch,
    _compute_cars_for_events,
    write_labels,
    load_events,
)
from papv_claims import settle_all  # noqa: E402

TODAY_DIR = Path("/root/Pronoia/pronoia_run/today_test")
EVENTS_FILE = TODAY_DIR / "events_today.jsonl"
CLAIMS_FILE = TODAY_DIR / "claims_today.jsonl"
LABELS_FILE = TODAY_DIR / "labels_today.jsonl"
REPORT_FILE = TODAY_DIR / "settlement_today.jsonl"
SUMMARY_FILE = TODAY_DIR / "summary_verification.json"


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


def pl(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def multi_download_klines(tickers, start, end, workers=16):
    """Wrapper: 下载 tickers 的 close pd.Series 到 dict[ticker] -> Series。"""
    sdt = dt.datetime.strptime(start, "%Y-%m-%d").date()
    edt = dt.datetime.strptime(end, "%Y-%m-%d").date()
    return _fetch_yf_batch(list(tickers), sdt, edt)


def main():
    today = dt.date.today()
    pl("=== PRONOIA TODAY VERIFICATION ===")
    pl(f"run date = {today}")

    events = load_events(str(EVENTS_FILE))
    claims_rows = load_jsonl(str(CLAIMS_FILE))
    pl(f"loaded events={len(events)} claims_rows={len(claims_rows)}")
    total_claims_pre = sum(len(c.get('claims', [])) for c in claims_rows)
    pl(f"claims total={total_claims_pre}")
    w_dist = dict(sorted(Counter(e['_window'] for e in events).items()))
    pl(f"window dist events: {w_dist}")

    # ---- 1. 构建 ticker 映射 ----
    asset_tickers = {}
    bm_tickers = {}
    for e in events:
        key = (e.event_id if hasattr(e, 'event_id') else e.get("event_id"),
               e.market if hasattr(e, 'market') else e.get("market"),
               e.symbol if hasattr(e, 'symbol') else e.get("symbol"))
        sym = key[1]
        mkt = key[1]
        bench = e.benchmark if hasattr(e, 'benchmark') else e.get("benchmark")
        try:
            asset_tickers[key] = _yf_ticker_for(sym, mkt, bench)
            bm_tickers[key] = _yf_benchmark_for(bench, mkt)
        except Exception as ex:
            pl(f"  ticker err for {key}: {ex}")
    ticker_set = set(asset_tickers.values()) | set(bm_tickers.values())
    pl(f"unique tickers: {len(ticker_set)}")

    # ---- 2. 下载 K 线 ----
    t0 = time.time()
    pl("Downloading K-lines...")
    hist_end = (today + dt.timedelta(days=3)).strftime("%Y-%m-%d")
    klines = multi_download_klines(list(ticker_set), start="2023-06-01", end=hist_end, workers=16)
    n_ok = sum(1 for v in klines.values() if v is not None and len(v) > 0)
    pl(f"K-line download: {n_ok}/{len(ticker_set)} tickers OK ({time.time()-t0:.0f}s)")

    # ---- 3. 计算 CARs ----
    cars_out, n_labeled = _compute_cars_for_events(events, klines, asset_tickers, bm_tickers)
    pl(f"CAR compute: {n_labeled}/{len(events)} events with labels")

    # ---- 4. 写 labels ----
    label_rows = write_labels(events, cars_out, str(LABELS_FILE), epsilon=0.005)
    pl(f"labels -> {LABELS_FILE} ({len(label_rows)} rows)")

    # ---- 5. 结算断言 ----
    pl("Loading claims & settling...")
    # write_labels 返回的是 list[dict] 还是 list[RawEvent]？按文档是 list[dict]
    if label_rows and isinstance(label_rows[0], dict):
        labels_by_eid = {r["event_id"]: r for r in label_rows}
    else:
        labels_by_eid = {}
        for r in label_rows:
            eid = r.event_id if hasattr(r, 'event_id') else r.get("event_id")
            if isinstance(r, dict):
                labels_by_eid[eid] = r
            else:
                try:
                    labels_by_eid[eid] = {k: (getattr(r, k, None) if not isinstance(r, dict) else r.get(k))
                                         for k in ["ret_t1","car_t1","bm_ret_t1","car_t1_pvalue",
                                                   "ret_t3","car_t3","bm_ret_t3","car_t3_pvalue",
                                                   "ret_t5","car_t5","bm_ret_t5","car_t5_pvalue",
                                                   "ret_t7","car_t7","bm_ret_t7","car_t7_pvalue",
                                                   "ret_t15","car_t15","bm_ret_t15","car_t15_pvalue",
                                                   "ret_t30","car_t30","bm_ret_t30","car_t30_pvalue",
                                                   "ret_t60","car_t60","bm_ret_t60","car_t60_pvalue",
                                                   "label_t1","label_t3","label_t5","label_t7",
                                                   "label_t15","label_t30","label_t60",
                                                   "car_avg_short","car_avg_mid","car_avg_long","car_avg_all"]}
                except Exception:
                    pass

    report_rows = []
    total_claims = total_settleable = total_correct = 0
    by_horizon = defaultdict(lambda: {"settleable": 0, "correct": 0, "pending": 0})
    by_family = defaultdict(lambda: {"settleable": 0, "correct": 0, "pending": 0})
    by_window = defaultdict(lambda: {"settleable": 0, "correct": 0, "pending": 0, "claims": 0})
    by_type = defaultdict(lambda: {"settleable": 0, "correct": 0, "pending": 0, "claims": 0})

    for cr in claims_rows:
        eid = cr.get("event_id", "")
        claims = cr.get("claims", [])
        lb = labels_by_eid.get(eid, {})
        result = settle_all(claims, lb, drop_trivial=False)
        total_claims += len(claims)
        total_settleable += result["settleable"]
        total_correct += result["correct"]
        pending = len(claims) - result["settleable"]
        win = cr.get("_window", "?")
        etype = cr.get("event_type_l2", "?")
        by_window[win]["claims"] += len(claims)
        by_window[win]["settleable"] += result["settleable"]
        by_window[win]["correct"] += result["correct"]
        by_window[win]["pending"] += pending
        by_type[etype]["claims"] += len(claims)
        by_type[etype]["settleable"] += result["settleable"]
        by_type[etype]["correct"] += result["correct"]
        by_type[etype]["pending"] += pending
        for s in result.get("settlements", []):
            h = s.get("horizon", "?")
            fam = s.get("family", "?")
            if s.get("correct") is None or s.get("truth") is None:
                by_horizon[h]["pending"] += 1
                by_family[fam]["pending"] += 1
                continue
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
            "pending": pending,
            "accuracy": (result["correct"] / result["settleable"]) if result["settleable"] else None,
        })

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        for r in report_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pl(f"settlement_report -> {REPORT_FILE} ({len(report_rows)} rows)")

    # ---- 6. 汇总报告 ----
    overall_acc = (total_correct / total_settleable * 100) if total_settleable else 0
    total_pending = total_claims - total_settleable

    print("\n" + "=" * 65)
    print(f"  PRONOIA TODAY VERIFICATION REPORT — run date {today}")
    print("=" * 65)
    print(f"  events             : {len(events)}")
    print(f"  claims             : {total_claims}")
    print(f"  settleable (today) : {total_settleable} ({total_settleable/max(total_claims,1)*100:.0f}% of claims)")
    print(f"  correct            : {total_correct}")
    print(f"  overall ACCURACY   : {overall_acc:.1f}%")
    print(f"  pending (no label) : {total_pending} (horizon尚未到结算日)")

    print("\n-- by window (事件 age window: T-X = X 日前的事件) --")
    for w in sorted(by_window.keys()):
        b = by_window[w]
        acc = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        print(f"  {w:>5}: claims={b['claims']:>3}  settleable={b['settleable']:>3}  "
              f"correct={b['correct']:>3}  acc={acc:5.1f}%  pending={b['pending']}")

    print("\n-- by horizon (结算horizon: tX = 事件后 X 交易日) --")
    for h in sorted(by_horizon.keys()):
        b = by_horizon[h]
        acc = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        print(f"  t{h:>3}: settleable={b['settleable']:>3}  correct={b['correct']:>3}  "
              f"acc={acc:5.1f}%  pending={b.get('pending',0)}")

    print("\n-- by event_type --")
    for t in sorted(by_type.keys()):
        b = by_type[t]
        acc = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        print(f"  {t:>20}: claims={b['claims']:>3}  settleable={b['settleable']:>3}  "
              f"correct={b['correct']:>3}  acc={acc:5.1f}%  pending={b['pending']}")

    print("\n-- by family (指标族) --")
    for f_ in sorted(by_family.keys()):
        b = by_family[f_]
        acc = (b["correct"] / b["settleable"] * 100) if b["settleable"] else 0
        print(f"  {f_:>14}: settleable={b['settleable']:>3}  correct={b['correct']:>3}  "
              f"acc={acc:5.1f}%  pending={b.get('pending',0)}")

    print("\n-- per-event accuracy (top & bottom 5) --")
    settled = [r for r in report_rows if r["settleable"] > 0]
    settled.sort(key=lambda r: (-(r["accuracy"] or 0), r["_window"]))
    for r in settled[:5]:
        print(f"  top: {r['_window']:>5} {r['market']} {r['symbol']:>8s} "
              f"{r['event_type_l2'][:8]:>8s}  "
              f"{r['correct']}/{r['settleable']}  acc={r['accuracy']*100:5.1f}%")
    if len(settled) > 10:
        for r in settled[-5:]:
            print(f"  bot: {r['_window']:>5} {r['market']} {r['symbol']:>8s} "
                  f"{r['event_type_l2'][:8]:>8s}  "
                  f"{r['correct']}/{r['settleable']}  acc={r['accuracy']*100:5.1f}%")

    stats = {
        "run_date": today.isoformat(),
        "n_events": len(events),
        "n_claims": total_claims,
        "n_settleable": total_settleable,
        "n_correct": total_correct,
        "n_pending": total_pending,
        "overall_accuracy": overall_acc / 100,
        "by_window": {k: dict(v) for k, v in by_window.items()},
        "by_horizon": {k: dict(v) for k, v in by_horizon.items()},
        "by_type": {k: dict(v) for k, v in by_type.items()},
        "by_family": {k: dict(v) for k, v in by_family.items()},
    }
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    pl(f"summary -> {SUMMARY_FILE}")
    print(f"\n[DONE]")


if __name__ == "__main__":
    main()

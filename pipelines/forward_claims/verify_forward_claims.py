#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_forward_claims.py — Pronoia-PAPV 前向断言验证（Step 3）。

流程：
  1. 从 events_forward.jsonl 加载事件
  2. 用 labeller 函数下载 K 线 + 计算 CAR/RET/bm_ret/pvalue（labels）
  3. 从 claims_forward.jsonl 加载模型断言
  4. 用 papv_claims.settle_all 结算断言 vs labels
  5. 输出 settlement_report.jsonl + 汇总统计

注意：前向测试中，近期事件（T-1/T-3）的长 horizon 尚无数据，
      settle_all 对 None label 自动跳过（不可结算），只结算已有数据的 horizon。
"""
from __future__ import annotations
import os, sys, json, math, time, datetime as dt, threading
from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---- 路径 ----
PRONIA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PRONIA / "backend"))
sys.path.insert(0, str(PRONIA / "backtesting" / "rlvr" / "training"))
sys.path.insert(0, str(PRONIA / "backtesting" / "rlvr" / "training" / "remote_scripts"))

# 不走沙箱代理
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

from app.event_backtest.labeller import (  # noqa: E402
    load_events, write_labels,
    _yf_ticker_for, _yf_benchmark_for,
    _ak_us_hist, _ak_cn_hist, _ak_cn_index_hist,
    _car, _market_model_car,
)
from papv_claims import parse_claims, settle_all, settle_claim, settle_claim_truth  # noqa: E402

FORWARD_DIR = PRONIA / "pronoia_run" / "forward_test"
EVENTS_FILE = FORWARD_DIR / "events_forward.jsonl"
CLAIMS_FILE = FORWARD_DIR / "claims_forward.jsonl"
LABELS_FILE = FORWARD_DIR / "labels_forward.jsonl"
REPORT_FILE = FORWARD_DIR / "settlement_report.jsonl"

HORIZONS = [(1, "t1"), (3, "t3"), (5, "t5"), (7, "t7"), (15, "t15"), (30, "t30"), (60, "t60")]


def pl(msg):
    line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def main():
    # ---- 1. 加载事件 ----
    events = load_events(str(EVENTS_FILE))
    pl(f"loaded {len(events)} events")
    mkt_cnt = Counter(e.market for e in events)
    pl(f"market: {dict(mkt_cnt)}")

    # ---- 2. 构建 ticker 映射 ----
    asset_tickers = {}
    bm_tickers = {}
    for e in events:
        asset_tickers[(e.event_id, e.market, e.symbol)] = _yf_ticker_for(e.symbol, e.market, e.benchmark)
        bm_tickers[(e.event_id, e.market, e.symbol)] = _yf_benchmark_for(e.benchmark, e.market)

    all_tickers = set(asset_tickers.values()) | set(bm_tickers.values())
    pl(f"unique tickers: {len(all_tickers)}")

    # ---- 3. 下载 K 线（分类：US / CN-asset / CN-index） ----
    earliest = min(e.event_date for e in events) - dt.timedelta(days=200)
    latest = max(e.event_date for e in events) + dt.timedelta(days=10)  # 到今天为止
    sd_iso = earliest.isoformat()
    ed_iso = latest.isoformat()
    pl(f"price window: {sd_iso} ~ {ed_iso}")

    closes_by_ticker: dict[str, object] = {}
    lock = threading.Lock()

    us_map, cn_asset_map, cn_index_map = {}, {}, {}
    for t in all_tickers:
        tl = t.lower()
        if len(tl) == 8 and tl[:2] in {"sh", "sz"} and tl[2:].isdigit():
            cn_index_map[t] = tl
            continue
        stripped = tl
        if stripped.endswith(".ss"): stripped = stripped[:-3]
        elif stripped.endswith(".sz"): stripped = stripped[:-3]
        if len(stripped) == 8 and stripped[:2] in {"sh", "sz"} and stripped[2:].isdigit():
            cn_index_map[t] = stripped
            continue
        if (t.endswith(".SS") or t.endswith(".SZ")) and len(t) == 9 and t[:6].isdigit():
            cn_asset_map[t] = t[:6]
            continue
        if len(t) == 6 and t.isdigit():
            cn_index_map[t] = t
            continue
        us_map[t] = t

    pl(f"classify: US={len(us_map)} CN-asset={len(cn_asset_map)} CN-index={len(cn_index_map)}")

    def dl_us(sym, canon):
        try:
            s = _ak_us_hist(sym, sd_iso, ed_iso)
            if s is not None and len(s) > 0:
                with lock: closes_by_ticker[canon] = s
                return True
            return False
        except Exception as ex:
            pl(f"  [WARN] US {sym}: {ex}")
            return False

    def dl_cn_asset(sym, canon):
        try:
            s = _ak_cn_hist(sym, sd_iso, ed_iso)
            if s is not None and len(s) > 0:
                with lock: closes_by_ticker[canon] = s
                return True
            return False
        except Exception as ex:
            pl(f"  [WARN] CN-asset {sym}: {ex}")
            return False

    def dl_cn_index(sym, canon):
        try:
            s = _ak_cn_index_hist(sym, sd_iso, ed_iso)
            if s is not None and len(s) > 0:
                with lock: closes_by_ticker[canon] = s
                return True
            return False
        except Exception as ex:
            pl(f"  [WARN] CN-index {sym}: {ex}")
            return False

    # Phase 1: US
    if us_map:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(dl_us, sym, canon): canon for canon, sym in us_map.items()}
            for f in as_completed(futs):
                f.result()
        pl(f"Phase US done in {time.time()-t0:.0f}s  cum={len(closes_by_ticker)}")

    # Phase 2: CN-asset
    if cn_asset_map:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=12) as ex:
            futs = {ex.submit(dl_cn_asset, sym, canon): canon for canon, sym in cn_asset_map.items()}
            for f in as_completed(futs):
                f.result()
        pl(f"Phase CN-asset done in {time.time()-t0:.0f}s  cum={len(closes_by_ticker)}")

    # Phase 3: CN-index
    if cn_index_map:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(dl_cn_index, sym, canon): canon for canon, sym in cn_index_map.items()}
            for f in as_completed(futs):
                f.result()
        pl(f"Phase CN-index done in {time.time()-t0:.0f}s  cum={len(closes_by_ticker)}")

    pl(f"Final close coverage: {len(closes_by_ticker)}/{len(all_tickers)}")

    # ---- 4. 计算 CARs ----
    pl("Computing CARs per event...")
    cars_out: dict = {}
    no_asset, no_bm = 0, 0
    for e in events:
        key = (e.event_id, e.market, e.symbol)
        at = asset_tickers[key]
        bt = bm_tickers[key]
        a_close = closes_by_ticker.get(at)
        b_close = closes_by_ticker.get(bt)
        rec: dict = {"asset_ticker": at, "benchmark_ticker": bt}
        for _, kn in HORIZONS:
            rec[kn] = None; rec[f"bm_{kn}"] = None
            rec[f"car_{kn}"] = None; rec[f"car_{kn}_tstat"] = None; rec[f"car_{kn}_pvalue"] = None
        if a_close is None: no_asset += 1
        if b_close is None: no_bm += 1
        for w, kn in HORIZONS:
            rec[kn] = _car(a_close, e.event_date, w, e.event_time_raw, e.market) if a_close is not None else None
            rec[f"bm_{kn}"] = _car(b_close, e.event_date, w, e.event_time_raw, e.market) if b_close is not None else None
            if a_close is not None and b_close is not None:
                car, ts, pv = _market_model_car(a_close, b_close, e.event_date, w, e.event_time_raw, e.market)
                rec[f"car_{kn}"] = car; rec[f"car_{kn}_tstat"] = ts; rec[f"car_{kn}_pvalue"] = pv
        cars_out[key] = rec

    if no_asset or no_bm:
        pl(f"[WARN] missing closes: asset={no_asset} benchmark={no_bm}")

    # ---- 5. 写 labels ----
    label_rows = write_labels(events, cars_out, str(LABELS_FILE), epsilon=0.005)
    pl(f"wrote {len(label_rows)} label rows -> {LABELS_FILE}")

    # label 覆盖率
    for h in ["t1", "t3", "t7", "t15", "t30", "t60"]:
        nv = sum(1 for r in label_rows if r.get(f"car_{h}") is not None)
        pl(f"  car_{h} coverage: {nv}/{len(label_rows)}")

    # ---- 6. 加载断言 + 结算 ----
    pl("Loading claims & settling...")
    claims_rows = [json.loads(l) for l in open(CLAIMS_FILE, encoding="utf-8")]
    labels_by_eid = {r["event_id"]: r for r in label_rows}

    all_settle = []
    per_event = []
    total_settleable = 0
    total_correct = 0
    total_claims = 0
    # 按 horizon / 族 / 窗口 统计
    by_horizon = defaultdict(lambda: {"settleable": 0, "correct": 0})
    by_family = defaultdict(lambda: {"settleable": 0, "correct": 0})
    by_window = defaultdict(lambda: {"settleable": 0, "correct": 0, "claims": 0})
    by_type = defaultdict(lambda: {"settleable": 0, "correct": 0, "claims": 0})

    for cr in claims_rows:
        eid = cr["event_id"]
        claims = cr["claims"]
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

        # 逐条断言详情
        for c in claims:
            truth = settle_claim_truth(c, lb)
            correct = settle_claim(c, lb)
            metric = c["metric"]
            # horizon
            import re
            hm = re.search(r"_t(\d+)", metric)
            h_key = f"t{hm.group(1)}" if hm else "other"
            # family
            from papv_claims import metric_family
            fam = metric_family(metric)
            if correct is not None:
                by_horizon[h_key]["settleable"] += 1
                by_horizon[h_key]["correct"] += int(correct)
                by_family[fam]["settleable"] += 1
                by_family[fam]["correct"] += int(correct)
            all_settle.append({
                "event_id": eid, "symbol": cr.get("symbol"), "window": win,
                "event_type": etype, "event_date": cr.get("event_date"),
                "metric": metric, "op": c["op"], "thr": c["thr"],
                "judge": c["judge"], "conf": c["conf"],
                "label_value": lb.get(metric),
                "truth": truth, "correct": correct,
            })

        per_event.append({
            "event_id": eid, "symbol": cr.get("symbol"), "window": win,
            "event_type": etype, "event_date": cr.get("event_date"),
            "n_claims": result["n_claims"], "settleable": result["settleable"],
            "correct": result["correct"],
            "accuracy": result["accuracy"],
            "n_horizons": result["n_horizons"], "n_families": result["n_families"],
        })

    # ---- 7. 写结算报告 ----
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        for r in all_settle:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pl(f"wrote {len(all_settle)} claim settlements -> {REPORT_FILE}")

    # ---- 8. 汇总 ----
    acc = (total_correct / total_settleable) if total_settleable else 0
    pl("=" * 60)
    pl("SETTLEMENT SUMMARY")
    pl("=" * 60)
    pl(f"events={len(claims_rows)}  claims={total_claims}  settleable={total_settleable}  "
       f"correct={total_correct}  accuracy={acc:.1%}")

    pl("\n--- by window ---")
    for w in ["T-1", "T-3", "T-7", "T-14", "T-30", "T-60"]:
        d = by_window.get(w)
        if d and d["settleable"]:
            pl(f"  {w}: {d['settleable']}/{d['claims']} settleable, "
               f"acc={d['correct']/d['settleable']:.1%}")
        elif d:
            pl(f"  {w}: {d['claims']} claims, 0 settleable")

    pl("\n--- by event type ---")
    for t, d in by_type.items():
        if d["settleable"]:
            pl(f"  {t}: {d['settleable']}/{d['claims']} settleable, "
               f"acc={d['correct']/d['settleable']:.1%}")

    pl("\n--- by horizon ---")
    for h in ["t1", "t3", "t5", "t7", "t15", "t30", "t60"]:
        d = by_horizon.get(h)
        if d and d["settleable"]:
            pl(f"  {h}: settleable={d['settleable']} acc={d['correct']/d['settleable']:.1%}")

    pl("\n--- by metric family ---")
    for fam, d in by_family.items():
        if d["settleable"]:
            pl(f"  {fam}: settleable={d['settleable']} acc={d['correct']/d['settleable']:.1%}")

    # Brier score (calibration)
    p_corrects = []
    for r in all_settle:
        if r["correct"] is not None and r["conf"] is not None:
            p = r["conf"] if r["judge"] else (1 - r["conf"])
            p_corrects.append(p if r["truth"] else (1 - p))
    if p_corrects:
        brier = sum((p - 1) ** 2 for p in p_corrects) / len(p_corrects)  # simplified
        pl(f"\n--- calibration ---")
        pl(f"  n_with_conf={len(p_corrects)}  brier~={brier:.4f}")

    pl("\n[DONE]")


if __name__ == "__main__":
    main()

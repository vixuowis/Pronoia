import os, sys, json, time, math, datetime as dt
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.insert(0, "/workspace/backend")
sys.path.insert(0, "/workspace")

import numpy as np
import pandas as pd
from app.event_backtest.labeller import (
    load_events, write_labels,
    _yf_ticker_for, _yf_benchmark_for,
    _ak_us_hist, _ak_cn_hist, _ak_cn_index_hist,
    _car, _market_model_car,
)

events_file = Path("/workspace/pronoia_run/data_v3/events.jsonl")
labels_file = Path("/workspace/pronoia_run/data_v3/labels.jsonl")
log_file = Path("/workspace/pronoia_run/logs/d2_label.log")
epsilon = 0.02

LOG_FP = open(log_file, "w", buffering=1)
def pl(msg):
    line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG_FP.write(line + "\n")

pl("=" * 60)
pl("D2 LABEL START — parallel version")

events = load_events(str(events_file))
pl(f"loaded {len(events)} events")
mkt_cnt = Counter(e.market for e in events)
pl(f"market: {dict(mkt_cnt)}")

# --- build ticker maps ---
asset_tickers = {}
bm_tickers = {}
for e in events:
    asset_tickers[(e.event_id, e.market, e.symbol)] = _yf_ticker_for(e.symbol, e.market, e.benchmark)
    bm_tickers[(e.event_id, e.market, e.symbol)] = _yf_benchmark_for(e.benchmark, e.market)

all_tickers = set(asset_tickers.values()) | set(bm_tickers.values())

earliest = min(e.event_date for e in events) - dt.timedelta(days=200)
latest = max(e.event_date for e in events) + dt.timedelta(days=150)
sd_iso = earliest.isoformat()
ed_iso = latest.isoformat()
pl(f"Close universe: {len(all_tickers)} tickers; window {sd_iso} ~ {ed_iso}")

closes_by_ticker: dict[str, pd.Series] = {}
lock = threading.Lock()

# classify
us_map: dict[str, str] = {}
cn_asset_map: dict[str, str] = {}
cn_index_map: dict[str, str] = {}

for t in all_tickers:
    tl = t.lower()
    if len(tl) == 8 and tl[:2] in {"sh", "sz"} and tl[2:].isdigit():
        cn_index_map[t] = tl
        continue
    stripped_suf = tl
    if stripped_suf.endswith(".ss"):
        stripped_suf = stripped_suf[:-3]
    elif stripped_suf.endswith(".sz"):
        stripped_suf = stripped_suf[:-3]
    if len(stripped_suf) == 8 and stripped_suf[:2] in {"sh", "sz"} and stripped_suf[2:].isdigit():
        cn_index_map[t] = stripped_suf
        continue
    if (t.endswith(".SS") or t.endswith(".SZ")) and len(t) == 9 and t[:6].isdigit():
        root = t[:6]
        if root.startswith(("51", "56", "58", "15")) or root.startswith(("399", "880", "881")):
            prefix = "sh" if root[0] in {"5", "8"} else "sz"
            if root.startswith("15") or root.startswith("399"):
                prefix = "sz"
            cn_index_map[t] = f"{prefix}{root}"
            continue
        cn_asset_map[t] = root
        continue
    if len(t) == 6 and t.isdigit():
        cn_index_map[t] = t
        continue
    us_map[t] = t

n_tot = len(all_tickers)
pl(f"分类: US={len(us_map)} CN-asset={len(cn_asset_map)} CN-index={len(cn_index_map)}  total={len(us_map)+len(cn_asset_map)+len(cn_index_map)}")

def pprint(prefix, idx, total, ok, phase):
    pl(f"[PROG] {prefix} {idx}/{total}  ok={ok}  cum={len(closes_by_ticker)}/{n_tot}  phase={phase}")

# ===== parallel download helpers =====
def download_us(sym, canonical, sem):
    try:
        s = _ak_us_hist(sym, sd_iso, ed_iso)
        if s is not None and len(s) > 0:
            with lock:
                closes_by_ticker[canonical] = s
            return True
        return False
    except Exception:
        return False

def download_cn_asset(sym, canonical, sem):
    try:
        s = _ak_cn_hist(sym, sd_iso, ed_iso)
        if s is not None and len(s) > 0:
            with lock:
                closes_by_ticker[canonical] = s
            return True
        return False
    except Exception:
        return False

def download_cn_index(sym, canonical, sem):
    try:
        s = _ak_cn_index_hist(sym, sd_iso, ed_iso)
        if s is not None and len(s) > 0:
            with lock:
                closes_by_ticker[canonical] = s
            return True
        return False
    except Exception:
        return False

# Phase 1: US (parallel)
if us_map:
    US_WORKERS = 8
    n_tot_us = len(us_map)
    t0 = time.time()
    ok_count = 0
    done_count = 0
    items = list(us_map.items())
    sem = threading.Semaphore(US_WORKERS)
    with ThreadPoolExecutor(max_workers=US_WORKERS) as ex:
        futs = {ex.submit(download_us, sym, canon, sem): canon for canon, sym in items}
        for f in as_completed(futs):
            if f.result():
                ok_count += 1
            done_count += 1
            if done_count % 10 == 0 or done_count == n_tot_us:
                pprint("Phase1-US", done_count, n_tot_us, ok_count, f"{time.time()-t0:.0f}s")
    pl(f"[INFO] Phase1 US DONE: ok={ok_count}/{n_tot_us} in {time.time()-t0:.0f}s  cum={len(closes_by_ticker)}/{n_tot}")

# Phase 2: CN-asset (parallel, 新浪限速，16 并发)
if cn_asset_map:
    CN_WORKERS = 16
    n_tot_cn = len(cn_asset_map)
    t0 = time.time()
    ok_count = 0
    done_count = 0
    items = list(cn_asset_map.items())
    sem = threading.Semaphore(CN_WORKERS)
    with ThreadPoolExecutor(max_workers=CN_WORKERS) as ex:
        futs = {ex.submit(download_cn_asset, sym, canon, sem): canon for canon, sym in items}
        for f in as_completed(futs):
            if f.result():
                ok_count += 1
            done_count += 1
            if done_count % 20 == 0 or done_count == n_tot_cn:
                pprint("Phase2-CN-asset", done_count, n_tot_cn, ok_count, f"{time.time()-t0:.0f}s")
    pl(f"[INFO] Phase2 CN-asset DONE: ok={ok_count}/{n_tot_cn} in {time.time()-t0:.0f}s  cum={len(closes_by_ticker)}/{n_tot}")

# Phase 3: CN-index/ETF (parallel)
if cn_index_map:
    CI_WORKERS = 12
    n_tot_ci = len(cn_index_map)
    t0 = time.time()
    ok_count = 0
    done_count = 0
    items = list(cn_index_map.items())
    sem = threading.Semaphore(CI_WORKERS)
    with ThreadPoolExecutor(max_workers=CI_WORKERS) as ex:
        futs = {ex.submit(download_cn_index, sym, canon, sem): canon for canon, sym in items}
        for f in as_completed(futs):
            if f.result():
                ok_count += 1
            done_count += 1
            if done_count % 10 == 0 or done_count == n_tot_ci:
                pprint("Phase3-CN-index", done_count, n_tot_ci, ok_count, f"{time.time()-t0:.0f}s")
    pl(f"[INFO] Phase3 CN-index DONE: ok={ok_count}/{n_tot_ci} in {time.time()-t0:.0f}s  cum={len(closes_by_ticker)}/{n_tot}")

pl(f"[INFO] Final close coverage: {len(closes_by_ticker)}/{n_tot} tickers")

# --- compute CARs (CPU fast) ---
pl("Computing CARs per event...")
out: dict[tuple, dict] = {}
no_asset = 0
no_bm = 0
HORIZONS: list[tuple[int, str]] = [(1, "t1"), (3, "t3"), (5, "t5"), (7, "t7"), (15, "t15"), (30, "t30"), (60, "t60")]
for e in events:
    key = (e.event_id, e.market, e.symbol)
    at = asset_tickers[key]
    bt = bm_tickers[key]
    a_close = closes_by_ticker.get(at)
    b_close = closes_by_ticker.get(bt)
    rec: dict = {"asset_ticker": at, "benchmark_ticker": bt}
    for _, kn in HORIZONS:
        rec[kn] = None
        rec[f"bm_{kn}"] = None
        rec[f"car_{kn}"] = None
        rec[f"car_{kn}_tstat"] = None
        rec[f"car_{kn}_pvalue"] = None
    if a_close is None:
        no_asset += 1
    if b_close is None:
        no_bm += 1
    for w, key_name in HORIZONS:
        r_a = _car(a_close, e.event_date, w, e.event_time_raw, e.market) if a_close is not None else None
        r_b = _car(b_close, e.event_date, w, e.event_time_raw, e.market) if b_close is not None else None
        rec[key_name] = r_a
        rec[f"bm_{key_name}"] = r_b
        if a_close is not None and b_close is not None:
            car, t_stat, p_value = _market_model_car(
                a_close, b_close, e.event_date, w, e.event_time_raw, e.market
            )
            rec[f"car_{key_name}"] = car
            rec[f"car_{key_name}_tstat"] = t_stat
            rec[f"car_{key_name}_pvalue"] = p_value
    out[key] = rec

if no_asset or no_bm:
    pl(f"[WARN] Missing closes: asset={no_asset}, benchmark={no_bm}")

# --- write labels ---
pl(f"Writing labels -> {labels_file}")
rows = write_labels(events, out, str(labels_file), epsilon=epsilon)

# --- stats ---
def _lc(name): return Counter(r[name] for r in rows if r.get(name))
for ln in ["label_t3", "label_t7", "label_t15", "label_t30", "label_t60",
           "label_avg_short", "label_avg_mid", "label_avg_long", "label_avg_all", "label_consensus66"]:
    dist = dict(_lc(ln))
    if dist:
        pl(f"[INFO] {ln} dist (eps={epsilon}): {dist}")
for h in ["t3", "t7", "t15", "t30", "t60"]:
    nv = sum(1 for r in rows if r.get(f"car_{h}") is not None)
    pl(f"[INFO] car_{h} coverage: {nv}/{len(rows)} ({nv*100//len(rows) if rows else 0}%)")

lab_t3 = _lc("label_t3")
cars_t3 = [r["car_t3"] for r in rows if r.get("car_t3") is not None]
pl(f"[INFO] label_t3: {dict(lab_t3)}")
if cars_t3:
    arr = np.array(cars_t3, dtype=float)
    pl(f"[INFO] car_t3 n={len(arr)} mean={arr.mean():.4f} std={arr.std():.4f} "
       f"p5={np.percentile(arr,5):.4f} p95={np.percentile(arr,95):.4f}")

pl(f"DONE_LABELS wrote {len(rows)} rows to {labels_file}")
LOG_FP.close()

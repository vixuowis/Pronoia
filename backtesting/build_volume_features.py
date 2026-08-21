"""给 events.jsonl 增加 4 维量价特征 + vol_regime（Pronoia-RLVR §3.2.2 / §1.3 schema）。

Strict as-of T0：四维计算只用到事件日 T0 及 T0 以前的 K 线。
复用 backend/app/event_backtest/labeller.py 的行情下载函数（CN akshare / US yfinance），
避免重新实现一套网络调用。

两种用法：
    # 1) 处理固定评估集 1000 条
    python3 backtesting/build_volume_features.py \
        --events backtesting/events_cn_us_1000_v1.jsonl \
        --out    backtesting/events_cn_us_1000_v1.jsonl

    # 2) 处理训练集（增量：只算 vol_t0_ratio 为 None 的）
    python3 backtesting/build_volume_features.py \
        --events data/rlvr_train_v1_5000/events.jsonl \
        --out    data/rlvr_train_v1_5000/events.jsonl \
        --only-missing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 把 backend / workspace 加到 sys.path，保证 import labeller 成功
WORKSPACE = Path(__file__).resolve().parent.parent  # /workspace
BACKEND   = WORKSPACE / "backend"
for _p in (str(BACKEND), str(WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.event_backtest.labeller import _ak_cn_hist, _ak_us_hist, _parse_date  # type: ignore
from app.skills.analyzers import compute_volume_regime                      # type: ignore


def _fetch_kline(symbol: str, market: str, event_date_iso: str,
                 lookback_cal_days: int = 120,
                 lookforward_cal_days: int = 2) -> list[dict]:
    """给单个标的拉 T0 - lookback ~ T0 的日 K。返回 list[dict(date,close,volume,high,low)]。"""
    import datetime as dt

    ed = dt.date.fromisoformat(event_date_iso)
    start = (ed - dt.timedelta(days=lookback_cal_days)).isoformat()
    end   = (ed + dt.timedelta(days=lookforward_cal_days)).isoformat()

    series = None
    if market.upper() == "CN":
        series = _ak_cn_hist(symbol, start, end)
    elif market.upper() == "US":
        series = _ak_us_hist(symbol.upper(), start, end)
    if series is None or len(series) == 0:
        return []
    # Series: index=date, value=close。这里只拿到 close，还没 volume。
    # 问题：labeller 里的 _ak_*_hist 返回的是 close series，不含 volume。
    # 解决方案：对 A 股重新调一次 get_stock_daily（akshare 的 stock_zh_a_daily 自带 volume）。
    return _fetch_kline_with_volume(symbol, market, start, end)


def _fetch_kline_with_volume(symbol: str, market: str, start_iso: str, end_iso: str) -> list[dict]:
    """含 volume 的 K 线下载：A 股直接走 akshare.stock_zh_a_daily（带 volume 列）；
    美股用 yfinance（默认含 Volume）。为了不依赖内部 atomic tool，这里独立实现。"""
    import datetime as dt
    import time

    mkt = market.upper()
    # ---- CN ----
    if mkt == "CN":
        try:
            import akshare as ak  # type: ignore
        except Exception:
            ak = None
        if ak is None:
            return []
        code = (symbol or "").strip()
        if not (len(code) == 6 and code.isdigit()):
            return []
        first = code[0]
        prefixed = f"sh{code}" if first in {"6", "9", "5"} else f"sz{code}"
        for attempt in range(3):
            try:
                time.sleep(0.5 + attempt * 0.3)
                df = ak.stock_zh_a_daily(symbol=prefixed, adjust="qfq")
                if df is None or len(df) == 0:
                    continue
                need_cols = {"date", "close", "volume"}
                if not need_cols.issubset(df.columns):
                    continue
                df["date"] = df["date"].astype(str).str[:10]
                sd = start_iso.replace("-", "")
                ed = end_iso.replace("-", "")
                sub = df[(df["date"] >= start_iso) & (df["date"] <= end_iso)]
                high = df["high"] if "high" in df.columns else df["close"]
                low  = df["low"]  if "low"  in df.columns else df["close"]
                rows = []
                for i, r in sub.iterrows():
                    rows.append({
                        "date":  str(r["date"])[:10],
                        "close": float(r["close"]),
                        "volume": float(r["volume"]),
                        "high":  float(r.get("high", r["close"])),
                        "low":   float(r.get("low",  r["close"])),
                    })
                return rows
            except Exception:
                continue
        return []

    # ---- US ----
    if mkt == "US":
        try:
            import yfinance as yf  # type: ignore
            import pandas as pd
        except Exception:
            return []
        try:
            end_pad = (dt.date.fromisoformat(end_iso) + dt.timedelta(days=3)).isoformat()
            df = yf.download(
                tickers=[symbol.upper()], start=start_iso, end=end_pad,
                auto_adjust=False, progress=False, threads=1,
            )
            if df is None or len(df) == 0:
                return []
            if isinstance(df, pd.DataFrame) and "Close" in df.columns:
                df.index = pd.to_datetime(df.index).date
                rows = []
                close_col = df["Close"]
                vol_col   = df["Volume"] if "Volume" in df.columns else None
                high_col  = df["High"]   if "High"   in df.columns else close_col
                low_col   = df["Low"]    if "Low"    in df.columns else close_col
                for idx in df.index:
                    c = float(close_col.loc[idx])
                    rows.append({
                        "date":  idx.isoformat() if hasattr(idx, "isoformat") else str(idx)[:10],
                        "close": c,
                        "volume": 0.0 if vol_col is None else float(vol_col.loc[idx]),
                        "high":  float(high_col.loc[idx]),
                        "low":   float(low_col.loc[idx]),
                    })
                return rows
        except Exception:
            return []
    return []


def process_events(events_in: Path, events_out: Path, only_missing: bool) -> dict:
    rows_in = []
    with open(events_in, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows_in.append(json.loads(line))
    print(f"[INFO] 读取 events: {len(rows_in)} 条  ← {events_in}")

    ok = 0; skip = 0; fail = 0
    for i, e in enumerate(rows_in):
        already = (
            e.get("vol_t0_ratio") is not None
            and e.get("vol_regime") is not None
        )
        if only_missing and already:
            skip += 1
            continue
        # event_time → YYYY-MM-DD；也兼容 event_date 字段
        event_iso = None
        for k in ("event_time", "event_date"):
            v = e.get(k)
            if v:
                d = _parse_date(v)
                if d is not None:
                    event_iso = d.isoformat()
                    break
        if event_iso is None:
            fail += 1
            continue
        sym = str(e.get("symbol") or "").strip()
        mkt = str(e.get("market") or "").upper()
        if not sym or mkt not in ("CN", "US"):
            fail += 1
            continue
        klines = _fetch_kline(sym, mkt, event_iso)
        feat = compute_volume_regime(klines, event_date=event_iso)
        if not feat.get("ok"):
            # degraded 兜底，不丢样本：给中性值
            e["vol_t0_ratio"]        = 1.0
            e["vol_pre5_ratio"]      = 1.0
            e["price_vol_diverge"]   = 0.0
            e["range_t0_normalized"] = 1.0
            e["vol_regime"]          = "NORMAL"
            e["vol_degraded"]        = True
            e["vol_degraded_reason"] = feat.get("reason", "kline fetch fail")
            fail += 1
        else:
            e["vol_t0_ratio"]        = feat["vol_t0_ratio"]
            e["vol_pre5_ratio"]      = feat["vol_pre5_ratio"]
            e["price_vol_diverge"]   = feat["price_vol_diverge"]
            e["range_t0_normalized"] = feat["range_t0_normalized"]
            e["vol_regime"]          = feat["vol_regime"]
            if feat.get("degraded"):
                e["vol_degraded"] = True
                e["vol_degraded_reason"] = feat.get("reason", "pre20 short history")
            ok += 1
        if (i + 1) % 10 == 0 or (i + 1) == len(rows_in):
            print(f"[PROG] {i+1}/{len(rows_in)}  ok={ok} skip={skip} fail={fail}  cum")

    # 写出（原地覆写允许，因为我们读进内存再写）
    tmp = events_out.with_suffix(events_out.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in rows_in:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, events_out)

    stats = {"total": len(rows_in), "ok": ok, "skip_already": skip, "fail": fail}
    print(f"[DONE] {stats}  → {events_out}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True, help="输入 events.jsonl 路径")
    ap.add_argument("--out",    required=True, help="输出 events.jsonl 路径（允许与输入相同=原地覆写）")
    ap.add_argument("--only-missing", action="store_true",
                    help="只处理 vol_t0_ratio 或 vol_regime 仍为空的样本（增量模式，默认 True 友好）")
    args = ap.parse_args()
    process_events(Path(args.events), Path(args.out), args.only_missing)


if __name__ == "__main__":
    main()

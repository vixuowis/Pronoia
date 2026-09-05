"""precompute_research_cache.py — Pronoia-RLVR 前置研究上下文预计算缓存。

背景（RLVR 训练范式）：
  Team Pipeline 前置部分（PLAN → FAN-OUT Experts：新闻检索/行情/财务/证据图/多情景推演）
  的产出对同一 event 在整个 RL 训练期间不变 → 离线预计算一次、缓存成中间数据。
  GRPO rollout 只做策略模型自身的 7 段 CoT 推理，不重复数据收集，大幅节省 GPU 时间。

Phase A：K 线缓存 —— 每个 (market, symbol) 只下载一次全量历史，落盘 JSON 复用。
Phase B：每事件 as-of T0 研究上下文 ——
          量价 4 维（补齐训练集缺失）+ 趋势/波动/均线位置/52周位置 + 基准相对强度。
Phase C：同类事件基率（严格防泄漏：只用 event_date < T0 的历史事件，expanding window）
          + 三情景推演（乐观/中性/悲观概率）+ 证据摘要（确定性 claim 列表，对应证据图节点）。

输出：
  research_cache.jsonl   # {event_id, vol_features, market_ctx, benchmark_ctx, bucket_stats, scenarios, evidence_items}
  events_enriched.jsonl  # events.jsonl 原字段 + 四维量价特征（vol_regime 等，供 reward/router 用）

说明：
  · 新闻上下文 = 事件记录本身（title/event_text 是 point-in-time 公告快照，离线无法回溯当日新闻流，
    且事件记录即 event_scout 的核心捕获物）；财务 point-in-time 快照留 v2（防止用现代财务数据
    对历史事件造成前视泄漏）。
  · 所有特征 strict as-of T0（T0 当日收盘/成交量计入——与 ret_tX 以 T0 收盘为基期、
    vol_t0_ratio 含 T0 成交量的口径一致）。

用法：
    python3 precompute_research_cache.py \
        --events  ../data/rlvr_train_v1_5000/events.jsonl \
        --labels  ../data/rlvr_train_v1_5000/labels.jsonl \
        --out-cache ../data/rlvr_train_v1_5000/research_cache.jsonl \
        --out-events ../data/rlvr_train_v1_5000/events_enriched.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_WORKSPACE = _THIS.parent.parent.parent  # /workspace
for _p in (str(_WORKSPACE / "backend"), str(_WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.skills.analyzers import compute_volume_regime  # type: ignore  # noqa: E402
sys.path.insert(0, str(_THIS.parent / "scripts"))
from scene_match import primary_horizon_for  # noqa: E402

CACHE_DIR = _THIS.parent.parent / "data" / "kline_cache"
HIST_START = "2023-06-01"   # 最早事件 2023-12，留 ~140 交易日预事件窗口
HIST_END = "2026-09-01"


# ======================================================================
# Phase A · K 线下载与缓存
# ======================================================================
def _cn_prefix(code: str) -> str:
    return f"sh{code}" if code[0] in {"6", "9", "5"} else f"sz{code}"


def _rows_from_df(df) -> list[dict]:
    df["date"] = df["date"].astype(str).str[:10]
    sub = df[(df["date"] >= HIST_START) & (df["date"] <= HIST_END)]
    rows = []
    for _, r in sub.iterrows():
        c = float(r["close"])
        rows.append({
            "date": str(r["date"])[:10],
            "close": c,
            "volume": float(r.get("volume", 0) or 0),
            "high": float(r.get("high", c) or c),
            "low": float(r.get("low", c) or c),
        })
    return rows


def _is_cn_etf(code: str) -> bool:
    return code[:2] in {"15", "51", "56", "58"}


def _download_cn(symbol: str, is_index: bool = False) -> list[dict]:
    import akshare as ak
    for attempt in range(4):
        try:
            time.sleep(0.4 + attempt * 0.4)
            if is_index:
                df = ak.stock_zh_index_daily(symbol=symbol)  # e.g. sh000300
            elif _is_cn_etf(symbol):
                # ETF：stock_zh_a_daily 不覆盖，走东财 fund_etf_hist_em（qfq 复权）
                df = ak.fund_etf_hist_em(symbol=symbol, period="daily",
                                         start_date=HIST_START.replace("-", ""),
                                         end_date=HIST_END.replace("-", ""),
                                         adjust="qfq")
            else:
                df = ak.stock_zh_a_daily(symbol=_cn_prefix(symbol), adjust="qfq")
            if df is None or len(df) == 0:
                continue
            return _rows_from_df(df)
        except Exception:
            continue
    return []


def _download_us(symbol: str) -> list[dict]:
    """美股/美 ETF：akshare stock_us_daily（新浪源，本沙箱可用；yfinance 不可达）。"""
    import akshare as ak
    code = str(symbol or "").strip().upper()
    for attempt in range(4):
        try:
            time.sleep(0.6 + attempt * 0.5)
            df = ak.stock_us_daily(symbol=code, adjust="qfq")
            if df is None or len(df) == 0 or "close" not in df.columns:
                continue
            return _rows_from_df(df)
        except Exception:
            continue
    return []


def load_kline(market: str, symbol: str, benchmark_mode: bool = False) -> list[dict]:
    """带磁盘缓存的 K 线加载。cache key = market_symbol（benchmark 用自身名）。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = f"{market}_{symbol}"
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    rows: list[dict] = []
    if market == "CN":
        rows = _download_cn(symbol, is_index=benchmark_mode)
    elif market == "US":
        rows = _download_us(symbol)
    if rows:
        cache_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"  [KLINE] {key}: {len(rows)} rows (downloaded & cached)")
    else:
        print(f"  [KLINE] {key}: FAILED (degraded)")
    return rows


# ======================================================================
# Phase B · as-of T0 市场上下文
# ======================================================================
def _upto(rows: list[dict], t0: str, include_t0: bool = True) -> list[dict]:
    out = []
    for r in rows:
        d = str(r["date"])[:10]
        if d < t0 or (include_t0 and d == t0):
            out.append(r)
    return out


def market_context(rows: list[dict], t0: str) -> dict:
    """标的 as-of T0 趋势/波动/位置上下文（含 T0 当日）。"""
    sub = _upto(rows, t0)
    n = len(sub)
    ctx: dict = {"n_days": n, "ok": n >= 25}
    if not ctx["ok"]:
        return ctx
    closes = [r["close"] for r in sub]
    c0 = closes[-1]

    def _pct(a: float, b: float) -> float:
        return round((a / b - 1.0) * 100.0, 2) if b else None

    # 动量
    ctx["mom_5d_pct"] = _pct(c0, closes[-6]) if n >= 6 else None
    ctx["mom_20d_pct"] = _pct(c0, closes[-21]) if n >= 21 else None
    # 20 日日收益波动（年化）
    if n >= 21:
        rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(n - 20, n)]
        mu = sum(rets) / len(rets)
        var = sum((x - mu) ** 2 for x in rets) / max(1, len(rets) - 1)
        ctx["vol_20d_ann_pct"] = round(math.sqrt(var) * math.sqrt(252) * 100.0, 1)
    # 均线位置
    for w in (5, 20, 60):
        if n >= w:
            ma = sum(closes[-w:]) / w
            ctx[f"pos_vs_ma{w}_pct"] = _pct(c0, ma)
    # 52 周（或可得窗口）高低位置
    lookback = closes[-min(n, 252):]
    hi, lo = max(lookback), min(lookback)
    ctx["pos_52w_pct"] = round((c0 - lo) / (hi - lo) * 100.0, 1) if hi > lo else None
    # 距 20 日高点回撤
    if n >= 21:
        hi20 = max(closes[-21:])
        ctx["drawdown_20d_pct"] = _pct(c0, hi20)
    return ctx


def benchmark_context(bench_rows: list[dict], sym_rows: list[dict], t0: str) -> dict:
    """基准行情 + 标的相对强度（都 as-of T0）。"""
    bctx = market_context(bench_rows, t0)
    out = {"benchmark_stats": bctx}
    sctx = market_context(sym_rows, t0)
    sm, bm = sctx.get("mom_20d_pct"), bctx.get("mom_20d_pct")
    if sm is not None and bm is not None:
        out["relative_strength_20d_pct"] = round(sm - bm, 2)
    return out


# ======================================================================
# Phase C · 同类事件基率（expanding window，严格 event_date < T0）
# ======================================================================
def bucket_base_rates(events: list[dict], labels: dict[str, dict]) -> dict[str, dict]:
    """对每条事件计算同类 (market, event_type_l2) 分桶的历史基率（只用更早事件）。

    返回 {event_id: bucket_stats}。bucket_stats:
      n_prior / p_up / p_down / p_neutral（按 primary horizon label）
      avg_car_primary_pct / p_car_pos / avg_ret_primary_pct
      insufficient=True 表示 n_prior < 20（基率参考价值低）
    """
    # 按日期排序的事件流（携带 label）
    stream = []
    for e in events:
        eid = str(e.get("event_id") or "")
        lb = labels.get(eid)
        if not lb:
            continue
        d = str(e.get("event_time") or e.get("event_date") or "")[:10]
        if not d:
            continue
        stream.append((d, e, lb))
    stream.sort(key=lambda x: x[0])

    # bucket → 历史累积记录
    buckets: dict[tuple, list] = defaultdict(list)
    result: dict[str, dict] = {}
    for d, e, lb in stream:
        eid = str(e["event_id"])
        mkt = str(e.get("market") or "").upper()
        el2 = str(e.get("event_type_l2") or "")
        key = (mkt, el2)
        ph = primary_horizon_for(mkt, el2)
        hist = buckets[key]

        # ---- 计算当前事件视角的基率（不含自己，也不含同日及之后）----
        n = len(hist)
        if n >= 5:
            ups = sum(1 for h in hist if h["dir"] == "up")
            downs = sum(1 for h in hist if h["dir"] == "down")
            neus = n - ups - downs
            car_vals = [h["car"] for h in hist if h["car"] is not None]
            ret_vals = [h["ret"] for h in hist if h["ret"] is not None]
            stats = {
                "n_prior": n,
                "p_up": round(ups / n, 3),
                "p_down": round(downs / n, 3),
                "p_neutral": round(neus / n, 3),
                "avg_car_primary_pct": round(sum(car_vals) / len(car_vals) * 100.0, 2) if car_vals else None,
                "p_car_pos": round(sum(1 for c in car_vals if c > 0) / len(car_vals), 3) if car_vals else None,
                "avg_ret_primary_pct": round(sum(ret_vals) / len(ret_vals) * 100.0, 2) if ret_vals else None,
                "insufficient": n < 20,
            }
        else:
            stats = {"n_prior": n, "insufficient": True}

        # ---- 把自己入桶（供更晚事件使用）----
        dir_gt = lb.get(f"label_{ph}")
        if not dir_gt:
            car = lb.get(f"car_{ph}")
            if isinstance(car, (int, float)):
                dir_gt = "up" if car > 0.01 else "down" if car < -0.01 else "neutral"
            else:
                dir_gt = "neutral"
        hist.append({
            "dir": str(dir_gt).lower(),
            "car": lb.get(f"car_{ph}") if isinstance(lb.get(f"car_{ph}"), (int, float)) else None,
            "ret": lb.get(f"ret_{ph}") if isinstance(lb.get(f"ret_{ph}"), (int, float)) else None,
        })
        result[eid] = stats
    return result


def build_scenarios(bucket_stats: dict, market_ctx: dict) -> dict:
    """三情景推演（乐观/中性/悲观）—— 基率 + 当前趋势微调，确定性生成。"""
    if bucket_stats.get("insufficient") and bucket_stats.get("n_prior", 0) < 5:
        return {"ok": False, "note": "同类事件历史样本不足，无可靠基率"}
    p_up = bucket_stats.get("p_up", 0.34)
    p_down = bucket_stats.get("p_down", 0.33)
    p_neu = bucket_stats.get("p_neutral", 0.33)
    # 趋势微调：20 日动量同向 ±3pp（封顶防极端）
    mom = market_ctx.get("mom_20d_pct")
    if isinstance(mom, (int, float)):
        adj = max(-0.03, min(0.03, mom / 100.0 * 0.5))
        p_up = max(0.02, min(0.92, p_up + adj))
        p_down = max(0.02, min(0.92, p_down - adj))
        p_neu = max(0.02, 1.0 - p_up - p_down)
    return {
        "ok": True,
        "bull": {"direction": "up", "prob": round(p_up, 3),
                 "avg_car": bucket_stats.get("avg_car_primary_pct")},
        "base": {"direction": "neutral", "prob": round(p_neu, 3)},
        "bear": {"direction": "down", "prob": round(p_down, 3)},
        "note": "概率=同类事件基率（expanding window, as-of T0）± 当前 20 日动量微调",
    }


def build_evidence_items(e: dict, vol_feat: dict, mctx: dict, bctx: dict,
                         scenarios: dict) -> list[dict]:
    """确定性证据摘要（对应 deep_researcher 证据图的核心节点，无 LLM 参与）。"""
    items = []

    def add(claim: str, direction: str, strength: str, source: str):
        items.append({"claim": claim, "direction": direction,
                      "strength": strength, "source": source})

    # 1) 事件类型先验
    if scenarios.get("ok"):
        add(f"同类事件基率：P(up)={scenarios['bull']['prob']}, P(down)={scenarios['bear']['prob']}",
            "up" if scenarios["bull"]["prob"] > scenarios["bear"]["prob"] + 0.05 else
            "down" if scenarios["bear"]["prob"] > scenarios["bull"]["prob"] + 0.05 else "neutral",
            "medium", "bucket_base_rates")
    # 2) 量价
    regime = vol_feat.get("vol_regime") or "NORMAL"
    diverge = vol_feat.get("price_vol_diverge")
    if isinstance(diverge, (int, float)):
        add(f"5 日量价背离值 {diverge:+.2f}（正=量价共振，负=背离）",
            "up" if diverge > 0.05 else "down" if diverge < -0.05 else "neutral",
            "medium", "volume_regime_analyzer")
    if regime == "HIGH":
        add(f"vol_regime=HIGH（T0 量比 {vol_feat.get('vol_t0_ratio', 'N/A')}），事件日显著放量，波动放大",
            "neutral", "medium", "volume_regime_analyzer")
    elif regime == "LOW":
        add("vol_regime=LOW，缩量运行，突破可靠性存疑", "neutral", "low", "volume_regime_analyzer")
    # 3) 趋势
    mom20 = mctx.get("mom_20d_pct")
    if isinstance(mom20, (int, float)):
        add(f"事件前 20 日动量 {mom20:+.2f}%", "up" if mom20 > 1.0 else "down" if mom20 < -1.0 else "neutral",
            "medium" if abs(mom20) > 5 else "low", "market_analyst")
    ma20 = mctx.get("pos_vs_ma20_pct")
    if isinstance(ma20, (int, float)):
        add(f"收盘价相对 MA20 {ma20:+.2f}%", "up" if ma20 > 0 else "down", "low", "market_analyst")
    pos52 = mctx.get("pos_52w_pct")
    if isinstance(pos52, (int, float)):
        add(f"52 周区间位置 {pos52:.0f}%（0=年内最低, 100=年内最高）",
            "down" if pos52 > 85 else "up" if pos52 < 15 else "neutral", "low", "market_analyst")
    # 4) 相对强度
    rs = bctx.get("relative_strength_20d_pct")
    if isinstance(rs, (int, float)):
        add(f"相对基准 20 日超额 {rs:+.2f}%", "up" if rs > 2 else "down" if rs < -2 else "neutral",
            "medium" if abs(rs) > 5 else "low", "market_analyst")
    return items


# ======================================================================
# 主流程
# ======================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out-cache", required=True)
    ap.add_argument("--out-events", required=True)
    args = ap.parse_args()

    events = [json.loads(l) for l in open(args.events, encoding="utf-8") if l.strip()]
    labels = {json.loads(l)["event_id"]: json.loads(l)
              for l in open(args.labels, encoding="utf-8") if l.strip()}
    print(f"[LOAD] events={len(events)} labels={len(labels)}")

    # ---- Phase A：K 线缓存（symbol 去重下载）----
    uniq: dict[tuple, int] = defaultdict(int)
    benchmarks: dict[str, int] = defaultdict(int)
    for e in events:
        uniq[(str(e.get("market") or "").upper(), str(e.get("symbol") or ""))] += 1
        bm = e.get("benchmark")
        if bm:
            benchmarks[str(bm)] += 1
    print(f"[PHASE-A] unique symbols={len(uniq)}, benchmarks={dict(benchmarks)}")

    klines: dict[tuple, list[dict]] = {}
    for i, ((mkt, sym), cnt) in enumerate(sorted(uniq.items()), 1):
        if not sym:
            continue
        klines[(mkt, sym)] = load_kline(mkt, sym)
        if i % 10 == 0:
            print(f"  [PHASE-A] {i}/{len(uniq)} symbols done")

    bench_klines: dict[str, list[dict]] = {}
    for bm in benchmarks:
        mkt = "CN" if str(bm).lower().startswith("sh") else "US"
        bench_klines[bm] = load_kline(mkt, bm, benchmark_mode=(mkt == "CN"))

    # ---- Phase C（先算基率，供 Phase B 情景用）----
    print("[PHASE-C] bucket base rates (expanding window, as-of T0)...")
    base_rates = bucket_base_rates(events, labels)
    print(f"[PHASE-C] done: {len(base_rates)} events")

    # ---- Phase B：每事件上下文 ----
    print("[PHASE-B] per-event as-of T0 context...")
    cache_rows = []
    vol_ok = vol_fail = 0
    for i, e in enumerate(events):
        eid = str(e.get("event_id") or "")
        t0 = str(e.get("event_time") or e.get("event_date") or "")[:10]
        mkt = str(e.get("market") or "").upper()
        sym = str(e.get("symbol") or "")
        bm = str(e.get("benchmark") or "")

        rows = klines.get((mkt, sym)) or []
        brows = bench_klines.get(bm) or []

        # 量价特征（as-of T0，含 T0 当日）
        sub = _upto(rows, t0)
        feat = compute_volume_regime(sub, event_date=t0)
        if feat.get("ok"):
            vol = {
                "vol_t0_ratio": feat["vol_t0_ratio"],
                "vol_pre5_ratio": feat["vol_pre5_ratio"],
                "price_vol_diverge": feat["price_vol_diverge"],
                "range_t0_normalized": feat["range_t0_normalized"],
                "vol_regime": feat["vol_regime"],
            }
            # 回写 events（供 reward/router/export 用）
            e.update(vol)
            vol_ok += 1
        else:
            vol = {"vol_t0_ratio": None, "vol_pre5_ratio": None,
                   "price_vol_diverge": None, "range_t0_normalized": None,
                   "vol_regime": "NORMAL", "degraded": True}
            e.update(vol)
            vol_fail += 1

        mctx = market_context(rows, t0)
        bctx = benchmark_context(brows, rows, t0) if brows else {"benchmark_stats": {"ok": False}}
        bstats = base_rates.get(eid, {"n_prior": 0, "insufficient": True})
        scen = build_scenarios(bstats, mctx)
        evid = build_evidence_items(e, vol, mctx, bctx, scen)

        cache_rows.append({
            "event_id": eid,
            "t0": t0,
            "vol_features": vol,
            "market_ctx": mctx,
            "benchmark_ctx": bctx,
            "bucket_stats": bstats,
            "scenarios": scen,
            "evidence_items": evid,
        })
        if (i + 1) % 500 == 0 or (i + 1) == len(events):
            print(f"  [PHASE-B] {i+1}/{len(events)}  vol_ok={vol_ok} vol_fail={vol_fail}")

    # ---- 写出 ----
    out_cache = Path(args.out_cache)
    out_cache.parent.mkdir(parents=True, exist_ok=True)
    with open(out_cache, "w", encoding="utf-8") as f:
        for r in cache_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.out_events, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # 摘要
    n_bench_ok = sum(1 for r in cache_rows if r["benchmark_ctx"].get("benchmark_stats", {}).get("ok"))
    n_scen_ok = sum(1 for r in cache_rows if r["scenarios"].get("ok"))
    n_mctx_ok = sum(1 for r in cache_rows if r["market_ctx"].get("ok"))
    print("\n[SUMMARY]")
    print(f"  research_cache rows : {len(cache_rows)}")
    print(f"  vol features ok     : {vol_ok} / {len(events)}")
    print(f"  market ctx ok       : {n_mctx_ok} / {len(events)}")
    print(f"  benchmark ctx ok    : {n_bench_ok} / {len(events)}")
    print(f"  scenarios ok        : {n_scen_ok} / {len(events)}")
    print(f"  → {out_cache}")
    print(f"  → {args.out_events}")


if __name__ == "__main__":
    main()

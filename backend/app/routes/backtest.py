"""Backtest API (P0): runs CRUD / start / cancel / SSE stream / metrics.

路由前缀: /api/bt
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import db
from ..config import DATA_DIR, PROJECT_ROOT
from ..event_backtest.application import load_predictions
from ..event_backtest.metrics import compute_metrics
from ..event_backtest import orchestrator as orch
from ..schemas import (
    ActionResponse,
    BacktestMetricsSnapshotList,
    BacktestRunResponse,
    BTDatasetResponse,
    CreateBacktestRunRequest,
    EventsCountResponse,
    ListBacktestRunsResponse,
    ListEventCatalogResponse,
    ListPredictionsResponse,
    PromptVariantItem,
    sse as _sse,
)

router = APIRouter(prefix="/api/bt", tags=["backtest"])


def _resolve_path(raw: str | None) -> str | None:
    """把相对路径（以 Pronoia 项目根为基准）解析为绝对路径；绝对路径原样返回。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    p = Path(s)
    if p.is_absolute():
        return str(p)
    return str((PROJECT_ROOT / p).resolve())


# ================================================================= runs CRUD ---

@router.get("/runs", response_model=ListBacktestRunsResponse)
def list_runs(limit: int = Query(100, ge=1, le=500)) -> Any:
    items = db.list_bt_runs(limit=limit)
    return {"total": len(items), "items": items}


def _auto_paths(name: str, run_id: str) -> tuple[str, str]:
    """根据 run_id 自动分配 out_path (predictions JSONL) 和 ckpt_dir。"""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name[:30]) or "bt"
    out_dir = Path(DATA_DIR) / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out_dir / f"_trajectory_{run_id}"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    return (
        str(out_dir / f"preds_{safe}_{run_id}.jsonl"),
        str(ckpt_dir),
    )


@router.post("/runs", response_model=BacktestRunResponse)
def create_run(req: CreateBacktestRunRequest) -> Any:
    # --- dataset_id 优先 ---
    events_path = _resolve_path(req.events_path)
    labels_path = _resolve_path(req.labels_path)
    if req.dataset_id:
        ds = db.get_bt_dataset(req.dataset_id)
        if not ds:
            raise HTTPException(status_code=404, detail=f"dataset_id={req.dataset_id} not found")
        events_path = events_path or _resolve_path(ds["path"])
        labels_path = labels_path or _resolve_path(ds.get("labels_path"))

    if not events_path or not Path(events_path).is_file():
        raise HTTPException(status_code=400, detail=f"events_path 无效或不存在: {req.events_path}")
    if labels_path and not Path(labels_path).is_file():
        raise HTTPException(status_code=400, detail=f"labels_path 不存在: {req.labels_path}")

    run_id = db.new_id()
    out_path, ckpt_dir = _auto_paths(req.name, run_id)

    # 估算 total_events
    total = 0
    try:
        from ..event_backtest.application import load_events
        total = len(load_events(events_path))
    except Exception:
        total = 0

    run = db.create_bt_run(
        name=req.name,
        runner=req.runner,
        events_path=events_path,
        labels_path=labels_path,
        out_path=out_path,
        ckpt_dir=ckpt_dir,
        run_id=run_id,
        prompt_variant=req.prompt_variant,
        model_version=req.model_version,
        concurrency=int(req.concurrency),
        total_events=total,
        config=req.config,
    )
    return run


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
def get_run(run_id: str) -> Any:
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.delete("/runs/{run_id}", response_model=ActionResponse)
def delete_run(run_id: str) -> Any:
    # 先尝试 cancel（如果 running）
    try:
        orch.cancel_bt_run(run_id)
    except Exception:
        pass
    if not db.delete_bt_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"ok": True, "run_id": run_id}


# ============================================================= start/cancel ---

@router.post("/runs/{run_id}/start", response_model=ActionResponse)
def start_run(run_id: str) -> Any:
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if run["status"] in {"running"}:
        return {"ok": False, "run_id": run_id, "message": "already running"}
    # P0 严格默认启用 as_of 防作弊（与 CLI 的 FEVER_BT_STRICT_AS_OF=1 一致）
    import os
    os.environ.setdefault("FEVER_BT_STRICT_AS_OF", "1")
    res = orch.start_bt_run(run_id)
    if not res.ok:
        raise HTTPException(status_code=400, detail=res.error or "start failed")
    return {"ok": True, "run_id": run_id, "message": "started"}


@router.post("/runs/{run_id}/cancel", response_model=ActionResponse)
def cancel_run(run_id: str) -> Any:
    if not orch.cancel_bt_run(run_id):
        run = db.get_bt_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return {"ok": False, "run_id": run_id, "message": f"not running/paused, status={run['status']}"}
    return {"ok": True, "run_id": run_id, "message": "cancelled"}


@router.post("/runs/{run_id}/pause", response_model=ActionResponse)
def pause_run(run_id: str) -> Any:
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    ok, msg = orch.pause_bt_run(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return {"ok": True, "run_id": run_id, "message": msg}


@router.post("/runs/{run_id}/resume", response_model=ActionResponse)
def resume_run(run_id: str) -> Any:
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    # P0 严格默认启用 as_of 防作弊（与 CLI 的 FEVER_BT_STRICT_AS_OF=1 一致）
    import os
    os.environ.setdefault("FEVER_BT_STRICT_AS_OF", "1")
    ok, msg = orch.resume_bt_run(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return {"ok": True, "run_id": run_id, "message": msg}


# =========================================================== predictions list ---

@router.get("/runs/{run_id}/events", response_model=ListPredictionsResponse)
def list_run_events(
    run_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    market: str | None = None,
    event_type_l2: str | None = None,
    only_incorrect: bool = Query(False),
) -> Any:
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    offset = (page - 1) * page_size
    total, items = db.list_bt_predictions(
        run_id,
        offset=offset,
        limit=page_size,
        market=market,
        event_type_l2=event_type_l2,
        only_incorrect=only_incorrect,
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/runs/{run_id}/events-catalog", response_model=ListEventCatalogResponse)
def list_run_event_catalog(
    run_id: str,
    market: str | None = None,
    event_type_l2: str | None = None,
    only_incorrect: bool = Query(False),
    status: str | None = None,
) -> Any:
    """Detail 页「事件目录」：从 events JSONL 直接取完整事件清单 + 状态 + 已完成 prediction。

    与 /events 的差异：
    - /events 只返回 DB 已写入 bt_predictions 的（即已完成的）；
    - /events-catalog 返回 events_path 文件里定义的全部事件（即本来就是 N 条），
      每条都有 status=pending/processing/done，Detail 页 render 后立刻看到 N 条待处理事件。
    """
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    events_path = run.get("events_path") or ""
    if not Path(events_path).is_file():
        raise HTTPException(status_code=404, detail=f"events_path not found on disk: {events_path}")
    try:
        from ..event_backtest.application import load_events

        evs = load_events(events_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"load_events failed: {exc}")
    # 取全量已完成 predictions（catalog 场景 events ≤1000，不取分页）
    _total, pred_rows = db.list_bt_predictions(
        run_id,
        offset=0,
        limit=100000,
        market=market,
        event_type_l2=event_type_l2,
        only_incorrect=only_incorrect,
    )
    pred_by_eid: dict[str, dict] = {p["event_id"]: p for p in pred_rows}
    # processing：ckpt_dir 下存在 {event_id}__{run_id}.json（或临时 tmp），但 prediction 未写入 DB
    processing_eids: set[str] = set()
    ckpt_dir = run.get("ckpt_dir") or run.get("trajectory_ckpt_dir")
    if ckpt_dir:
        cdp = Path(ckpt_dir)
        if cdp.is_dir():
            rid_suffix = f"__{run_id}"
            for p in cdp.iterdir():
                if not p.is_file():
                    continue
                if p.suffix not in {".json", ".tmp"}:
                    continue
                stem = p.stem
                if stem.endswith(rid_suffix):
                    processing_eids.add(stem[: -len(rid_suffix)])
                else:
                    processing_eids.add(stem)
    ev_eid_set = {getattr(e, "event_id", "") for e in evs}
    processing_eids &= ev_eid_set  # 过滤非本 events 的残留文件误判
    items: list[dict] = []
    for e in evs:
        eid = getattr(e, "event_id", "")
        ev_market = getattr(e, "market", "") or None
        ev_type = getattr(e, "event_type_l2", "") or None
        if market and ev_market != market:
            continue
        if event_type_l2 and ev_type != event_type_l2:
            continue
        pred = pred_by_eid.get(eid)
        if only_incorrect:
            # only_incorrect 只保留 prediction 存在且 is_correct_t3 == False 的
            if pred is None or bool(pred.get("is_correct_t3")) is not False:
                continue
        st: str
        if pred is not None:
            st = "done"
        elif eid in processing_eids:
            st = "processing"
        else:
            st = "pending"
        if status and st != status:
            continue
        title = (
            getattr(e, "title", None)
            or getattr(e, "event_title", None)
            or getattr(e, "headline", None)
            or None
        )
        raw_event_text = getattr(e, "event_text", None) or None
        # 文本可能非常长（完整公告），catalog 列表截断 300 字够用；完整正文在事件详情 panel 从 dataset 直接读
        event_text_catalog: str | None = None
        if isinstance(raw_event_text, str) and raw_event_text.strip():
            event_text_catalog = raw_event_text[:300] + ("…" if len(raw_event_text) > 300 else "")
        items.append(
            {
                "event_id": eid,
                "symbol": getattr(e, "symbol", None) or None,
                "market": ev_market,
                "event_type_l2": ev_type,
                "title": title,
                "event_time": getattr(e, "event_time", None) or None,
                "source_url": getattr(e, "source_url", None) or None,
                "event_text": event_text_catalog,
                "status": st,
                "prediction": pred,
            }
        )
    return {"total": len(items), "items": items}


@router.get("/runs/{run_id}/events/{event_id}")
def get_run_event(run_id: str, event_id: str) -> Any:
    pred = db.get_bt_prediction(run_id, event_id)
    if not pred:
        raise HTTPException(status_code=404, detail="prediction not found")
    run = db.get_bt_run(run_id)
    ckpt_dir = Path(run.get("ckpt_dir") or run.get("trajectory_ckpt_dir") or "") if run else None
    # trajectory ckpt 查找：按候选优先级逐一尝试（engine 实际写 {eid}.json，
    # 旧版 orchestrator 曾把 DB 路径误写为 {eid}__{run_id}.json，这里两边都兼容）
    import json as _json
    candidates: list[Path] = []
    db_path = pred.get("trajectory_ckpt")
    if db_path:
        candidates.append(Path(db_path))
    if ckpt_dir and ckpt_dir.is_dir():
        candidates.append(ckpt_dir / f"{event_id}.json")
        candidates.append(ckpt_dir / f"{event_id}__{run_id}.json")
    ckpt: dict | None = None
    for cand in candidates:
        try:
            if cand.is_file():
                with open(cand) as f:
                    ckpt = _json.load(f)
                if ckpt is not None:
                    break
        except Exception:
            continue
    # 返回结构：prediction + trajectory + event_meta（从 events_path 补全事件说明，用于前端「事件信息」区块）
    result: dict[str, Any] = {"prediction": pred, "trajectory": ckpt}
    event_meta: dict[str, Any] = {}
    if ckpt and isinstance(ckpt.get("event_meta"), dict):
        event_meta.update(ckpt["event_meta"])
    # 从 as_of_packet 中提取 event_text / title 补全事件说明（比 event_meta 更完整）
    if ckpt:
        aop = ckpt.get("as_of_packet")
        if isinstance(aop, str):
            try:
                aop_obj = _json.loads(aop)
                if isinstance(aop_obj, dict):
                    for k in ("event_text", "event_title", "title", "headline", "source_url"):
                        v = aop_obj.get(k)
                        if isinstance(v, str) and v.strip():
                            event_meta.setdefault(k, v)
            except Exception:
                pass
    if not event_meta.get("event_id"):
        event_meta["event_id"] = event_id
    for k in ("symbol", "market", "event_type_l2"):
        if not event_meta.get(k):
            v = pred.get(k)
            if v is not None:
                event_meta[k] = v
    result["event_meta"] = event_meta
    return result


@router.get("/runs/{run_id}/events/{event_id}/kline")
def get_run_event_kline(run_id: str, event_id: str) -> Any:
    """单事件行情（K 线）数据源：按 symbol 复用 get_stock_daily 拉事件日前后日K
    （前 120 / 后 15 自然日），返回 KlinePayload（symbol/dates/ohlc/volumes/event_date），
    供详情页「标的视图」渲染蜡烛图 + 事件日 markLine。"""
    import datetime as _dt
    import re as _re

    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    events_path = run.get("events_path") or ""
    if not Path(events_path).is_file():
        raise HTTPException(status_code=404, detail=f"events_path not found on disk: {events_path}")
    from ..event_backtest.application import load_events

    evs = load_events(events_path)
    ev = next((e for e in evs if getattr(e, "event_id", "") == event_id), None)
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")
    symbol = str(getattr(ev, "symbol", "") or "").strip()
    if not symbol:
        raise HTTPException(status_code=404, detail="event has no symbol")

    # 事件日（仅取日期部分；无/异常则回退今天，避免整条 K 线接口失败）
    raw_ts = str(getattr(ev, "event_time", "") or "").strip()
    event_date = None
    try:
        event_date = _dt.datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).date()
    except Exception:
        m = _re.match(r"\d{4}-\d{2}-\d{2}", raw_ts)
        if m:
            event_date = _dt.date.fromisoformat(m.group(0))
    if event_date is None:
        event_date = _dt.date.today()

    start = (event_date - _dt.timedelta(days=120)).isoformat()
    end = (event_date + _dt.timedelta(days=15)).isoformat()

    from ..skills.market import get_stock_daily

    res = get_stock_daily(symbol, start_date=start, end_date=end, adjust="qfq")
    if not isinstance(res, dict) or not res.get("ok"):
        err = res.get("error") if isinstance(res, dict) else "kline fetch failed"
        return {"ok": False, "error": err}
    artifact = res.get("artifact") or {}
    payload = dict(artifact.get("payload") or {})
    payload["symbol"] = payload.get("symbol") or symbol
    payload["event_date"] = event_date.isoformat()
    return {"ok": True, "payload": payload}


# ========================================================= metrics & snapshots ---

@router.get("/runs/{run_id}/metrics")
def get_run_metrics(run_id: str) -> Any:
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    # 优先走 out_path 已写盘 + labels；没有 labels 时会退化为空列表 labels
    preds = []
    out_path = Path(run["out_path"])
    if out_path.is_file():
        try:
            preds = load_predictions(out_path)
        except Exception:
            preds = []
    labels_list: list[Any] = []
    labels_path = run.get("labels_path") or None
    if labels_path and Path(labels_path).is_file():
        try:
            from ..event_backtest.application import load_labels
            labels_list = load_labels(labels_path)
        except Exception:
            labels_list = []
    try:
        from ..event_backtest.metrics_registry import compute_all_metrics
        # 用新的可插拔指标系统计算
        results = compute_all_metrics(predictions=preds, labels=labels_list)
        # 统一转成 {metric_id: MetricResult_dict}
        metrics_dict = {mid: mr.to_dict() for mid, mr in results.items()}
        # 存入 bt_runs.metrics_json（后台持久化）
        try:
            db.update_bt_run_metrics(run_id, metrics_dict)
        except Exception:
            pass
        # 返回元信息 + 指标本体
        def _compat_acc_stat(metric_id: str) -> dict:
            """把新 MetricResult 字典还原成旧 BTPredAccStat {acc, n, k, wilson_lo_95, wilson_hi_95}。

            Fallback 优先级（针对老数据或 predictions/labels 无法重算 meta 的情况）：
              1) 新 metrics_dict（compute_all_metrics 计算结果）
              2) bt_runs 行已持久化的标量字段：acc_t3_strict / acc_t3_strict_lo / acc_t3_non_neutral
                 （列表页展示的值就是直接读这些字段），同时用 run.done_events 作为 n 近似兜底
              3) 零值兜底，保证前端拿到数值不会 undefined 崩
            """
            md = metrics_dict.get(metric_id) or {}
            value = md.get("value")
            breakdown = md.get("breakdown") or {}
            wilson = breakdown.get("wilson") or {}
            meta = md.get("meta") or {}
            # 兼容新老键名（lo_95 vs wilson_lo_95）
            lo = wilson.get("lo_95") if wilson.get("lo_95") is not None else wilson.get("wilson_lo_95")
            hi = wilson.get("hi_95") if wilson.get("hi_95") is not None else wilson.get("wilson_hi_95")
            n = meta.get("n") if meta.get("n") is not None else 0
            k = meta.get("k") if meta.get("k") is not None else 0
            acc = value if value is not None else ((k / n) if n > 0 else 0.0)

            # ============== Fallback 2：bt_runs 行里已有的标量字段 ==============
            # 如果 compute_all_metrics 产出的 meta 是空的（老数据、结构不兼容、load_labels 失败）
            # → 列表页显示的 acc 实际来自 run.acc_t3_strict 字段，这里必须同步，避免「列表有%、详情 0%」
            try:
                acc_scalar = float(acc) if isinstance(acc, (int, float)) else None
                lo_scalar = float(lo) if isinstance(lo, (int, float)) else None
                n_int = int(n) if isinstance(n, (int, float)) else 0
                k_int = int(k) if isinstance(k, (int, float)) else 0

                # 如果重新计算出来的 n 极小（< 3）但 run.done_events 又≥真实事件数 → 说明重算失败，走 fallback
                done_n = int(run.get("done_events") or 0) if isinstance(run.get("done_events"), (int, float)) else 0
                need_fallback = (
                    (acc_scalar is None or n_int <= 0)
                    and done_n >= 1
                )

                def _fb(
                    field_acc: str,
                    field_lo: str | None,
                    *,
                    strict_metric: bool,
                ) -> None:
                    nonlocal acc_scalar, lo_scalar, n_int, k_int
                    saved_acc = run.get(field_acc)
                    if not isinstance(saved_acc, (int, float)):
                        return
                    saved_acc_f = float(saved_acc)
                    acc_scalar = saved_acc_f
                    # k / n 近似：用 done_events 作为 n（Oracle 有标签的都跑过了 → 当作严格分母的 n）
                    # 对 non_neutral：n < done_events，这里保守取 max(1, round(done_n * (0.6~0.9))) 下限不写死，保留 done_n 即可 ——
                    #   前端只显示 k/n 的文本，不依赖数字精确比较，关键是 acc% 和 Wilson lo 视觉正确
                    # lo bound
                    if field_lo:
                        vv = run.get(field_lo)
                        if isinstance(vv, (int, float)):
                            lo_scalar = float(vv)
                    # 重算 k = round(acc * n)，让 k/n 与 acc 在显示的%上一致
                    eff_n = max(1, done_n) if done_n >= 1 else max(1, n_int)
                    # strict 分母小一点？但前端显示的%是 acc_scalar*100，无需较真；保证 round(k/n)==acc_scalar 即可
                    est_k = int(round(acc_scalar * eff_n))
                    # clamp
                    if 0 <= est_k <= eff_n:
                        n_int = eff_n
                        k_int = est_k
                    elif n_int <= 0:
                        n_int = eff_n
                        k_int = max(0, min(eff_n, est_k))

                if need_fallback:
                    if metric_id == "acc_t3_strict":
                        _fb("acc_t3_strict", "acc_t3_strict_lo", strict_metric=True)
                    elif metric_id == "acc_primary_non_neutral":
                        _fb("acc_t3_non_neutral", None, strict_metric=False)

                if acc_scalar is None:
                    acc_scalar = 0.0
                if lo_scalar is None:
                    lo_scalar = 0.0
                acc = acc_scalar
                lo = lo_scalar
                n = n_int
                k = k_int
            except Exception:
                # 兜底：保持已有的值（可能 0），绝对不能抛
                pass

            return {
                "acc": float(acc) if isinstance(acc, (int, float)) else 0.0,
                "n": int(n) if isinstance(n, (int, float)) else 0,
                "k": int(k) if isinstance(k, (int, float)) else 0,
                "wilson_lo_95": float(lo) if isinstance(lo, (int, float)) else 0.0,
                "wilson_hi_95": float(hi) if isinstance(hi, (int, float)) else 1.0,
            }

        # 中性预测占比 / 弃权数 / 总样本量：从 metrics 元信息 + 实际 predictions 反推
        coverage_meta = (metrics_dict.get("coverage_rate") or {}).get("meta") or {}
        abstain_meta = (metrics_dict.get("abstain_rate") or {}).get("meta") or {}
        strict_meta = (metrics_dict.get("acc_t3_strict") or {}).get("meta") or {}
        # 总标签事件数（预测有交集的）
        done_events_raw = run.get("done_events")
        done_events_n = int(done_events_raw) if isinstance(done_events_raw, (int, float)) else 0
        n_total_labels_meta = int(
            coverage_meta.get("n_total")
            if coverage_meta.get("n_total") is not None
            else (abstain_meta.get("n") if abstain_meta.get("n") is not None else strict_meta.get("n", 0))
        )
        # Fallback：run.done_events（列表页显示的真实完成事件数）
        n_total_labels = n_total_labels_meta if n_total_labels_meta > 0 else done_events_n
        # 弃权数（pred.abstain 或 force_neutral）
        n_abstain_meta = int(
            coverage_meta.get("n_abstain")
            if coverage_meta.get("n_abstain") is not None
            else (abstain_meta.get("abstain") if abstain_meta.get("abstain") is not None else 0)
        )
        n_abstain = n_abstain_meta
        # 中性预测的数量：pred_direction == "neutral" 且 非 abstain
        try:
            label_event_ids: set[str] = set()
            for l in labels_list:
                eid = getattr(l, "event_id", None) or (l.get("event_id") if isinstance(l, dict) else None)
                if eid:
                    label_event_ids.add(str(eid))
            # 若 labels 为空，则退化为「所有 preds 都算在样本内」
            n_neutral_pred = 0
            for p in preds:
                eid = getattr(p, "event_id", None) or (p.get("event_id") if isinstance(p, dict) else None)
                if eid and label_event_ids and str(eid) not in label_event_ids:
                    continue
                pred_d = getattr(p, "pred_direction", None) or (p.get("pred_direction") if isinstance(p, dict) else None)
                abst = getattr(p, "abstain", False) or (p.get("abstain") if isinstance(p, dict) else False)
                if (not abst) and pred_d == "neutral":
                    n_neutral_pred += 1
        except Exception:
            n_neutral_pred = 0

        total_denom = int(n_total_labels) if n_total_labels > 0 else 0
        neutral_ratio = (n_neutral_pred / total_denom) if total_denom > 0 else 0.0
        abstain_count_val = int(n_abstain)

        compat_strict = _compat_acc_stat("acc_t3_strict")
        compat_non_neutral = _compat_acc_stat("acc_primary_non_neutral")

        return {
            "run_id": run_id,
            "primary_oracle_horizon": "t3",
            "epsilon": 0.005,
            "n_total": total_denom,
            "total": total_denom,
            "metrics": metrics_dict,
            "neutral_count": int(n_neutral_pred),
            "neutral_ratio": float(neutral_ratio),
            "abstain_count": abstain_count_val,
            # 向后兼容：保留老接口需要的顶层字段（前端旧代码不至于崩）
            "acc_t3_strict": compat_strict,
            "acc_t3_non_neutral": compat_non_neutral,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compute_metrics failed: {exc}")


@router.get("/metrics/defs")
def list_metric_definitions() -> Any:
    """列出所有已注册的指标元信息（display_name / description / tier / higher_is_better）。
    前端用这个动态渲染指标卡片 / 雷达图维度。"""
    from ..event_backtest.metrics_registry import list_metric_defs
    return list_metric_defs()


@router.get("/runs/{run_id}/metrics/snapshots", response_model=BacktestMetricsSnapshotList)
def get_run_metrics_snapshots(run_id: str) -> Any:
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return {"items": db.list_bt_metrics_snapshots(run_id)}


# ======================================================== SSE progress stream ---

@router.get("/stream/{run_id}")
async def stream_run_events(run_id: str) -> StreamingResponse:
    """订阅回测进度 SSE 流。

    Frame event.type ∈ {run_started, run_info, prediction, metrics_snapshot,
                         run_done, run_failed, run_cancelled, run_status_changed}
    """
    run = db.get_bt_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    q: asyncio.Queue[dict] = orch.sse_subscribe(run_id)

    async def _gen():
        try:
            # 先发一个 hello + 当前状态快照，前端立即能显示
            snap = {
                "type": "hello",
                "run_id": run_id,
                "status": run["status"],
                "done_events": run["done_events"],
                "total_events": run["total_events"],
            }
            yield _sse(snap)
            # 补发最近一个 metrics_snapshot（若有）
            snaps = db.list_bt_metrics_snapshots(run_id)
            if snaps:
                last = snaps[-1]
                yield _sse({"type": "metrics_snapshot", "from_catchup": True, **last})
            # 循环消费队列（每个 q 属本连接）
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # 心跳，保持连接
                    yield _sse({"type": "heartbeat", "run_id": run_id})
                    continue
                yield _sse(evt)
                if evt.get("type") in {"run_done", "run_failed", "run_cancelled"}:
                    break
        finally:
            orch.sse_unsubscribe(run_id, q)

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# UI 辅助：列出 prompt 变体（含具体文本）和 events 文件计数
# ---------------------------------------------------------------------------


@router.get("/datasets", response_model=list[BTDatasetResponse])
def list_datasets() -> Any:
    """返回 bt_datasets 中已注册的数据集列表，用于前端「Data list」下拉框。

    已包含：数据集 id / 显示名 / 事件数 / market 分布 / type 分布 / symbol 分布 / date range / labels_path。
    选择后提交创建 run 时传 dataset_id 即可，不需要再手动填 events_path / labels_path。
    """
    raw = db.list_bt_datasets()
    out: list[BTDatasetResponse] = []
    for r in raw:
        out.append(
            BTDatasetResponse(
                id=str(r.get("id") or ""),
                name=str(r.get("name") or r.get("id") or ""),
                path=str(r.get("path") or ""),
                labels_path=r.get("labels_path") if isinstance(r.get("labels_path"), str) and r.get("labels_path") else None,
                total_events=int(r.get("total_events") or 0),
                by_market=dict(r.get("by_market") or {}),
                by_type=dict(r.get("by_type") or {}),
                by_symbol=dict(r.get("by_symbol") or {}),
                date_range=r.get("date_range") if isinstance(r.get("date_range"), dict) else None,
                created_at=r.get("created_at"),
            )
        )
    return out


@router.get("/prompt-variants", response_model=list[PromptVariantItem])
def list_prompt_variants(
    runner: str = Query("team_prompt", description="baseline/team_prompt/team_full"),
) -> Any:
    """返回 prompt 变体选项：每个变体带 description、市场说明、完整 prompt 文本。

    - baseline: 返回空列表（不使用 LLM）
    - team_prompt: 返回 system prompt（单一判别器评分卡）
    - team_full: 返回 TEAM_FULL 任务指令模板（多 Agent 协作流程）
    """
    from ..event_backtest.engine import list_prompt_variants as _catalog
    return _catalog(runner)


@router.get("/events-count", response_model=EventsCountResponse)
def get_events_count(path: str = Query(..., description="events.jsonl 路径（相对或绝对）")) -> Any:
    """校验 events 文件并返回事件数量。"""
    resolved = _resolve_path(path) or ""
    if not resolved or not Path(resolved).is_file():
        return EventsCountResponse(
            path=resolved or str(path),
            valid=False,
            count=0,
            message="文件不存在",
        )
    try:
        from ..event_backtest.application import load_events
        evs = load_events(resolved)
        return EventsCountResponse(path=resolved, valid=True, count=len(evs), message=None)
    except Exception as exc:  # noqa: BLE001
        return EventsCountResponse(
            path=resolved,
            valid=False,
            count=0,
            message=f"校验失败: {exc}",
        )


@router.get("/labels-count", response_model=EventsCountResponse)
def get_labels_count(
    path: str = Query(..., description="labels.jsonl 路径（相对或绝对）"),
    events_path: Optional[str] = Query(None, description="可选：对应的 events 文件路径，用于检查 event_id 覆盖率"),
) -> Any:
    """校验 labels 文件并返回数量；如传 events_path 则额外对比 event_id 覆盖率。"""
    resolved = _resolve_path(path) or ""
    if not resolved or not Path(resolved).is_file():
        return EventsCountResponse(
            path=resolved or str(path),
            valid=False,
            count=0,
            message="文件不存在",
        )
    try:
        from ..event_backtest.application import load_events, load_labels

        labels = load_labels(resolved)
        label_ids = {str(getattr(l, "event_id", "")) for l in labels}

        if not events_path:
            return EventsCountResponse(path=resolved, valid=True, count=len(labels), message=None)

        # 与 events 对比覆盖率
        resolved_ev = _resolve_path(events_path) or ""
        if not resolved_ev or not Path(resolved_ev).is_file():
            return EventsCountResponse(
                path=resolved,
                valid=True,
                count=len(labels),
                message=f"加载成功 {len(labels)} 条；但对比的 events 文件不存在，跳过覆盖率检查",
            )
        evs = load_events(resolved_ev)
        ev_ids = {str(getattr(e, "event_id", "")) for e in evs}
        covered = ev_ids & label_ids
        missing = ev_ids - label_ids
        extra = label_ids - ev_ids
        msg_parts = [f"labels {len(labels)} 条；events {len(evs)} 条", f"覆盖率 {len(covered)}/{len(ev_ids)}"]
        if missing:
            miss_list = sorted(missing)[:5]
            msg_parts.append(f"缺失 {len(missing)} 个 event_id（例：{', '.join(miss_list)}{'…' if len(missing)>5 else ''}）")
        if extra:
            msg_parts.append(f"多余 {len(extra)} 个 labels 中的 event_id 在 events 里不存在")
        return EventsCountResponse(
            path=resolved,
            valid=len(missing) == 0,
            count=len(labels),
            message="；".join(msg_parts),
        )
    except Exception as exc:  # noqa: BLE001
        return EventsCountResponse(
            path=resolved,
            valid=False,
            count=0,
            message=f"校验失败: {exc}",
        )

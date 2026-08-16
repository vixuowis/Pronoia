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
        summary = compute_metrics(predictions=preds, labels=labels_list)
        return summary.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compute_metrics failed: {exc}")


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
                         run_done, run_failed, run_cancelled}
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

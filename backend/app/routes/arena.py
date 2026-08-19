"""Arena 横向比对 API。

路由前缀: /api/arena
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..config import PROJECT_ROOT
from ..event_backtest import arena as arena_engine

router = APIRouter(prefix="/api/arena", tags=["arena"])


# ============================================================== Schemas ========================

class CreateArenaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Arena 显示名")
    run_ids: list[str] = Field(..., description="参与比对的 run_id 列表，至少 2 个")
    dataset_id: Optional[str] = Field(None, description="数据集 ID（可选，便于筛选）")
    description: Optional[str] = Field(None, description="备注")
    config: Optional[dict[str, Any]] = Field(default_factory=dict, description="自定义：选定的 metric 列表等")


class ComputeArenaRequest(BaseModel):
    run_ids: list[str] = Field(..., description="参与比对的 run_id 列表（即时计算，不落库）")
    selected_metric_ids: Optional[list[str]] = Field(None, description="自定义参与排名/雷达的指标")


# ============================================================== CRUD ===========================

@router.get("")
def list_arenas(limit: int = Query(100, ge=1, le=500)) -> Any:
    items = db.list_bt_arenas(limit=limit)
    return {"total": len(items), "items": items}


@router.post("")
def create_arena(req: CreateArenaRequest) -> Any:
    if len(req.run_ids) < 2:
        raise HTTPException(status_code=400, detail="run_ids 至少需要 2 个")
    # 校验 run_id 都存在
    for rid in req.run_ids:
        r = db.get_bt_run(rid)
        if not r:
            raise HTTPException(status_code=404, detail=f"run_id={rid} 不存在")
    # 尝试取 dataset_name（方便显示）
    dataset_name = None
    if req.dataset_id:
        ds = db.get_bt_dataset(req.dataset_id)
        if ds:
            dataset_name = ds.get("name")
    return db.create_bt_arena(
        name=req.name,
        run_ids=req.run_ids,
        dataset_id=req.dataset_id,
        dataset_name=dataset_name,
        description=req.description,
        config=req.config,
    )


@router.get("/{arena_id}")
def get_arena(arena_id: str) -> Any:
    a = db.get_bt_arena(arena_id)
    if not a:
        raise HTTPException(status_code=404, detail="arena not found")
    return a


@router.delete("/{arena_id}")
def delete_arena(arena_id: str) -> Any:
    if not db.delete_bt_arena(arena_id):
        raise HTTPException(status_code=404, detail="arena not found")
    return {"ok": True, "arena_id": arena_id}


# ============================================================== 计算引擎 ======================

def _load_labels_for_runs(run_ids: list[str]):
    """尝试用第一个 run 的 labels_path 加载 labels（同数据集共享 labels）。"""
    for rid in run_ids:
        r = db.get_bt_run(rid)
        if not r:
            continue
        lp = r.get("labels_path")
        if lp and Path(lp).is_file():
            try:
                from ..event_backtest.application import load_labels
                return load_labels(lp)
            except Exception:
                return None
    return None


@router.post("/compute")
def compute_arena_inline(req: ComputeArenaRequest) -> Any:
    """即时计算：不落库，直接返回 Arena 比对结果。
    适用于前端「临时选几个 Run 对比看看」场景。"""
    if len(req.run_ids) < 2:
        raise HTTPException(status_code=400, detail="run_ids 至少需要 2 个")
    run_infos = []
    for rid in req.run_ids:
        r = db.get_bt_run(rid)
        if not r:
            raise HTTPException(status_code=404, detail=f"run_id={rid} 不存在")
        run_infos.append(r)
    ctxs = arena_engine.build_run_contexts(run_infos)
    labels_list = _load_labels_for_runs(req.run_ids)
    result = arena_engine.compute_arena_result(
        ctxs,
        selected_metric_ids=req.selected_metric_ids,
        labels_list=labels_list,
    )
    return result


@router.post("/{arena_id}/compute")
def compute_arena_and_save(
    arena_id: str,
    req: Optional[ComputeArenaRequest] = None,  # noqa: UP007 - Pydantic 兼容
) -> Any:
    """对已创建的 arena_id 计算比对结果并写回 result_json。"""
    a = db.get_bt_arena(arena_id)
    if not a:
        raise HTTPException(status_code=404, detail="arena not found")
    run_ids = req.run_ids if req and req.run_ids else (a.get("run_ids") or [])
    selected_metric_ids = (req.selected_metric_ids if req else None) or (
        (a.get("config") or {}).get("selected_metric_ids") if isinstance(a.get("config"), dict) else None
    )
    if len(run_ids) < 2:
        raise HTTPException(status_code=400, detail="run_ids 至少需要 2 个")
    # 先标记 computing
    db.update_bt_arena_status(arena_id, "computing")
    try:
        run_infos = []
        for rid in run_ids:
            r = db.get_bt_run(rid)
            if not r:
                raise HTTPException(status_code=404, detail=f"run_id={rid} 不存在")
            run_infos.append(r)
        ctxs = arena_engine.build_run_contexts(run_infos)
        labels_list = _load_labels_for_runs(run_ids)
        result = arena_engine.compute_arena_result(
            ctxs,
            selected_metric_ids=selected_metric_ids,
            labels_list=labels_list,
        )
        db.update_bt_arena_status(arena_id, "done", result=result)
    except HTTPException:
        raise
    except Exception as exc:
        db.update_bt_arena_status(arena_id, "failed", result={"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"arena compute failed: {exc}")
    return db.get_bt_arena(arena_id)

"""BacktestOrchestrator: Web 版回测调度器。

核心职责（零侵入，不修改 engine.py / application.py 任何一行）：
1. 包装 3 种 runner（baseline / team_prompt / team_full），统一 per-event callback
2. 回测生命周期管理：pending → running → done/failed，写 bt_runs 表状态
3. 每完成 N 个事件自动调用 compute_metrics → 写 bt_metrics_snapshots + 推送 SSE
4. SSE 多 client 广播：同一 run_id 所有订阅者共享进度流

V8 稳定性约束（project_memory）：
- 单进程，全局 _V8_GUARD_LOCK，同一时刻只有 1 个 active team_full run
- 每 run 内部 concurrency ≤ 2（参数强制 clamp）
"""
from __future__ import annotations

import asyncio
import json
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .. import db
from .application import load_events, validate_events, write_jsonl
from .engine import run_baseline
from .metrics import MetricsSummary, compute_metrics
from .models import Direction, EventRecord, TeamPrediction

_CLIENTS_LOCK = threading.RLock()
# run_id -> list of queues (each queue ~ 1 SSE connection)
_SSE_CLIENT_QUEUES: dict[str, list[asyncio.Queue[dict]]] = {}
# 全局 V8 互斥（team_full runner 用）：防止 py_mini_racer 在多并发/多进程下崩溃
_V8_GUARD_LOCK = threading.Lock()
# 正在 running 的 run_id -> threading.Thread（后台任务）
_RUN_TASKS: dict[str, threading.Thread] = {}
# run_id -> cancel flag (True 表示立刻在回调点抛错取消)
_RUN_CANCEL: dict[str, bool] = {}
# run_id -> threading.Event: 默认 set() 正常跑；pause() clear()；resume() 再 set()
# worker 在每条事件回调点会轮询该 event；未 set 就 sleep 等待
_RUN_RESUME: dict[str, threading.Event] = {}


def _get_resume_event(run_id: str) -> threading.Event:
    ev = _RUN_RESUME.get(run_id)
    if ev is None:
        ev = threading.Event()
        ev.set()  # 默认：允许运行
        _RUN_RESUME[run_id] = ev
    return ev


def _wait_if_paused(run_id: str, poll: float = 0.25) -> None:
    """每条事件回调点之前调用：若处于 paused 状态则阻塞等待 resume，同时检查 cancel。

    - poll: 轮询间隔秒；取消请求会在此粒度内响应
    - 若 cancel 被置 True：抛出 RuntimeError，交给上层 _do_run 捕获写 failed
    """
    ev = _get_resume_event(run_id)
    # 加一层 while，防止"伪唤醒"或竞态
    while not ev.is_set():
        if _RUN_CANCEL.get(run_id):
            raise RuntimeError("cancelled by user while paused")
        # timeout 轮询 + 顺便让出 CPU；同时 cancel 也能很快响应
        ev.wait(timeout=poll)


# --------------------------------------------------------------------- utils ----

def _dump_event_basic(ev: EventRecord) -> dict:
    return {
        "event_id": getattr(ev, "event_id", None) or (isinstance(ev, dict) and ev.get("event_id")),
        "symbol": getattr(ev, "symbol", "") or (isinstance(ev, dict) and ev.get("symbol") or ""),
        "market": getattr(ev, "market", "") or (isinstance(ev, dict) and ev.get("market") or ""),
        "event_type_l2": getattr(ev, "event_type_l2", "") or (isinstance(ev, dict) and ev.get("event_type_l2") or ""),
        "title": getattr(ev, "title", "") or (isinstance(ev, dict) and ev.get("title") or ""),
    }


def _neutral_fallback_pred(event_id: str, reason: str = "abort/fallback") -> TeamPrediction:
    return TeamPrediction(
        event_id=event_id,
        pred_direction="neutral",  # type: ignore[arg-type]
        confidence=0.50,
        rationale=f"[fallback] {reason}",
        abstain=True,
        run_id="",
    )


# ------------------------------------------------------------- SSE pub/sub ----

def sse_subscribe(run_id: str) -> asyncio.Queue[dict]:
    """新 SSE 客户端订阅：返回一个 Queue，Orchestrator 会向此 Queue put 事件。"""
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=1024)
    with _CLIENTS_LOCK:
        _SSE_CLIENT_QUEUES.setdefault(run_id, [])
        _SSE_CLIENT_QUEUES[run_id].append(q)
    return q


def sse_unsubscribe(run_id: str, q: asyncio.Queue[dict]) -> None:
    with _CLIENTS_LOCK:
        qs = _SSE_CLIENT_QUEUES.get(run_id) or []
        if q in qs:
            qs.remove(q)


def sse_broadcast(run_id: str, evt: dict) -> None:
    """把进度事件广播到所有已订阅的 SSE 队列。"""
    evt = {"run_id": run_id, **evt}
    with _CLIENTS_LOCK:
        qs = list(_SSE_CLIENT_QUEUES.get(run_id) or [])
    for q in qs:
        try:
            q.put_nowait(evt)
        except Exception:
            # 满了就丢弃最旧一条再试（兜底，不阻塞调度线程）
            try:
                q.get_nowait()
                q.put_nowait(evt)
            except Exception:
                pass


# ------------------------------------------------------------- metrics sync ----

def _sync_labels_for_predictions(
    run_id: str,
    predictions: list[TeamPrediction],
    labels_path: Optional[str | Path],
) -> None:
    """取 labels_path（若有）回填 oracle_label_t3 / oracle_car_t3 / is_correct_t3。"""
    if not labels_path:
        return
    try:
        from .application import load_labels
        labels_map = {lbl.event_id: lbl for lbl in load_labels(labels_path)}
    except Exception:
        return
    for p in predictions:
        lbl = labels_map.get(p.event_id)
        if not lbl:
            continue
        label_t3 = getattr(lbl, "label_t3", None)
        car_t3 = getattr(lbl, "car_t3", None)
        abstain = bool(getattr(p, "abstain", False))
        is_correct: Optional[bool] = None
        if label_t3 and (car_t3 is not None) and not abstain and p.pred_direction != "neutral":
            # 与 compute_metrics 同口径：pred in {up,down} 且 label not missing 才算
            is_correct = bool(p.pred_direction == label_t3)
        db.add_bt_prediction(
            run_id=run_id,
            event_id=p.event_id,
            pred_direction=p.pred_direction,
            confidence=p.confidence,
            abstain=abstain,
            rationale=p.rationale,
            oracle_label_t3=label_t3,
            oracle_car_t3=float(car_t3) if car_t3 is not None else None,
            is_correct_t3=is_correct,
        )


def _maybe_snapshot(
    run_id: str,
    predictions: list[TeamPrediction],
    labels_path: Optional[str | Path],
    *,
    done_count: int,
    force: bool = False,
) -> Optional[MetricsSummary]:
    """每完成 5 个事件（或 force=True）调用 compute_metrics 并写快照 + 推送 SSE。

    核心约束：done_events 必须更新，不能因为 labels / metrics 异常导致进度卡在 0。
    进度写 DB 与 metrics 快照解耦：metrics 失败只影响 acc 字段，done_events 照常推进。
    """
    should = force or (done_count % 5 == 0 and done_count > 0)
    # 进度写盘永远做（只要 done_count > 0 或 force），避免因 metrics 异常进度一直为 0
    if done_count > 0 or force:
        try:
            db.update_bt_run_progress(run_id, done_events=done_count)
        except Exception:
            pass
    if not should:
        return None
    labels: list = []
    if labels_path:
        try:
            from .application import load_labels
            labels = load_labels(labels_path)
        except Exception:
            labels = []
    summary: Optional[MetricsSummary] = None
    try:
        summary = compute_metrics(predictions=predictions, labels=labels)
    except Exception:
        summary = None
    if summary:
        try:
            snap_id = db.add_bt_metrics_snapshot(
                run_id=run_id,
                done_count=done_count,
                acc_t3_strict=summary.acc_t3_strict.acc,
                acc_t3_strict_lo=summary.acc_t3_strict.wilson_lo_95,
                acc_t3_non_neutral=summary.acc_t3_non_neutral.acc,
                neutral_ratio=(summary.n_abstain_pred / summary.n_total) if summary.n_total else 0.0,
            )
            sse_broadcast(run_id, {
                "type": "metrics_snapshot",
                "snapshot_id": snap_id,
                "done_count": done_count,
                "acc_t3_strict": summary.acc_t3_strict.acc,
                "acc_t3_strict_lo": summary.acc_t3_strict.wilson_lo_95,
                "acc_t3_non_neutral": summary.acc_t3_non_neutral.acc,
                "neutral_ratio": (summary.n_abstain_pred / summary.n_total) if summary.n_total else 0.0,
            })
            db.update_bt_run_progress(
                run_id,
                done_events=done_count,
                acc_t3_strict=summary.acc_t3_strict.acc,
                acc_t3_strict_lo=summary.acc_t3_strict.wilson_lo_95,
                acc_t3_non_neutral=summary.acc_t3_non_neutral.acc,
            )
        except Exception:
            pass
    return summary


# -------------------------------------------------------- per-runner wrappers ----

def _run_baseline_with_cb(
    events: list[EventRecord],
    *,
    run_id: str,
    model_version: str,
    on_pred: Callable[[TeamPrediction, EventRecord], None],
) -> list[TeamPrediction]:
    """baseline runner 本身是批量的，拆成逐事件调用保证进度可见。

    调试/验证 pause/resume：设置环境变量 FEVER_BT_SLEEP_PER_EVENT=1.2 可让每条事件后 sleep N 秒，
    模拟真实慢回测。
    """
    # baseline 内部其实没有 per-event LLM；但我们对每个事件独立调 run_baseline([ev])
    # 仍然是 O(N) 且不破坏现有返回结构
    import os as _os
    _sleep_s = 0.0
    try:
        _sleep_s = float(_os.environ.get("FEVER_BT_SLEEP_PER_EVENT") or "0")
    except Exception:
        _sleep_s = 0.0
    from .engine import run_baseline
    outs: list[TeamPrediction] = []
    for ev in events:
        ps = run_baseline([ev], run_id=run_id, model_version=model_version or "event-baseline-v0")
        for p in ps:
            outs.append(p)
            on_pred(p, ev)
        if _sleep_s > 0:
            import time as _time
            _time.sleep(_sleep_s)
    return outs


def _run_team_prompt_with_cb(
    events: list[EventRecord],
    *,
    run_id: str,
    model_version: str,
    concurrency: int,
    skip_event_ids: set[str],
    system_prompt_variant: str,
    on_pred: Callable[[TeamPrediction, EventRecord], None],
) -> list[TeamPrediction]:
    """直接复用 engine.run_team_prompt 的 on_pred_callback，再查回 event record。"""
    from .engine import run_team_prompt
    ev_map = {getattr(e, "event_id", ""): e for e in events}

    def _cb(p: TeamPrediction) -> None:
        ev = ev_map.get(p.event_id)
        if ev is None:
            ev = EventRecord(event_id=p.event_id, symbol="", market="", event_time="",
                             event_type_l2="", title="", event_text="", source_url="")
        on_pred(p, ev)

    preds = asyncio.run(
        run_team_prompt(
            events,
            run_id=run_id,
            model_version=model_version,
            concurrency=concurrency,
            skip_event_ids=skip_event_ids,
            system_prompt_variant=system_prompt_variant,
            on_pred_callback=_cb,
        )
    )
    return list(preds)


def _run_team_full_with_cb(
    events: list[EventRecord],
    *,
    run_id: str,
    model_version: str,
    concurrency: int,
    skip_event_ids: set[str],
    system_prompt_variant: str,
    trajectory_ckpt_dir: Path,
    on_pred: Callable[[TeamPrediction, EventRecord], None],
    cancel_flag_ref: list[bool],
) -> list[TeamPrediction]:
    """调用 engine.run_team_full_trajectory；通过原生 on_pred_callback 做到每条 case 完成即实时推进度
    （LLM 调用完成 → engine 立即 callback → _on_pred 写 DB / 写盘 / SSE / done_events++，
    而不是等全部跑完再批量 push，解决「一直 0/N → 突然 N/N 跳变」观感问题）。

    pause/cancel 阻塞在 orchestrator 的 _on_pred 内部统一处理（每条 pred 完成后 _wait_if_paused + cancel_flag 检查），
    不会把 pause 逻辑穿进 engine 内部，保持 engine 独立可测。
    """
    from .engine import run_team_full_trajectory

    ev_map = {getattr(e, "event_id", ""): e for e in events}
    ev_map[""] = EventRecord(
        event_id="", symbol="", market="", event_time="",
        event_type_l2="", title="", event_text="", source_url="",
    )

    seen_eids: set[str] = set()
    ordered: list[TeamPrediction] = []

    def _cb(p: TeamPrediction) -> None:
        ev = ev_map.get(p.event_id, ev_map[""])
        seen_eids.add(p.event_id)
        ordered.append(p)  # 按 callback 到达顺序（真实完成顺序，后续 main 返回用 events 原始 order 兜底）
        on_pred(p, ev)

    preds = asyncio.run(
        run_team_full_trajectory(
            events,
            run_id=run_id,
            model_version=model_version,
            concurrency=concurrency,
            skip_event_ids=skip_event_ids,
            system_prompt_variant=system_prompt_variant,
            trajectory_ckpt_dir=trajectory_ckpt_dir,
            on_pred_callback=_cb,
        )
    )
    # 兜底：skip_event_ids 里的事件没有走 callback（engine 直接跳过），但需要返回给上层让 out_path 完整。
    # 另外，preds 按 remaining 原始 idx 顺序，我们用 preds 做最终返回保证顺序稳定；
    # 对 engine 产出但 callback 没触达（异常边界保护）的那些，再补一次 on_pred 以防漏写 DB。
    remaining = [e for e in events if getattr(e, "event_id", None) not in skip_event_ids]
    pred_map = {p.event_id: p for p in preds}
    final_ordered: list[TeamPrediction] = []
    for ev in remaining:
        eid = getattr(ev, "event_id", None) or ""
        p = pred_map.get(eid)
        if not p:
            p = _neutral_fallback_pred(eid, reason="team_full missing prediction (abstain)")
        final_ordered.append(p)
        if p.event_id and p.event_id not in seen_eids:
            on_pred(p, ev)
    return final_ordered


# --------------------------------------------------------- main entry point ----

@dataclass
class BacktestStartResult:
    ok: bool
    run_id: str
    error: Optional[str] = None


def start_bt_run(run_id: str) -> BacktestStartResult:
    """启动/恢复一个回测 run：pending / paused / 没有活跃线程的 stuck run 都会起新线程。

    设计目标：
    - 刷新页面后（后台线程仍在跑）：不会重复起线程
    - server 重启后 running/paused stuck run：用户点 Continue → 重新启线程，
      _do_run 会从 out_path + ckpt_dir 扫已完成事件（skip_event_ids），不会从头重算
    """
    run = db.get_bt_run(run_id)
    if not run:
        return BacktestStartResult(ok=False, run_id=run_id, error=f"run_id={run_id} not found")

    current = str(run.get("status") or "")
    active_thread = _RUN_TASKS.get(run_id)
    if active_thread is not None and active_thread.is_alive():
        return BacktestStartResult(ok=True, run_id=run_id, error=f"already active, status={current}")

    # 允许从 pending / paused / running(stuck) / failed / cancelled 启动；
    # done 是终态，不允许再启动。failed/cancelled 启动会走 resume 续算（跳过已完成事件）。
    if current not in {"pending", "paused", "running", "failed", "cancelled"}:
        return BacktestStartResult(ok=False, run_id=run_id, error=f"cannot start from status={current}")

    # 参数 clamp：V8 稳定性硬约束（project_memory）
    effective_concurrency = min(2, max(1, int(run.get("concurrency") or 1)))

    # 初始化 resume 事件：默认 set(允许运行)
    _get_resume_event(run_id).set()
    db.update_bt_run_status(run_id, "running")
    sse_broadcast(run_id, {"type": "run_started", "concurrency": effective_concurrency})
    _RUN_CANCEL[run_id] = False

    def _thread_main() -> None:
        try:
            with _V8_GUARD_LOCK:
                _do_run(run_id, effective_concurrency)
        except Exception as exc:
            tb = traceback.format_exc()
            db.update_bt_run_status(run_id, "failed", error_msg=f"{type(exc).__name__}: {exc}")
            sse_broadcast(run_id, {"type": "run_failed", "error": f"{type(exc).__name__}: {exc}", "traceback": tb})
        finally:
            _RUN_TASKS.pop(run_id, None)
            _RUN_CANCEL.pop(run_id, None)
            _RUN_RESUME.pop(run_id, None)

    t = threading.Thread(target=_thread_main, name=f"bt-run-{run_id}", daemon=True)
    _RUN_TASKS[run_id] = t
    t.start()
    return BacktestStartResult(ok=True, run_id=run_id)


def cancel_bt_run(run_id: str) -> bool:
    """取消回测：running / paused 状态都允许取消。"""
    run = db.get_bt_run(run_id)
    if not run:
        return False
    status = str(run.get("status") or "")
    if status not in {"running", "paused"}:
        return False
    _RUN_CANCEL[run_id] = True
    # 若当前 paused，先把 resume event set 一下 → wait_if_paused 会立刻抛 cancel，不永久阻塞
    _get_resume_event(run_id).set()
    db.update_bt_run_status(run_id, "cancelled")
    sse_broadcast(run_id, {"type": "run_cancelled"})
    return True


def pause_bt_run(run_id: str) -> tuple[bool, str]:
    """暂停：要求 status=running 且线程仍 alive；否则报 409 友好消息。返回 (ok, message)。"""
    run = db.get_bt_run(run_id)
    if not run:
        return False, "run not found"
    status = str(run.get("status") or "")
    if status == "paused":
        return True, "already paused"
    if status != "running":
        return False, f"cannot pause from status={status}"
    t = _RUN_TASKS.get(run_id)
    if t is None or not t.is_alive():
        # 线程已经退出，但 DB 还是 running（stuck）— 直接置为 paused 以便用户后续 Resume
        db.update_bt_run_status(run_id, "paused")
        sse_broadcast(run_id, {"type": "run_status_changed", "from": status, "to": "paused", "reason": "worker_thread_gone"})
        return True, "worker gone, marked paused"
    _get_resume_event(run_id).clear()
    db.update_bt_run_status(run_id, "paused")
    sse_broadcast(run_id, {"type": "run_status_changed", "from": "running", "to": "paused"})
    return True, "paused"


def resume_bt_run(run_id: str) -> tuple[bool, str]:
    """继续：
    - status=paused 且线程 alive → 置位 resume_event
    - status=paused 线程死了 / status=running 线程死了 → 调 start_bt_run 重起线程 + 从 out_path 恢复
    - status=pending → 直接 start_bt_run
    """
    run = db.get_bt_run(run_id)
    if not run:
        return False, "run not found"
    status = str(run.get("status") or "")
    if status == "running":
        t = _RUN_TASKS.get(run_id)
        if t and t.is_alive():
            return True, "already running"
        r = start_bt_run(run_id)
        return r.ok, (r.error or "resumed (restart worker, skip done via out_path)")
    if status == "paused":
        t = _RUN_TASKS.get(run_id)
        if t and t.is_alive():
            _get_resume_event(run_id).set()
            db.update_bt_run_status(run_id, "running")
            sse_broadcast(run_id, {"type": "run_status_changed", "from": "paused", "to": "running"})
            return True, "resumed"
        r = start_bt_run(run_id)
        return r.ok, (r.error or "resumed (restart worker, skip done via out_path)")
    if status == "pending":
        r = start_bt_run(run_id)
        return r.ok, (r.error or "started")
    return False, f"cannot resume from status={status}"


def _do_run(run_id: str, effective_concurrency: int) -> None:
    run = db.get_bt_run(run_id)
    if not run:
        raise RuntimeError(f"run_id={run_id} missing in thread")

    events_path = Path(run["events_path"])
    out_path = Path(run["out_path"])
    labels_path = Path(run["labels_path"]) if run.get("labels_path") else None
    ckpt_dir = Path(run["ckpt_dir"]) if run.get("ckpt_dir") else None

    # --- 1. 加载 & 校验 events ---
    events = load_events(events_path)
    issues = validate_events(events)
    if issues:
        raise ValueError("事件文件校验失败:\n" + "\n".join(issues[:20]))

    db.update_bt_run_progress(run_id, done_events=0)
    sse_broadcast(run_id, {"type": "run_info", "total_events": len(events)})

    # --- 2. resume 逻辑（从 out_path + ckpt_dir 扫描已完成） ---
    from .application import load_predictions
    existing: list[TeamPrediction] = []
    skip_event_ids: set[str] = set()
    if out_path.exists():
        try:
            existing = load_predictions(out_path)
            skip_event_ids = {p.event_id for p in existing if p.event_id}
        except Exception:
            existing, skip_event_ids = [], set()
    if run["runner"] == "team_full" and ckpt_dir and ckpt_dir.exists() and ckpt_dir.is_dir():
        for fn in ckpt_dir.iterdir():
            if fn.is_file() and fn.suffix == ".json" and not fn.name.startswith("."):
                ev_id = fn.stem.split("__")[0]
                if ev_id:
                    skip_event_ids.add(ev_id)

    predictions_buffer: list[TeamPrediction] = list(existing)
    done_count_holder = {"n": len(existing)}

    # --- 3. per-pred callback (统一写盘 + 写 DB + SSE + 定时 metrics) ---
    def _flush_all() -> None:
        # 写预测 JSONL
        try:
            write_jsonl(out_path, [p.to_dict() for p in predictions_buffer])
        except Exception:
            pass

    def _on_pred(p: TeamPrediction, ev: EventRecord) -> None:
        # 每条事件回调点先统一处理：pause 阻塞 / cancel 抛错
        _wait_if_paused(run_id)
        if _RUN_CANCEL.get(run_id):
            raise RuntimeError("cancelled by user")
        predictions_buffer.append(p)
        done_count_holder["n"] += 1
        n = done_count_holder["n"]
        # 每个 pred 落盘
        _flush_all()
        # 写 bt_predictions 表（labels 若在则同步回填 oracle）
        labels_map: dict[str, Any] = {}
        if labels_path:
            try:
                from .application import load_labels
                labels_map = {lbl.event_id: lbl for lbl in load_labels(labels_path)}
            except Exception:
                labels_map = {}
        lbl = labels_map.get(p.event_id)
        label_t3 = getattr(lbl, "label_t3", None) if lbl else None
        car_t3 = getattr(lbl, "car_t3", None) if lbl else None
        abstain = bool(getattr(p, "abstain", False))
        is_correct: Optional[bool] = None
        if label_t3 and car_t3 is not None and not abstain and p.pred_direction in {"up", "down"}:
            is_correct = bool(p.pred_direction == label_t3)
        db.add_bt_prediction(
            run_id=run_id,
            event_id=p.event_id,
            pred_direction=p.pred_direction,
            symbol=getattr(ev, "symbol", None),
            market=getattr(ev, "market", None),
            event_type_l2=getattr(ev, "event_type_l2", None),
            confidence=p.confidence,
            abstain=abstain,
            rationale=p.rationale,
            oracle_label_t3=label_t3,
            oracle_car_t3=float(car_t3) if car_t3 is not None else None,
            is_correct_t3=is_correct,
            trajectory_ckpt=str(ckpt_dir / f"{p.event_id}.json") if ckpt_dir else None,
        )
        # 推送单事件 SSE
        sse_broadcast(run_id, {
            "type": "prediction",
            "done_count": n,
            "prediction": {
                "event_id": p.event_id,
                "pred_direction": p.pred_direction,
                "confidence": p.confidence,
                "abstain": abstain,
            },
            "event_basic": _dump_event_basic(ev),
        })
        # 每 5 个事件一次 metrics 快照
        _maybe_snapshot(run_id, predictions_buffer, labels_path, done_count=n)

    # --- 4. 根据 runner 分派 ---
    variant = run.get("prompt_variant") or "v0"
    model_version = run.get("model_version") or ""
    cancel_ref = [_RUN_CANCEL.get(run_id, False)]

    if run["runner"] == "baseline":
        evs_run = [e for e in events if getattr(e, "event_id", None) not in skip_event_ids]
        preds = _run_baseline_with_cb(
            evs_run,
            run_id=run_id,
            model_version=model_version or "event-baseline-v0",
            on_pred=_on_pred,
        )
    elif run["runner"] == "team_prompt":
        evs_run = events  # skip 在内部用
        preds = _run_team_prompt_with_cb(
            evs_run,
            run_id=run_id,
            model_version=model_version or "team-prompt-v0",
            concurrency=effective_concurrency,
            skip_event_ids=skip_event_ids,
            system_prompt_variant=variant,
            on_pred=_on_pred,
        )
    elif run["runner"] == "team_full":
        if ckpt_dir is None:
            ckpt_dir = Path("data/_trajectory_ckpt_web")
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        preds = _run_team_full_with_cb(
            events,
            run_id=run_id,
            model_version=model_version or "team-full-trajectory-v1",
            concurrency=effective_concurrency,
            skip_event_ids=skip_event_ids,
            system_prompt_variant=variant,
            trajectory_ckpt_dir=ckpt_dir,
            on_pred=_on_pred,
            cancel_flag_ref=cancel_ref,
        )
    else:
        raise ValueError(f"未知 runner={run['runner']}")

    # --- 5. 收尾：强制 metrics 终态 + JSONL 终态写盘 ---
    final_n = done_count_holder["n"]
    _flush_all()
    summary = _maybe_snapshot(run_id, predictions_buffer, labels_path, done_count=final_n, force=True)
    # labels 全量回填（防止中途 labels_path 变化）
    _sync_labels_for_predictions(run_id, predictions_buffer, labels_path)
    db.update_bt_run_status(run_id, "done")
    sse_broadcast(run_id, {
        "type": "run_done",
        "done_count": final_n,
        "metrics": summary.to_dict() if summary else None,
    })

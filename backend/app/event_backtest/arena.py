"""Arena：同一数据集 × 多 Run（不同 Agent/LLM/配置）的横向比对引擎。

输入：一组 run_id（对应 bt_runs，必须共享同一 events/labels 数据集才比得有意义）
输出：
  - per_run_metrics  ：每个 run 的完整指标集（metrics_registry 结果）
  - ranking           ：每个指标的升/降排名 {metric_id: [{run_id, value, rank}]}
  - radar_chart       ：归一化的雷达图数据（每条 run 对应一个多边形）
  - pairwise_tests    ：两两 run 的显著性检验（对每个核心准确率做两比例 z 检验 / McNemar）
  - win_loss_table    ：两两 run 的胜负统计表
  - shared_events     ：参与 run 之间共有的事件集合（便于统计"同事件上的直接对决"）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ============================================================== 统计工具 ========================

def two_prop_z_test(n1: int, k1: int, n2: int, k2: int) -> dict:
    """两比例 z 检验（大样本近似），比较 run1 (k1/n1) vs run2 (k2/n2) 的准确率差异。

    返回 {p_value, z_score, diff, ci95_lo, ci95_hi}；
    小样本 / 0 比例时返回空结果。
    """
    if n1 <= 0 or n2 <= 0:
        return {"ok": False, "reason": "n<=0"}
    p1 = k1 / n1
    p2 = k2 / n2
    diff = p1 - p2
    k = k1 + k2
    n = n1 + n2
    p_pool = k / n if n > 0 else 0
    if p_pool in (0.0, 1.0):
        # 极端情况（全对/全错）：无方差，跳过检验
        return {"ok": False, "reason": "pooled proportion extreme (0/1)"}
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se <= 1e-12:
        return {"ok": False, "reason": "se too small"}
    z = diff / se
    # 双侧 p 值
    p_value = 2 * (1 - _norm_cdf(abs(z)))
    # diff 的 95% CI（不用 pooled se，用各自的）
    se_unpooled = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    ci_lo = diff - 1.95996 * se_unpooled
    ci_hi = diff + 1.95996 * se_unpooled
    return {
        "ok": True,
        "p_value": float(f"{p_value:.6f}"),
        "z_score": float(f"{z:.4f}"),
        "diff": float(f"{diff:.6f}"),
        "ci95_lo": float(f"{ci_lo:.6f}"),
        "ci95_hi": float(f"{ci_hi:.6f}"),
        "n1": n1, "k1": k1, "n2": n2, "k2": k2,
    }


def _norm_cdf(x: float) -> float:
    """标准正态分布 CDF（Abramowitz & Stegun 近似，误差<7.5e-8）。"""
    # constants
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)


# ============================================================== 核心 Arena =====================

@dataclass
class ArenaRunContext:
    """每个被比 run 的上下文数据。"""
    run_id: str
    run_info: dict[str, Any]                       # bt_runs 行
    # 关键属性，便于前端直接展示：
    runner: str = ""
    prompt_variant: str = ""
    model_version: str = ""
    status: str = ""
    done_events: int = 0
    total_events: int = 0
    # 成本 / 耗时（从 bt_predictions 聚合）
    tokens_in: int = 0
    tokens_out: int = 0
    step_ms_total: int = 0
    # 指标：从 metrics_registry 结果读取
    metrics: dict[str, dict] = field(default_factory=dict)
    # prediction 明细（按需加载，用于 pairwise 同事件直接对决）
    predictions_by_eid: dict[str, dict] = field(default_factory=dict)


def _load_run_predictions(run_info: dict) -> dict[str, dict]:
    """从 run 的 out_path 读取 predictions JSONL，返回 {event_id: pred_dict}。"""
    out_path = run_info.get("out_path") or ""
    if not out_path or not Path(out_path).is_file():
        return {}
    preds: dict[str, dict] = {}
    try:
        from .application import load_predictions
        for p in load_predictions(out_path):
            eid = getattr(p, "event_id", None)
            if not eid:
                continue
            preds[eid] = {
                "pred_direction": getattr(p, "pred_direction", None),
                "confidence": getattr(p, "confidence", None),
                "abstain": bool(getattr(p, "abstain", False)),
                "rationale": getattr(p, "rationale", None),
            }
    except Exception:
        pass
    return preds


def _compute_run_metrics(run_info: dict) -> dict[str, dict]:
    """计算或从 DB 读取一个 run 的完整 metrics_registry 结果。
    优先走 DB.metrics_json；没有则现场计算并回写。"""
    # 1) DB 缓存优先
    cached = run_info.get("metrics") or None
    if isinstance(cached, dict) and cached:
        return cached
    # 2) 现场计算：load preds + labels
    from pathlib import Path
    out_path = run_info.get("out_path") or ""
    labels_path = run_info.get("labels_path") or None
    preds_list = []
    labels_list = []
    try:
        from .application import load_predictions, load_labels
        if out_path and Path(out_path).is_file():
            preds_list = load_predictions(out_path)
        if labels_path and Path(labels_path).is_file():
            labels_list = load_labels(labels_path)
    except Exception:
        preds_list, labels_list = [], []
    if not preds_list:
        return {}
    from .metrics_registry import compute_all_metrics
    results = compute_all_metrics(predictions=preds_list, labels=labels_list)
    return {mid: mr.to_dict() for mid, mr in results.items()}


def _aggregate_run_cost(run_id: str) -> dict:
    """从 bt_predictions 聚合 tokens_in / tokens_out / step_ms 总和。"""
    try:
        from .. import db as _db
        row = _db._get_conn().execute(
            """
            SELECT
              COALESCE(SUM(tokens_in), 0),
              COALESCE(SUM(tokens_out), 0),
              COALESCE(SUM(step_ms), 0)
            FROM bt_predictions WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        if not row:
            return {"tokens_in": 0, "tokens_out": 0, "step_ms_total": 0}
        return {
            "tokens_in": int(row[0] or 0),
            "tokens_out": int(row[1] or 0),
            "step_ms_total": int(row[2] or 0),
        }
    except Exception:
        return {"tokens_in": 0, "tokens_out": 0, "step_ms_total": 0}


def build_run_contexts(run_infos: list[dict]) -> list[ArenaRunContext]:
    """把一组 bt_runs 行转成 ArenaRunContext（带指标、predictions、tokens/step_ms）。"""
    ctxs: list[ArenaRunContext] = []
    for r in run_infos:
        rid = str(r.get("id") or "")
        metrics = _compute_run_metrics(r)
        preds = _load_run_predictions(r)
        cost = _aggregate_run_cost(rid)
        ctxs.append(ArenaRunContext(
            run_id=rid,
            run_info=r,
            runner=str(r.get("runner") or ""),
            prompt_variant=str(r.get("prompt_variant") or ""),
            model_version=str(r.get("model_version") or ""),
            status=str(r.get("status") or ""),
            done_events=int(r.get("done_events") or 0),
            total_events=int(r.get("total_events") or 0),
            tokens_in=cost["tokens_in"],
            tokens_out=cost["tokens_out"],
            step_ms_total=cost["step_ms_total"],
            metrics=metrics,
            predictions_by_eid=preds,
        ))
    return ctxs


# ============================================================== 聚合：排名 / 雷达 / 配对 ======

def _rank_metric(ctxs: list[ArenaRunContext], metric_id: str,
                 metric_def: Optional[dict] = None) -> list[dict]:
    """对单个指标的所有 run 排序并打 rank。返回 [{run_id, value, rank, display_name}]。"""
    higher = True
    display = metric_id
    if metric_def:
        higher = bool(metric_def.get("higher_is_better", True))
        display = metric_def.get("display_name") or metric_id
    rows = []
    for c in ctxs:
        mr = c.metrics.get(metric_id) or {}
        val = mr.get("value")
        rows.append({"run_id": c.run_id, "value": val, "display_name": display})
    # 排序：None 放最后
    def _sort_key(r):
        v = r["value"]
        if v is None:
            return (1, 0.0)
        return (0, float(v) if higher else -float(v))
    rows.sort(key=_sort_key)
    # 排名（同分同 rank：dense）
    last_v = None
    last_rank = 0
    for i, r in enumerate(rows):
        v = r["value"]
        if v is None:
            r["rank"] = None
            continue
        if last_v is None or v != last_v:
            last_rank = i + 1
            last_v = v
        r["rank"] = last_rank
    return rows


def _normalize_for_radar(
    ctxs: list[ArenaRunContext],
    metric_ids: list[str],
    metric_defs: dict[str, dict],
) -> dict[str, Any]:
    """为雷达图归一化指标到 [0, 1]：
      - higher_is_better=True : (v - min) / (max - min)
      - higher_is_better=False: 1 - (v - min)/(max - min)
      - 若 max==min：都给 0.5
    返回 {
      axes: [{metric_id, display_name}],
      series: [{run_id, label, values: [0..1 对应 axes 顺序]}]
    }
    """
    axes = []
    for mid in metric_ids:
        md = metric_defs.get(mid, {})
        axes.append({"metric_id": mid, "display_name": md.get("display_name") or mid})

    # 收集每个指标的 [value, None 跳过]
    per_metric_vals: dict[str, list[float]] = {mid: [] for mid in metric_ids}
    per_run_vals: dict[str, list[Optional[float]]] = {c.run_id: [] for c in ctxs}
    for mid in metric_ids:
        for c in ctxs:
            v = (c.metrics.get(mid) or {}).get("value")
            per_run_vals[c.run_id].append(v)
            if v is not None:
                per_metric_vals[mid].append(float(v))

    # 求 min/max
    bounds: dict[str, tuple[float, float]] = {}
    for mid in metric_ids:
        vals = per_metric_vals[mid]
        if not vals:
            bounds[mid] = (0.0, 1.0)
        else:
            lo, hi = min(vals), max(vals)
            if abs(hi - lo) < 1e-9:
                # 单值：取 [lo - 10%, lo + 10%]（至少非零区间）以便非 0.5
                if abs(lo) < 1e-9:
                    lo, hi = 0.0, 1.0
                else:
                    eps = abs(lo) * 0.1
                    lo -= eps
                    hi += eps
            bounds[mid] = (lo, hi)

    series = []
    for c in ctxs:
        label = (
            (c.model_version or f"{c.runner}/{c.prompt_variant}" or c.runner)
            + f" · {c.run_id[:6]}"
        )
        norm = []
        for i, mid in enumerate(metric_ids):
            v = per_run_vals[c.run_id][i]
            if v is None:
                norm.append(None)
                continue
            lo, hi = bounds[mid]
            frac = (float(v) - lo) / (hi - lo)
            frac = max(0.0, min(1.0, frac))
            md = metric_defs.get(mid, {})
            if not md.get("higher_is_better", True):
                frac = 1.0 - frac
            norm.append(float(f"{frac:.4f}"))
        series.append({"run_id": c.run_id, "label": label, "values": norm})
    return {"axes": axes, "series": series}


def _pairwise_compare(
    ctxs: list[ArenaRunContext],
    metric_ids_for_test: list[str],
    metric_defs: dict[str, dict],
) -> list[dict]:
    """对每个核心"准确率类"指标（带 n/k）做两两 z 检验。"""
    out = []
    for i in range(len(ctxs)):
        for j in range(i + 1, len(ctxs)):
            ci, cj = ctxs[i], ctxs[j]
            per_metric = {}
            for mid in metric_ids_for_test:
                # 从 breakdown.wilson 读 n/k（acc_*_strict / non_neutral / significant_only 都有）
                mi = ci.metrics.get(mid) or {}
                mj = cj.metrics.get(mid) or {}
                wi = (mi.get("breakdown") or {}).get("wilson") or {}
                wj = (mj.get("breakdown") or {}).get("wilson") or {}
                n1, k1 = int(wi.get("n") or 0), int(wi.get("k") or 0)
                n2, k2 = int(wj.get("n") or 0), int(wj.get("k") or 0)
                test_res = two_prop_z_test(n1, k1, n2, k2)
                md = metric_defs.get(mid, {})
                per_metric[mid] = {
                    "display_name": md.get("display_name") or mid,
                    "v_i": mi.get("value"),
                    "v_j": mj.get("value"),
                    "test": test_res,
                }
            out.append({
                "i_run_id": ci.run_id,
                "j_run_id": cj.run_id,
                "i_label": f"{ci.runner}/{ci.prompt_variant or ''}/{ci.model_version or ''}".strip("/"),
                "j_label": f"{cj.runner}/{cj.prompt_variant or ''}/{cj.model_version or ''}".strip("/"),
                "metrics": per_metric,
            })
    return out


def _shared_event_head_to_head(
    ctxs: list[ArenaRunContext],
    labels_list: Optional[list] = None,
) -> dict[str, Any]:
    """同事件直接对决：在参与 run 共同覆盖的事件子集上，两两 run 统计谁更准。

    labels_list 可选：如果提供，还能计算"谁与 oracle 更一致"的胜场。
    返回 {
      shared_event_count: N,
      win_loss: [{i_run_id, j_run_id, i_wins, j_wins, ties}],
      per_event_matrix: {event_id: {run_id: pred_direction}}  # 抽样前 100 条
    }
    """
    # 1) 所有 run 都预测了的 eid 交集
    eid_sets = [set(c.predictions_by_eid.keys()) for c in ctxs if c.predictions_by_eid]
    if not eid_sets:
        return {"shared_event_count": 0, "win_loss": [], "per_event_matrix": {}}
    shared: set[str] = set.intersection(*eid_sets) if len(eid_sets) > 1 else eid_sets[0]
    shared_count = len(shared)

    # 2) 两两 win/loss/tie（按 primary oracle，若 labels_list 提供）
    label_by_eid = {}
    if labels_list:
        from .models import EventLabel
        for l in labels_list:
            if isinstance(l, EventLabel):
                label_by_eid[l.event_id] = l.label_t3  # primary=t3

    win_loss = []
    for i in range(len(ctxs)):
        for j in range(i + 1, len(ctxs)):
            ci, cj = ctxs[i], ctxs[j]
            iw = jw = ties = 0
            for eid in shared:
                pi = ci.predictions_by_eid.get(eid) or {}
                pj = cj.predictions_by_eid.get(eid) or {}
                di, dj = pi.get("pred_direction"), pj.get("pred_direction")
                oracle = label_by_eid.get(eid)
                if not oracle or oracle == "neutral":
                    # 无标签/中性：比较预测本身（不区分胜负，除非我们想比较一致性）
                    if di == dj:
                        ties += 1
                    # 否则：没法判定
                    continue
                ci_correct = (di == oracle)
                cj_correct = (dj == oracle)
                if ci_correct and not cj_correct:
                    iw += 1
                elif cj_correct and not ci_correct:
                    jw += 1
                else:
                    ties += 1
            win_loss.append({
                "i_run_id": ci.run_id, "j_run_id": cj.run_id,
                "i_label": f"{ci.runner}/{ci.prompt_variant or ''}/{ci.model_version or ''}".strip("/"),
                "j_label": f"{cj.runner}/{cj.prompt_variant or ''}/{cj.model_version or ''}".strip("/"),
                "i_wins": iw, "j_wins": jw, "ties": ties,
            })

    # 3) 抽样 per_event_matrix（最多前 100 个 shared 事件）
    sample = sorted(shared)[:100]
    matrix = {}
    for eid in sample:
        row = {}
        for c in ctxs:
            p = c.predictions_by_eid.get(eid) or {}
            row[c.run_id] = {
                "pred": p.get("pred_direction"),
                "confidence": p.get("confidence"),
                "abstain": bool(p.get("abstain")),
                "oracle_t3": label_by_eid.get(eid),
            }
        matrix[eid] = row
    return {"shared_event_count": shared_count, "win_loss": win_loss, "per_event_matrix": matrix}


def compute_arena_result(
    ctxs: list[ArenaRunContext],
    *,
    selected_metric_ids: Optional[list[str]] = None,
    labels_list: Optional[list] = None,
) -> dict:
    """主入口：计算 Arena 的完整比对结果。"""
    from .metrics_registry import list_metric_defs
    all_defs = list_metric_defs()

    # 决定要展示的指标
    if not selected_metric_ids:
        # 默认：所有 core + extended（剔除 value=None 的）
        selected = []
        for mid, md in all_defs.items():
            if md["tier"] in ("core", "extended"):
                selected.append(mid)
        # 过滤掉"所有 run 都没值"的指标
        has_any = {mid: False for mid in selected}
        for c in ctxs:
            for mid in selected:
                v = (c.metrics.get(mid) or {}).get("value")
                if v is not None:
                    has_any[mid] = True
        selected = [mid for mid in selected if has_any[mid]]
        selected_metric_ids = selected

    # 1) per-run-metrics（按 selected_metric_ids 过滤）
    per_run = {}
    for c in ctxs:
        display_name = (
            (c.model_version or c.runner)
            + (f" · {c.prompt_variant}" if c.prompt_variant else "")
        )
        per_run[c.run_id] = {
            "run_id": c.run_id,
            "display_name": display_name,
            "runner": c.runner,
            "prompt_variant": c.prompt_variant,
            "model_version": c.model_version,
            "status": c.status,
            "done_events": c.done_events,
            "total_events": c.total_events,
            "metrics": {mid: c.metrics.get(mid) for mid in selected_metric_ids if c.metrics.get(mid)},
        }

    # 2) ranking（每个指标）
    ranking = {}
    for mid in selected_metric_ids:
        ranking[mid] = _rank_metric(ctxs, mid, all_defs.get(mid))

    # 3) 雷达图（只取有 value 的"核心几个" + 手动挑的扩展指标）
    radar_metrics = []
    preferred = [
        "acc_avg_all_strict", "acc_t3_strict", "acc_primary_non_neutral",
        "acc_primary_significant_only", "coverage_rate", "abstain_rate",
        "calibration_mse", "direction_bias", "acc_high_confidence",
    ]
    for mid in preferred:
        if mid in selected_metric_ids:
            radar_metrics.append(mid)
    # 不够 5 个时用 selected 的前几个补齐
    if len(radar_metrics) < 5:
        for mid in selected_metric_ids:
            if mid not in radar_metrics:
                radar_metrics.append(mid)
                if len(radar_metrics) >= 7:
                    break
    radar = _normalize_for_radar(ctxs, radar_metrics, all_defs)

    # 4) pairwise 检验（对 3 个核心准确率类指标）
    pairwise_targets = [
        mid for mid in ["acc_avg_all_strict", "acc_t3_strict", "acc_primary_non_neutral"]
        if mid in selected_metric_ids
    ]
    pairwise = _pairwise_compare(ctxs, pairwise_targets, all_defs)

    # 把成本信息合并进 per_run（便于前端任意 Tab 中复用）
    # 成本估算：按商用 LLM 通用中位数 $0.50 / 1M in, $1.50 / 1M out 计算
    PRICE_IN_PER_M = 0.50
    PRICE_OUT_PER_M = 1.50
    for c in ctxs:
        rid = c.run_id
        if rid in per_run:
            tokens_in = int(c.tokens_in or 0)
            tokens_out = int(c.tokens_out or 0)
            step_ms = int(c.step_ms_total or 0)
            cost_usd = (tokens_in / 1_000_000) * PRICE_IN_PER_M + (tokens_out / 1_000_000) * PRICE_OUT_PER_M
            per_run[rid]["tokens_in"] = tokens_in
            per_run[rid]["tokens_out"] = tokens_out
            per_run[rid]["tokens_total"] = tokens_in + tokens_out
            per_run[rid]["step_ms_total"] = step_ms
            per_run[rid]["cost_usd_estimate"] = round(cost_usd, 6)

    # 7) Pareto 成本/效果 散点数据（给前端帕累托 Tab 直接用）
    pareto_points: list[dict] = []
    for c in ctxs:
        rid = c.run_id
        tokens_total = int(c.tokens_in or 0) + int(c.tokens_out or 0)
        cost_usd = (
            (int(c.tokens_in or 0) / 1_000_000) * PRICE_IN_PER_M
            + (int(c.tokens_out or 0) / 1_000_000) * PRICE_OUT_PER_M
        )
        # 效果 Y：优先用 primary_non_neutral；否则用 acc_t3_strict；否则 composite_score (若有)
        effect_y = None
        for mid in ("acc_primary_non_neutral", "acc_t3_strict", "acc_avg_all_strict"):
            v = (c.metrics.get(mid) or {}).get("value")
            if isinstance(v, (int, float)):
                effect_y = float(v)
                break
        # 如果 composite_score 是 list[dict] 形式，查一下
        composite_lookup: dict[str, float] = {}
        if isinstance(composite, list):
            for r in composite:
                if isinstance(r, dict) and r.get("run_id") and isinstance(r.get("score"), (int, float)):
                    composite_lookup[str(r["run_id"])] = float(r["score"])
        if effect_y is None and rid in composite_lookup:
            effect_y = composite_lookup[rid]
        display = per_run.get(rid, {}).get("display_name") or (
            (c.model_version or c.runner) + (f" · {c.prompt_variant}" if c.prompt_variant else "")
        )
        pareto_points.append({
            "run_id": rid,
            "label": display,
            "runner": c.runner,
            "prompt_variant": c.prompt_variant,
            "model_version": c.model_version,
            "effect": effect_y if effect_y is not None else 0.0,
            "effect_metric_id": "acc_primary_non_neutral" if effect_y is not None else "composite",
            "cost_tokens": tokens_total,
            "cost_usd": round(cost_usd, 6),
            "step_ms": int(c.step_ms_total or 0),
            "composite_score": composite_lookup.get(rid),
        })
    # 计算非支配（帕累托）前沿：最大化 effect，最小化 cost_tokens
    def _dominates(a: dict, b: dict) -> bool:
        # a dominates b ⇔ a.effect >= b.effect AND a.cost_tokens <= b.cost_tokens，且至少一个严格不等
        eff_ok = (a.get("effect") or 0) >= (b.get("effect") or 0)
        cost_ok = (a.get("cost_tokens") or 0) <= (b.get("cost_tokens") or 0)
        strict = (
            (a.get("effect") or 0) > (b.get("effect") or 0)
            or (a.get("cost_tokens") or 0) < (b.get("cost_tokens") or 0)
        )
        return eff_ok and cost_ok and strict
    frontier_ids: set[str] = set()
    for i, p in enumerate(pareto_points):
        dominated = False
        for j, q in enumerate(pareto_points):
            if i == j:
                continue
            if _dominates(q, p):
                dominated = True
                break
        if not dominated:
            frontier_ids.add(str(p.get("run_id") or ""))
    for p in pareto_points:
        p["on_pareto_frontier"] = str(p.get("run_id") or "") in frontier_ids
    # 把 frontier 按 cost 排序后得到连线路径（从"最便宜 → 最有效但最贵"单调）
    frontier_pts = sorted(
        [p for p in pareto_points if p.get("on_pareto_frontier")],
        key=lambda p: (p.get("cost_tokens") or 0, -(p.get("effect") or 0)),
    )
    pareto_chart = {
        "points": pareto_points,
        "frontier_run_ids": [p.get("run_id") for p in frontier_pts],
        "frontier_line": [
            {"run_id": p.get("run_id"), "cost_tokens": p.get("cost_tokens"), "effect": p.get("effect")}
            for p in frontier_pts
        ],
        "defaults": {
            "y_axis": "effect",  # acc_primary_non_neutral
            "x_axis": "cost_tokens",  # tokens_total (in+out)
        },
    }

    return {
        "run_count": len(ctxs),
        "selected_metric_ids": selected_metric_ids,
        "metric_defs": {mid: all_defs[mid] for mid in selected_metric_ids if mid in all_defs},
        "per_run": per_run,
        "ranking": ranking,
        "radar_chart": radar,
        "pairwise_tests": pairwise,
        "head_to_head": head_to_head,
        "composite_score": composite,
        "pareto_chart": pareto_chart,
    }


def _build_composite_score(
    ctxs: list[ArenaRunContext],
    metric_ids: list[str],
    metric_defs: dict[str, dict],
) -> list[dict]:
    """综合得分：每个指标按 rank 倒数加权（rank 越小越好，最高权重），
    再加权求和。输出 [{run_id, score, rank}]，用于综合排名。"""
    if len(ctxs) <= 1 or not metric_ids:
        return []
    # 每个指标先 rank
    per_metric_rank: dict[str, dict[str, Optional[int]]] = {}
    for mid in metric_ids:
        rows = _rank_metric(ctxs, mid, metric_defs.get(mid))
        per_metric_rank[mid] = {r["run_id"]: r["rank"] for r in rows}
    # weight = 1 / (rank_mean)  简化：每个指标都 weight=1（对 core 翻倍）
    scores: dict[str, float] = {c.run_id: 0.0 for c in ctxs}
    weights_sum = 0.0
    for mid in metric_ids:
        w = 2.0 if metric_defs.get(mid, {}).get("tier") == "core" else 1.0
        # 对"higher_is_better"，rank=1 给最高分；对 "lower_is_better"也一样（_rank_metric 已经排序好了）
        N = len(ctxs)
        for c in ctxs:
            rk = per_metric_rank[mid].get(c.run_id)
            if rk is None:
                # 无值：给倒数第一
                s = 0.0
            else:
                # 线性映射：rk=1 → N points, rk=N → 1 point；None → 0
                s = max(0.0, N + 1 - float(rk))
            scores[c.run_id] += s * w
        weights_sum += w * N
    # 归一化到 0..100
    max_possible = weights_sum if weights_sum > 0 else 1.0
    norm = {rid: float(f"{100.0 * s / max_possible:.3f}") for rid, s in scores.items()}
    rows = [{"run_id": rid, "score": s} for rid, s in norm.items()]
    rows.sort(key=lambda x: -x["score"])
    for i, r in enumerate(rows):
        if i == 0:
            r["rank"] = 1
        else:
            r["rank"] = (i + 1) if r["score"] != rows[i - 1]["score"] else rows[i - 1]["rank"]
    return rows

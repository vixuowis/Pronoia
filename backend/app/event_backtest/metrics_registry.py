"""可插拔指标注册系统（Metrics Registry）。

设计目标：
  - 指标不再硬编码在 MetricsSummary dataclass 里；每个指标是一个独立的 Calculator
  - 新增指标只需写一个函数 + @register_metric，无需改动 dataclass / DB schema / schemas
  - 返回结构统一为 {metric_id: MetricResult}，天然支持前端按需渲染

指标分层（tier）：
  - core     ：核心必算（如 ACC 全时间窗口），无论配置都会计算
  - extended ：扩展指标（如校准度、覆盖度、收益分布），默认算，可配置关闭
  - custom   ：用户/实验性指标，需显式启用

每个 MetricResult 含：
  value        : 主值（scalar 或 dict）
  display_name : 显示名
  description  : 一句话说明
  tier         : core/extended/custom
  higher_is_better : True=越大越好（排名时用）
  breakdown    : 可选的细分（如按 market/type 分组、置信区间等）
  meta         : 自由元信息（如样本数 n、配置参数）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Iterable, Optional

from .models import EventLabel, Label, TeamPrediction, Horizon, ALL_HORIZONS


# ======================================================== 基础工具（沿用旧 metrics.py） ========

def _wilson_lower(n: int, k: int, *, z: float = 1.959963984540054) -> float:
    if n <= 0:
        return 0.0
    k = max(0, min(n, k))
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    lo = center - margin
    return 0.0 if lo < 0 else (1.0 if lo > 1 else lo)


def _wilson_upper(n: int, k: int, *, z: float = 1.959963984540054) -> float:
    if n <= 0:
        return 1.0
    k = max(0, min(n, k))
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    hi = center + margin
    return 1.0 if hi > 1 else (0.0 if hi < 0 else hi)


def _mk_acc_stat(n: int, k: int) -> dict:
    acc = (k / n) if n > 0 else 0.0
    return {
        "n": n, "k": k, "acc": float(f"{acc:.6f}"),
        "wilson_lo_95": float(f"{_wilson_lower(n, k):.6f}"),
        "wilson_hi_95": float(f"{_wilson_upper(n, k):.6f}"),
    }


# ======================================================== 数据结构定义 =========================

@dataclass
class MetricResult:
    """单个指标的计算结果。"""
    value: Any                                    # 主值：scalar 或 dict
    display_name: str                             # 前端显示名
    description: str                              # 一句话说明
    tier: str = "extended"                        # core / extended / custom
    higher_is_better: bool = True                 # 排名时方向
    breakdown: dict[str, Any] = field(default_factory=dict)  # 细分：分组、CI、分布
    meta: dict[str, Any] = field(default_factory=dict)       # 元信息：样本数、配置等

    def to_dict(self) -> dict:
        return asdict(self)


# ======================================================== 计算上下文 ===========================

@dataclass
class ComputeContext:
    """传给每个指标计算器的上下文。"""
    pairs: list[tuple[TeamPrediction, EventLabel]]   # pred ∩ labels 的配对
    n_total: int
    primary_oracle_horizon: Horizon
    epsilon: float
    exclude_non_significant: bool
    non_sig_event_ids: set[str]                       # 被显著性过滤掉的 event_id

    def label_of(self, lab: EventLabel, h: str) -> Label:
        return getattr(lab, f"label_{h}", "") or ""


# ======================================================== 注册表 ==============================

MetricFn = Callable[[ComputeContext], MetricResult]

_REGISTRY: dict[str, dict] = {}  # metric_id → {fn, display_name, description, tier, higher_is_better}


def register_metric(
    metric_id: str,
    *,
    display_name: str,
    description: str,
    tier: str = "extended",
    higher_is_better: bool = True,
) -> Callable[[MetricFn], MetricFn]:
    """注册一个指标。

    用法：
        @register_metric("acc_t3_strict", display_name="T3 准确率(严格)",
                         description="T3 窗口，abstain/neutral 算错", tier="core")
        def calc_acc_t3_strict(ctx: ComputeContext) -> MetricResult:
            ...
    """
    def deco(fn: MetricFn) -> MetricFn:
        _REGISTRY[metric_id] = {
            "fn": fn,
            "display_name": display_name,
            "description": description,
            "tier": tier,
            "higher_is_better": higher_is_better,
        }
        return fn
    return deco


def list_metric_defs(*, tier: Optional[str] = None) -> dict[str, dict]:
    """列出已注册的指标元信息（不含 fn）。"""
    out = {}
    for mid, info in _REGISTRY.items():
        if tier and info["tier"] != tier:
            continue
        out[mid] = {k: v for k, v in info.items() if k != "fn"}
    return out


def get_metric_def(metric_id: str) -> Optional[dict]:
    info = _REGISTRY.get(metric_id)
    if not info:
        return None
    return {k: v for k, v in info.items() if k != "fn"}


# ======================================================== 核心计算引擎 ========================

def _build_context(
    *,
    predictions: list[TeamPrediction],
    labels: list[EventLabel],
    epsilon: float,
    exclude_non_significant: bool,
    primary_oracle_horizon: Horizon,
) -> ComputeContext:
    if primary_oracle_horizon not in ALL_HORIZONS:
        primary_oracle_horizon = "t3"  # type: ignore[assignment]

    pred_by_id = {p.event_id: p for p in predictions if p.event_id}
    pairs: list[tuple[TeamPrediction, EventLabel]] = []
    for lab in labels:
        p = pred_by_id.get(lab.event_id)
        if p is not None:
            pairs.append((p, lab))

    non_sig_event_ids: set[str] = set()
    if exclude_non_significant:
        for _, lab in pairs:
            pkey = f"car_{primary_oracle_horizon}_pvalue"
            p_val = getattr(lab, pkey, None)
            if p_val is None and primary_oracle_horizon == "t3":
                p_val = getattr(lab, "car_t3_pvalue", None)
            if p_val is not None and p_val > 0.10:
                non_sig_event_ids.add(lab.event_id)

    return ComputeContext(
        pairs=pairs,
        n_total=len(pairs),
        primary_oracle_horizon=primary_oracle_horizon,
        epsilon=float(epsilon),
        exclude_non_significant=exclude_non_significant,
        non_sig_event_ids=non_sig_event_ids,
    )


def compute_all_metrics(
    *,
    predictions: list[TeamPrediction],
    labels: list[EventLabel],
    epsilon: float = 0.005,
    exclude_non_significant: bool = False,
    primary_oracle_horizon: Horizon = "t3",
    enabled_metrics: Optional[Iterable[str]] = None,
    disabled_metrics: Optional[Iterable[str]] = None,
) -> dict[str, MetricResult]:
    """计算所有（或指定的）已注册指标。

    规则：
      - tier=core 的指标永远启用
      - enabled_metrics=None → 启用全部非 custom
      - disabled_metrics 优先级最高
    """
    ctx = _build_context(
        predictions=predictions, labels=labels, epsilon=epsilon,
        exclude_non_significant=exclude_non_significant,
        primary_oracle_horizon=primary_oracle_horizon,
    )

    # 决定启用哪些 metric_id
    enabled: set[str] = set()
    for mid, info in _REGISTRY.items():
        if info["tier"] == "core":
            enabled.add(mid)
        elif enabled_metrics is None and info["tier"] != "custom":
            enabled.add(mid)
        elif enabled_metrics is not None and mid in enabled_metrics:
            enabled.add(mid)

    if disabled_metrics:
        enabled -= set(disabled_metrics)

    results: dict[str, MetricResult] = {}
    for mid in sorted(enabled):
        info = _REGISTRY[mid]
        try:
            res = info["fn"](ctx)
            # 兜底：填充显示名等（如果 Calculator 自己没填）
            if not res.display_name:
                res.display_name = info["display_name"]
            if not res.description:
                res.description = info["description"]
            if not res.tier:
                res.tier = info["tier"]
            results[mid] = res
        except Exception as exc:  # noqa: BLE001
            # 单个指标失败不影响其他
            results[mid] = MetricResult(
                value=None,
                display_name=info["display_name"],
                description=f"[计算失败] {exc}",
                tier=info["tier"],
                higher_is_better=info["higher_is_better"],
                meta={"error": str(exc)},
            )
    return results


# ======================================================== 指标定义 ============================

def _evaluate_horizon_strict(ctx: ComputeContext, h: str) -> dict:
    """对指定 horizon 计算严格口径 ACC：
    剔除 pred_abstain ∨ oracle_abstain；neutral=算错。返回 _mk_acc_stat dict。
    """
    n_s, k_s = 0, 0
    for p, lab in ctx.pairs:
        lab_h = ctx.label_of(lab, h)
        pred_abstain = bool(p.abstain)
        oracle_abstain = (not lab_h.strip())
        if ctx.exclude_non_significant and lab.event_id in ctx.non_sig_event_ids:
            oracle_abstain = True
        if pred_abstain or oracle_abstain:
            continue
        n_s += 1
        if lab_h == "neutral":
            continue
        if p.pred_direction == lab_h:
            k_s += 1
    return _mk_acc_stat(n_s, k_s)


def _evaluate_primary_non_neutral(ctx: ComputeContext, h: str) -> dict:
    """只对 primary horizon：剔除 abstain 且 oracle∈{up,down} 才计分。"""
    n_nn, k_nn = 0, 0
    for p, lab in ctx.pairs:
        lab_h = ctx.label_of(lab, h)
        if bool(p.abstain) or (not lab_h.strip()):
            continue
        if lab_h not in {"up", "down"}:
            continue
        n_nn += 1
        if p.pred_direction == lab_h:
            k_nn += 1
    return _mk_acc_stat(n_nn, k_nn)


def _evaluate_primary_significant_only(ctx: ComputeContext, h: str) -> dict:
    """只对 primary horizon：pvalue<0.10 且非 abstain 且非 neutral。"""
    n_sig, k_sig = 0, 0
    for p, lab in ctx.pairs:
        if p.abstain:
            continue
        pkey = f"car_{h}_pvalue"
        p_val = getattr(lab, pkey, None)
        if h == "t3" and p_val is None:
            p_val = getattr(lab, "car_t3_pvalue", None)
        if p_val is None or p_val >= 0.10:
            continue
        lh = ctx.label_of(lab, h)
        if not lh.strip():
            continue
        if lh == "neutral":
            continue
        n_sig += 1
        if p.pred_direction == lh:
            k_sig += 1
    return _mk_acc_stat(n_sig, k_sig)


# --- CORE: 12 个 horizon 的严格 ACC（与旧 MetricsSummary 对齐） ---

def _register_acc_strict(h: Horizon, display_name: str, order: int = 100) -> None:
    """生成并注册一个 horizon 的 strict ACC 指标。"""
    @register_metric(
        f"acc_{h}_strict",
        display_name=display_name,
        description=f"{display_name}：abstain/neutral 算错，最严格口径",
        tier="core",
        higher_is_better=True,
    )
    def _calc(ctx: ComputeContext, _h=h) -> MetricResult:
        stat = _evaluate_horizon_strict(ctx, _h)
        return MetricResult(
            value=stat["acc"],
            display_name=display_name,
            description=f"{display_name}：abstain/neutral 算错",
            tier="core",
            higher_is_better=True,
            breakdown={"wilson": {"lo_95": stat["wilson_lo_95"], "hi_95": stat["wilson_hi_95"]}},
            meta={"n": stat["n"], "k": stat["k"], "horizon": _h, "mode": "strict"},
        )


for _h, _dn in [
    ("t1", "T1 准确率"),
    ("t3", "T3 准确率"),
    ("t5", "T5 准确率"),
    ("t7", "T7 准确率"),
    ("t15", "T15 准确率"),
    ("t30", "T30 准确率"),
    ("t60", "T60 准确率"),
    ("avg_short", "短期平均准确率"),
    ("avg_mid", "中期平均准确率"),
    ("avg_long", "长期平均准确率"),
    ("avg_all", "全周期平均准确率"),
    ("consensus66", "共识66准确率"),
]:
    _register_acc_strict(_h, _dn)  # type: ignore[arg-type]


# --- CORE: Primary horizon 专项口径 ---

@register_metric(
    "acc_primary_non_neutral",
    display_name="主口径 非中性准确率",
    description="Primary horizon：剔除 abstain 后，只在 oracle∈{up,down} 上计分（贴近实战）",
    tier="core",
    higher_is_better=True,
)
def calc_acc_primary_non_neutral(ctx: ComputeContext) -> MetricResult:
    h = ctx.primary_oracle_horizon
    stat = _evaluate_primary_non_neutral(ctx, h)
    return MetricResult(
        value=stat["acc"],
        display_name="主口径 非中性准确率",
        description=f"Primary({h}) 只在 up/down 标签上计分",
        tier="core",
        higher_is_better=True,
        breakdown={"wilson": {"lo_95": stat["wilson_lo_95"], "hi_95": stat["wilson_hi_95"]}},
        meta={"n": stat["n"], "k": stat["k"], "primary_horizon": h, "mode": "non_neutral"},
    )


@register_metric(
    "acc_primary_significant_only",
    display_name="主口径 显著事件准确率",
    description="Primary horizon：仅 oracle pvalue<0.10 的显著事件计分（剔除噪声事件）",
    tier="core",
    higher_is_better=True,
)
def calc_acc_primary_significant_only(ctx: ComputeContext) -> MetricResult:
    h = ctx.primary_oracle_horizon
    stat = _evaluate_primary_significant_only(ctx, h)
    return MetricResult(
        value=stat["acc"],
        display_name="主口径 显著事件准确率",
        description=f"Primary({h}) 仅 car pvalue<0.10 的事件",
        tier="core",
        higher_is_better=True,
        breakdown={"wilson": {"lo_95": stat["wilson_lo_95"], "hi_95": stat["wilson_hi_95"]}},
        meta={"n": stat["n"], "k": stat["k"], "primary_horizon": h, "mode": "significant_only"},
    )


# --- EXTENDED: 覆盖度 / 弃权率 ---

@register_metric(
    "coverage_rate",
    display_name="预测覆盖率",
    description="(pred ∩ labels 且 非 abstain) / 总 labels 数；越高代表越敢给结论",
    tier="extended",
    higher_is_better=True,
)
def calc_coverage_rate(ctx: ComputeContext) -> MetricResult:
    n_labels = len({lab.event_id for _, lab in ctx.pairs})
    n_covered = sum(1 for p, _ in ctx.pairs if not p.abstain)
    rate = (n_covered / n_labels) if n_labels > 0 else 0.0
    return MetricResult(
        value=rate,
        display_name="预测覆盖率",
        description="非 abstain 的预测数 / 总事件数",
        tier="extended",
        higher_is_better=True,
        meta={"n_total": n_labels, "n_covered": n_covered, "n_abstain": n_labels - n_covered},
    )


@register_metric(
    "abstain_rate",
    display_name="弃权率",
    description="pred_abstain=True 的比例；越低越好（但过低可能导致 accuracy 下降）",
    tier="extended",
    higher_is_better=False,
)
def calc_abstain_rate(ctx: ComputeContext) -> MetricResult:
    n = len(ctx.pairs)
    k = sum(1 for p, _ in ctx.pairs if p.abstain)
    rate = (k / n) if n > 0 else 0.0
    return MetricResult(
        value=rate,
        display_name="弃权率",
        description="abstain / 总配对数",
        tier="extended",
        higher_is_better=False,
        meta={"n": n, "abstain": k},
    )


# --- EXTENDED: 校准度（Confidence Calibration）---

@register_metric(
    "calibration_mse",
    display_name="置信度校准 MSE",
    description="(confidence - actual_accuracy)^2 的均值；越小代表置信度越准",
    tier="extended",
    higher_is_better=False,
)
def calc_calibration_mse(ctx: ComputeContext) -> MetricResult:
    """简单的置信度校准：
    将 prediction 按 confidence 分桶（如果有的话），每桶 (实际正确率 - avg_confidence)^2。
    无 confidence 时返回 None。
    """
    buckets: dict[int, list[int]] = {}  # bucket_key(0..9) → [1=correct, 0=wrong]
    h = ctx.primary_oracle_horizon
    n_valid = 0
    sq_sum = 0.0
    confidences: list[float] = []
    actuals: list[int] = []
    for p, lab in ctx.pairs:
        if p.abstain or p.confidence is None:
            continue
        lab_h = ctx.label_of(lab, h)
        if not lab_h.strip() or lab_h == "neutral":
            continue
        actual = 1 if (p.pred_direction == lab_h) else 0
        conf = max(0.0, min(1.0, float(p.confidence)))
        confidences.append(conf)
        actuals.append(actual)
        n_valid += 1
        sq_sum += (conf - actual) ** 2
        bk = int(conf * 10)
        if bk > 9:
            bk = 9
        buckets.setdefault(bk, []).append(actual)

    if n_valid == 0:
        return MetricResult(
            value=None,
            display_name="置信度校准 MSE",
            description="无 confidence 数据或无有效样本",
            tier="extended",
            higher_is_better=False,
            meta={"n_valid": 0},
        )

    mse = sq_sum / n_valid
    # 分桶详情
    bucket_stats = {}
    for bk in range(10):
        arr = buckets.get(bk, [])
        if arr:
            bucket_stats[f"{bk*10}-{(bk+1)*10}%"] = {
                "n": len(arr),
                "acc": sum(arr) / len(arr),
                "confidence_mid": (bk + 0.5) * 0.1,
            }
    return MetricResult(
        value=float(f"{mse:.6f}"),
        display_name="置信度校准 MSE",
        description="(confidence - actual_accuracy)^2 均值",
        tier="extended",
        higher_is_better=False,
        breakdown={"buckets": bucket_stats},
        meta={"n_valid": n_valid},
    )


# --- EXTENDED: 方向偏差（是否系统性偏向 up/down）---

@register_metric(
    "direction_bias",
    display_name="方向偏差",
    description="预测 up 的比例 vs oracle up 的比例；绝对值越大代表系统偏差越严重",
    tier="extended",
    higher_is_better=False,
)
def calc_direction_bias(ctx: ComputeContext) -> MetricResult:
    h = ctx.primary_oracle_horizon
    preds_up, preds_down, pred_total = 0, 0, 0
    oracle_up, oracle_down, oracle_total = 0, 0, 0
    for p, lab in ctx.pairs:
        if not p.abstain:
            pred_total += 1
            if p.pred_direction == "up":
                preds_up += 1
            elif p.pred_direction == "down":
                preds_down += 1
        lab_h = ctx.label_of(lab, h)
        if lab_h in {"up", "down"}:
            oracle_total += 1
            if lab_h == "up":
                oracle_up += 1
            elif lab_h == "down":
                oracle_down += 1
    pred_up_ratio = (preds_up / pred_total) if pred_total > 0 else 0.0
    oracle_up_ratio = (oracle_up / oracle_total) if oracle_total > 0 else 0.0
    bias = pred_up_ratio - oracle_up_ratio
    return MetricResult(
        value=float(f"{abs(bias):.6f}"),
        display_name="方向偏差",
        description="|pred_up_ratio - oracle_up_ratio|",
        tier="extended",
        higher_is_better=False,
        breakdown={
            "pred_up_ratio": pred_up_ratio,
            "oracle_up_ratio": oracle_up_ratio,
            "signed_bias": float(f"{bias:.6f}"),
        },
        meta={
            "pred_total": pred_total, "preds_up": preds_up, "preds_down": preds_down,
            "oracle_total": oracle_total, "oracle_up": oracle_up, "oracle_down": oracle_down,
        },
    )


# --- EXTENDED: 平均 Oracle CAR（用于判断数据集本身的"可预测性"）---

@register_metric(
    "avg_car_primary",
    display_name="主窗口平均 CAR",
    description="Primary horizon 上所有有效标签的平均累计异常收益率；参考基准",
    tier="extended",
    higher_is_better=True,
)
def calc_avg_car_primary(ctx: ComputeContext) -> MetricResult:
    h = ctx.primary_oracle_horizon
    cars: list[float] = []
    for _, lab in ctx.pairs:
        c = getattr(lab, f"car_{h}", None)
        lab_h = ctx.label_of(lab, h)
        if (lab_h or "").strip() and isinstance(c, (int, float)):
            cars.append(float(c))
    avg = sum(cars) / len(cars) if cars else 0.0
    return MetricResult(
        value=float(f"{avg:.6f}"),
        display_name="主窗口平均 CAR",
        description=f"Primary({h}) 有效标签平均累计异常收益率",
        tier="extended",
        higher_is_better=True,
        meta={"n": len(cars), "horizon": h, "min": min(cars) if cars else None, "max": max(cars) if cars else None},
    )


# --- EXTENDED: 分组准确率（按 market / type）---

@register_metric(
    "acc_by_market",
    display_name="按市场分组准确率",
    description="Primary horizon 严格口径，按 CN/US/HK 等市场分组的准确率",
    tier="extended",
    higher_is_better=True,
)
def calc_acc_by_market(ctx: ComputeContext) -> MetricResult:
    h = ctx.primary_oracle_horizon
    grouped: dict[str, list[tuple[TeamPrediction, EventLabel]]] = {}
    for p, lab in ctx.pairs:
        if p.abstain:
            continue
        k = (lab.market or "UNK")
        grouped.setdefault(k, []).append((p, lab))
    breakdown: dict[str, Any] = {}
    for k, items in grouped.items():
        n_s, k_s = 0, 0
        for p, lab in items:
            lab_h = ctx.label_of(lab, h)
            if not lab_h.strip():
                continue
            n_s += 1
            if lab_h == "neutral":
                continue
            if p.pred_direction == lab_h:
                k_s += 1
        breakdown[k] = _mk_acc_stat(n_s, k_s)
    # 主值 = 各组 n 加权平均 acc
    total_n = sum(v["n"] for v in breakdown.values())
    weighted_avg = (
        sum(v["acc"] * v["n"] for v in breakdown.values()) / total_n
        if total_n > 0 else 0.0
    )
    return MetricResult(
        value=float(f"{weighted_avg:.6f}"),
        display_name="按市场分组准确率",
        description=f"Primary({h}) 按市场分组严格口径",
        tier="extended",
        higher_is_better=True,
        breakdown=breakdown,
        meta={"n_groups": len(breakdown), "total_n": total_n, "horizon": h},
    )


@register_metric(
    "acc_by_type",
    display_name="按事件类型分组准确率",
    description="Primary horizon 严格口径，按 event_type_l2 分组的准确率",
    tier="extended",
    higher_is_better=True,
)
def calc_acc_by_type(ctx: ComputeContext) -> MetricResult:
    h = ctx.primary_oracle_horizon
    grouped: dict[str, list[tuple[TeamPrediction, EventLabel]]] = {}
    for p, lab in ctx.pairs:
        if p.abstain:
            continue
        k = (lab.event_type_l2 or "UNK")
        grouped.setdefault(k, []).append((p, lab))
    breakdown: dict[str, Any] = {}
    for k, items in grouped.items():
        n_s, k_s = 0, 0
        for p, lab in items:
            lab_h = ctx.label_of(lab, h)
            if not lab_h.strip():
                continue
            n_s += 1
            if lab_h == "neutral":
                continue
            if p.pred_direction == lab_h:
                k_s += 1
        breakdown[k] = _mk_acc_stat(n_s, k_s)
    total_n = sum(v["n"] for v in breakdown.values())
    weighted_avg = (
        sum(v["acc"] * v["n"] for v in breakdown.values()) / total_n
        if total_n > 0 else 0.0
    )
    return MetricResult(
        value=float(f"{weighted_avg:.6f}"),
        display_name="按事件类型分组准确率",
        description=f"Primary({h}) 按 event_type_l2 分组严格口径",
        tier="extended",
        higher_is_better=True,
        breakdown=breakdown,
        meta={"n_groups": len(breakdown), "total_n": total_n, "horizon": h},
    )


# --- EXTENDED: Top-box / Bottom-box 置信度表现 ---

@register_metric(
    "acc_high_confidence",
    display_name="高置信度准确率",
    description="confidence ≥ 0.8 的样本准确率；越高代表高置信区间越可靠",
    tier="extended",
    higher_is_better=True,
)
def calc_acc_high_confidence(ctx: ComputeContext) -> MetricResult:
    h = ctx.primary_oracle_horizon
    n_s, k_s = 0, 0
    for p, lab in ctx.pairs:
        if p.abstain or p.confidence is None or p.confidence < 0.8:
            continue
        lab_h = ctx.label_of(lab, h)
        if not lab_h.strip():
            continue
        n_s += 1
        if lab_h == "neutral":
            continue
        if p.pred_direction == lab_h:
            k_s += 1
    stat = _mk_acc_stat(n_s, k_s)
    return MetricResult(
        value=stat["acc"],
        display_name="高置信度准确率",
        description="confidence ≥ 0.8 的严格准确率",
        tier="extended",
        higher_is_better=True,
        breakdown={"wilson": {"lo_95": stat["wilson_lo_95"], "hi_95": stat["wilson_hi_95"]}},
        meta={"n": stat["n"], "k": stat["k"], "threshold": 0.8, "horizon": h},
    )


# --- EXTENDED: 与 Prior 方向一致度 ---

@register_metric(
    "prior_alignment_rate",
    display_name="先验方向一致率",
    description="pred_direction 与 direction_prior 相同的比例；高代表模型会独立思考，低代表盲从先验（需结合准确率看）",
    tier="extended",
    higher_is_better=True,  # 非单调：过高代表不思考，过低代表不尊重先验
)
def calc_prior_alignment_rate(ctx: ComputeContext) -> MetricResult:
    n, k = 0, 0
    for p, _ in ctx.pairs:
        if p.abstain:
            continue
        # direction_prior 在 prediction 里没有，是 events 里的字段；
        # 这里从 ctx.pairs 无法直接取到，因此需要通过 run 的 events 文件。
        # 为了不让指标卡住，这里只统计那些已经"在 p 或 lab 上暴露了 prior"的情况：
        prior = getattr(p, "direction_prior", None)
        if prior is None:
            # 从 lab 上试试（EventLabel 没有 direction_prior，但兼容一些扩展字段）
            continue
        n += 1
        if str(prior) == str(p.pred_direction):
            k += 1
    if n == 0:
        return MetricResult(
            value=None,
            display_name="先验方向一致率",
            description="本回测无 direction_prior 数据",
            tier="extended",
            higher_is_better=True,
            meta={"n_valid": 0},
        )
    rate = k / n
    return MetricResult(
        value=rate,
        display_name="先验方向一致率",
        description="pred == direction_prior 的比例",
        tier="extended",
        higher_is_better=True,
        meta={"n": n, "aligned": k},
    )

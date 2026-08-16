from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal

from .models import EventLabel, Label, TeamPrediction


Horizon = Literal["t1", "t3", "t5"]


def _wilson_lower(n: int, k: int, *, z: float = 1.959963984540054) -> float:
    """Wilson 95% CI lower bound (n=样本数, k=正确数). n=0 → 0"""
    if n <= 0: return 0.0
    if k < 0: k = 0
    if k > n: k = n
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    lo = center - margin
    return 0.0 if lo < 0 else (1.0 if lo > 1 else lo)


def _wilson_upper(n: int, k: int, *, z: float = 1.959963984540054) -> float:
    if n <= 0: return 1.0
    if k < 0: k = 0
    if k > n: k = n
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    hi = center + margin
    return 1.0 if hi > 1 else (0.0 if hi < 0 else hi)


@dataclass(frozen=True)
class AccWithWilson:
    """单一口径的 ACC + Wilson 95% CI。n=分母数, k=正确数, acc=k/n, lo/hi=Wilson 95% 上下限"""
    n: int
    k: int
    acc: float
    wilson_lo_95: float
    wilson_hi_95: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n, "k": self.k, "acc": float(f"{self.acc:.6f}"),
            "wilson_lo_95": float(f"{self.wilson_lo_95:.6f}"),
            "wilson_hi_95": float(f"{self.wilson_hi_95:.6f}"),
        }


@dataclass(frozen=True)
class MetricsSummary:
    epsilon: float
    n_total: int                              # pairs 总数（pred∩labels）
    n_abstain_pred: int                       # 预测器 abstain=True 计数
    n_abstain_oracle: int                     # oracle label_t3 为空（car_t3 空 / 无行情）计数
    n_non_significant: int = 0                # 因 car_t3_pvalue>0.10 被剔除的标签数（exclude_non_significant=True 时）
    # 主口径：剔除 (pred_abstain ∨ oracle_abstain)；neutral=算错 （最严格，设计文档 §5 默认口径）
    acc_t1_strict: AccWithWilson = field(default_factory=lambda: AccWithWilson(0,0,0.0,0.0,1.0))
    acc_t3_strict: AccWithWilson = field(default_factory=lambda: AccWithWilson(0,0,0.0,0.0,1.0))
    acc_t5_strict: AccWithWilson = field(default_factory=lambda: AccWithWilson(0,0,0.0,0.0,1.0))
    # 次口径：剔除 abstain 且 oracle≠neutral 时才计（只在有方向样本上测）
    acc_t3_non_neutral: AccWithWilson = field(default_factory=lambda: AccWithWilson(0,0,0.0,0.0,1.0))
    # 仅统计显著事件口径：只在 car_t3_pvalue<0.10 的标签上算 t3 strict ACC
    acc_t3_significant_only: AccWithWilson = field(default_factory=lambda: AccWithWilson(0,0,0.0,0.0,1.0))
    # 保留老字段（向后兼容）：严格口径的 acc 值
    acc_t1: float = 0.0
    acc_t3: float = 0.0
    acc_t5: float = 0.0
    avg_car_t1: float = 0.0
    avg_car_t3: float = 0.0
    avg_car_t5: float = 0.0
    acc_by_market: dict[str, dict[str, Any]] = field(default_factory=dict)
    acc_by_type: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        # 把顶层的 AccWithWilson 对象展开成纯 dict（含 float 格式化）
        for k in list(d.keys()):
            v = d[k]
            if isinstance(v, AccWithWilson):
                d[k] = v.to_dict()
        # 处理 group dicts (acc_by_market / acc_by_type) 中嵌套的 AccWithWilson：
        # asdict 已把这些递归转成 plain dict，这里从 self 取原始对象调用 to_dict()
        # 以应用统一的 float 格式化
        for group_field in ("acc_by_market", "acc_by_type"):
            original = getattr(self, group_field, None)
            if not isinstance(original, dict):
                continue
            new_group: dict[str, Any] = {}
            for g_k, g_v in original.items():
                if isinstance(g_v, dict):
                    new_inner: dict[str, Any] = {}
                    for i_k, i_v in g_v.items():
                        new_inner[i_k] = i_v.to_dict() if isinstance(i_v, AccWithWilson) else i_v
                    new_group[g_k] = new_inner
                else:
                    new_group[g_k] = g_v
            d[group_field] = new_group
        return d


def label_from_car(car: float, *, epsilon: float) -> Label:
    if car > epsilon:
        return "up"
    if car < -epsilon:
        return "down"
    return "neutral"


def _mk_wilson(n: int, k: int) -> AccWithWilson:
    acc = (k / n) if n > 0 else 0.0
    return AccWithWilson(n=n, k=k, acc=acc, wilson_lo_95=_wilson_lower(n,k), wilson_hi_95=_wilson_upper(n,k))


def compute_metrics(
    *,
    predictions: list[TeamPrediction],
    labels: list[EventLabel],
    epsilon: float = 0.005,
    exclude_non_significant: bool = False,
) -> MetricsSummary:
    pred_by_id = {p.event_id: p for p in predictions if p.event_id}
    pairs: list[tuple[TeamPrediction, EventLabel]] = []
    for lab in labels:
        p = pred_by_id.get(lab.event_id)
        if p is None:
            continue
        pairs.append((p, lab))

    n_total = len(pairs)
    n_abstain_pred = sum(1 for p, _ in pairs if p.abstain)
    n_abstain_oracle = sum(1 for _, lab in pairs if not (lab.label_t3 or "").strip())

    # 显著性过滤（向后兼容：旧 EventLabel 没有 car_t3_pvalue 字段时 getattr 返回 None）
    # 非显著 = car_t3_pvalue 不为 None 且 > 0.10（CAR 太小、方向标签可能是噪声）
    def _is_non_significant(lab: EventLabel) -> bool:
        p_val = getattr(lab, "car_t3_pvalue", None)
        return p_val is not None and p_val > 0.10

    # 仅在 exclude_non_significant=True 时把非显著标签计入剔除计数
    non_sig_event_ids: set[str] = set()
    if exclude_non_significant:
        for p, lab in pairs:
            if _is_non_significant(lab):
                non_sig_event_ids.add(lab.event_id)
    n_non_significant = len(non_sig_event_ids)

    def _evaluate(h: Horizon):
        """返回 (strict_acc, nonneutral_t3_acc=None_otherwise) 两个 AccWithWilson"""
        rows = []
        for p, lab in pairs:
            lab_h: Label = getattr(lab, f"label_{h}") or ""
            pred_abstain = bool(p.abstain)
            oracle_abstain = (not lab_h.strip())
            # 显著性过滤：开启时把非显著标签当作 oracle_abstain 剔除（不进 strict 分母）
            if exclude_non_significant and lab.event_id in non_sig_event_ids:
                oracle_abstain = True
            rows.append((p, lab_h, pred_abstain, oracle_abstain))

        # Strict 口径：
        #   分母 = not(pred_abstain ∨ oracle_abstain)
        #   分子 = 分母中 pred_direction == label_h **且** 仅 label_h in {up,down} 时判对
        #          （即 oracle=neutral 即使方向相等也算错，严格对齐 §5）
        n_s = 0; k_s = 0
        for p, lab_h, pa, oa in rows:
            if pa or oa: continue
            n_s += 1
            if lab_h == "neutral":
                continue  # k_s 不增 → 与 _hard_correct 逻辑一致（neutral 判错）
            if p.pred_direction == lab_h:
                k_s += 1
        strict = _mk_wilson(n_s, k_s)

        # Non-neutral 口径（仅 t3 暴露）：
        #   分母 = not abstain 且 oracle∈{up,down}；分子 = 方向一致
        non_neutral: AccWithWilson | None = None
        if h == "t3":
            n_nn = 0; k_nn = 0
            for p, lab_h, pa, oa in rows:
                if pa or oa: continue
                if lab_h not in {"up","down"}: continue
                n_nn += 1
                if p.pred_direction == lab_h:
                    k_nn += 1
            non_neutral = _mk_wilson(n_nn, k_nn)
        return strict, non_neutral

    s1, _ = _evaluate("t1")
    s3, s3_nn = _evaluate("t3")
    s5, _ = _evaluate("t5")
    s3_nn = s3_nn or _mk_wilson(0,0)

    # acc_t3_significant_only：只在 car_t3_pvalue<0.10 的显著标签上算 t3 strict ACC
    # （独立于 exclude_non_significant 开关；旧标签无 p 值则不被计入分母）
    n_sig = 0; k_sig = 0
    for p, lab in pairs:
        p_val = getattr(lab, "car_t3_pvalue", None)
        if p_val is None or p_val >= 0.10:
            continue
        if p.abstain: continue
        lab_t3 = (lab.label_t3 or "").strip()
        if not lab_t3: continue
        n_sig += 1
        if lab_t3 == "neutral": continue
        if p.pred_direction == lab_t3: k_sig += 1
    acc_t3_significant_only = _mk_wilson(n_sig, k_sig)

    # avg car：对 oracle car_t* 非空（非 0）的样本求均值
    def car_for(h: Horizon) -> list[float]:
        out = []
        for _, lab in pairs:
            c = getattr(lab, f"car_{h}")
            # EventLabel.from_dict 里用了 float(car or 0.0)，这里粗略区分：label 非空才算有效 car
            lab_h = getattr(lab, f"label_{h}")
            if (lab_h or "").strip() and isinstance(c, (int, float)):
                out.append(float(c))
        return out

    avg_car_t1 = sum(car_for("t1")) / len(car_for("t1")) if car_for("t1") else 0.0
    avg_car_t3 = sum(car_for("t3")) / len(car_for("t3")) if car_for("t3") else 0.0
    avg_car_t5 = sum(car_for("t5")) / len(car_for("t5")) if car_for("t5") else 0.0

    def group_key_market(lab: EventLabel) -> str:
        return lab.market or "UNK"

    def group_key_type(lab: EventLabel) -> str:
        return lab.event_type_l2 or "UNK"

    # group 级 ACC：沿用严格口径逻辑，每个 horizon 都打 Wilson 95% CI
    # 结构：out[k] = {"n": int, "acc_t1": AccWithWilson, "acc_t3": AccWithWilson, "acc_t5": AccWithWilson}
    def group_acc(key_fn) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[tuple[TeamPrediction, EventLabel]]] = {}
        for p, lab in pairs:
            if p.abstain: continue
            k = key_fn(lab)
            grouped.setdefault(k, []).append((p, lab))
        out: dict[str, dict[str, Any]] = {}
        for k, items in grouped.items():
            per: dict[str, Any] = {"n": int(len(items))}
            for h in ("t1","t3","t5"):
                n_s, k_s = 0, 0
                for p, lab in items:
                    lab_h = getattr(lab, f"label_{h}") or ""
                    if not lab_h.strip(): continue
                    n_s += 1
                    if lab_h == "neutral": continue
                    if p.pred_direction == lab_h: k_s += 1
                per[f"acc_{h}"] = _mk_wilson(n_s, k_s)
            out[k] = per
        return out

    return MetricsSummary(
        epsilon=float(epsilon),
        n_total=n_total,
        n_abstain_pred=n_abstain_pred,
        n_abstain_oracle=n_abstain_oracle,
        n_non_significant=n_non_significant,
        acc_t1_strict=s1,
        acc_t3_strict=s3,
        acc_t5_strict=s5,
        acc_t3_non_neutral=s3_nn,
        acc_t3_significant_only=acc_t3_significant_only,
        # 向后兼容老字段
        acc_t1=s1.acc,
        acc_t3=s3.acc,
        acc_t5=s5.acc,
        avg_car_t1=avg_car_t1,
        avg_car_t3=avg_car_t3,
        avg_car_t5=avg_car_t5,
        acc_by_market=group_acc(group_key_market),
        acc_by_type=group_acc(group_key_type),
    )


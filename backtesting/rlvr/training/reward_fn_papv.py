"""reward_fn_papv.py — Pronoia-PAPV 六元 Reward（核心 = 断言判断准确性 + 校准）。

Reward = Σ w_i * R_i，总范围约 [-0.20, +1.00]
  R0 10%  格式合规：可解析 CLAIM 数 ∈ [3,6] + 四段标题齐全
  R1 15%  可验证性：断言可结算占比（指标在面板内 & label 有数值）——PAPV 三条件
  R2 45%  判断准确性：correct / settleable（核心指标：断言提得准不准）
  R3 20%  置信度校准：1 - 2·Brier（高置信押对加分、押错重罚）
  R4 5%   逻辑链：【2】段存在且覆盖各断言
  R5 5%   覆盖多样性：≥2 个 horizon、≥2 个指标族（防止只会断言 car_t3>0）

设计原则（对应 PAPV 提案 §七「过拟合看答案猜」对策）：
  断言由模型自主选择指标/阈值构成，reward 只在「判断真假」上给分——
  模型要学的是「对哪些命题有把握、对哪些没把握」，而非记住单一方向标签。

v6 修复（阈值单位错位）：
  · parse_claims 增加单位守卫：裸数字 |thr|>0.15 按本意百分数归一（÷100）；
  · settle_all(drop_trivial=True)：|实际值| < |阈值|/2 的送分断言不计入 R1/R2/R3，
    从激励上关闭「写大阈值换命中」的捷径。

v6.1 残留偏差修正（40 案例 case study 四启示之 B3/B4/B5，只做 [-0.15, 0] 的额外扣分）：
  B3 极端事件显著性惩罚：T0 反应极端（|car_t1| 或 |ret_t1| > 5%）时，
     错误主张「不显著」的 pvalue 断言每条额外 -0.05（涨停/跌停后几乎必然显著）。
  B4 car/ret 分化惩罚：基准同向大跌（min bm_ret_tX ≤ -2%）时，
     错误的 ret 下行断言每条额外 -0.05（基准同跌 → 超跌反弹，car 空不应连坐 ret 空）。
  B5 T0 噪音事件衰减：中标/经营数据/框架协议类事件 T0 为负时，
     错误的 car/ret 下行断言每条额外 -0.04（此类 T0 负反馈多为噪音而非趋势）。
"""
from __future__ import annotations

import re
from typing import Optional

import sys
from pathlib import Path
_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from papv_claims import (  # noqa: E402
    METRIC_PANEL, parse_claims, settle_all, settle_claim, is_trivial_claim,
    metric_family,
)

SECTION_HEADERS = {
    "R0": r"【\s*0[.\s]*断言规划\s*】",
    "R1a": r"【\s*1[.\s]*断言列表\s*】",
    "R2a": r"【\s*2[.\s]*逻辑链\s*】",
    "R3a": r"【\s*3[.\s]*反方与风险\s*】",
}


def _has_section(text: str, key: str) -> bool:
    return re.search(SECTION_HEADERS[key], text) is not None


# ============ v6.1 残留偏差修正辅助 ============

# B5：T0 负反馈多为噪音的事件类型（事件标题/正文关键词）
_T0_NOISE_EVENT_RE = re.compile(r"中标|经营数据|框架协议|合作协议|中标公告")


def _asserts_negative(c: dict) -> bool:
    """断言隐含「指标将处于低位/下跌」：
    下行谓词（<, <=）判成立，或上行谓词（>, >=）判不成立，且阈值不高（≤2%）。"""
    down_pred = c["op"] in ("<", "<=")
    claims_below = c["judge"] if down_pred else (not c["judge"])
    return bool(claims_below) and c["thr"] <= 0.02


def _asserts_insiginificant(c: dict) -> bool:
    """pvalue 断言隐含「不显著」立场：谓词描述显著但判不成立，或反之。"""
    op, thr = c["op"], c["thr"]
    pred_sig = (op in ("<", "<=") and thr <= 0.05) or (op in (">", ">=") and thr >= 0.05)
    return (not c["judge"]) if pred_sig else bool(c["judge"])


def _residual_bias_adj(claims: list[dict], event: dict, label: dict) -> tuple[float, dict]:
    """B3/B4/B5 残留偏差修正项。返回 (额外扣分 ∈ [-0.15, 0], 诊断明细)。"""
    adj = 0.0
    diag: dict = {}

    car_t1 = label.get("car_t1")
    ret_t1 = label.get("ret_t1")
    t1_vals = [abs(v) for v in (car_t1, ret_t1) if isinstance(v, (int, float))]
    extreme_t0 = bool(t1_vals) and max(t1_vals) > 0.05

    # 错误且非平凡的断言集合（避免对送分断言重复扣分）
    def _wrong_nontrivial(c: dict) -> bool:
        return settle_claim(c, label) is False and not is_trivial_claim(c, label)

    # B3 极端事件显著性：T0 反应极端时错误主张「不显著」
    if extreme_t0:
        n = sum(
            1 for c in claims
            if "pvalue" in c["metric"] and _asserts_insiginificant(c) and _wrong_nontrivial(c)
        )
        if n:
            diag["b3_wrong_insiginificant"] = n
            adj -= 0.05 * n

    # B4 car/ret 分化：基准大跌时错误的 ret 下行断言（超跌反弹被忽略）
    bm_vals = [v for k, v in label.items()
               if k.startswith("bm_ret_t") and isinstance(v, (int, float))]
    if bm_vals and min(bm_vals) <= -0.02:
        n = sum(
            1 for c in claims
            if metric_family(c["metric"]) == "ret" and _asserts_negative(c) and _wrong_nontrivial(c)
        )
        if n:
            diag["b4_ret_down_pen"] = n
            adj -= 0.05 * n

    # B5 T0 噪音事件：中标/经营数据类事件 T0 为负时，错误的 car/ret 下行断言
    ev_text = " ".join(
        (str(event.get(k) or "")[:300] if k == "body" else str(event.get(k) or ""))
        for k in ("event_type_l2", "event_type", "title", "body")
    )
    if _T0_NOISE_EVENT_RE.search(ev_text) and isinstance(car_t1, (int, float)) and car_t1 < 0:
        n = sum(
            1 for c in claims
            if metric_family(c["metric"]) in ("car", "ret") and _asserts_negative(c) and _wrong_nontrivial(c)
        )
        if n:
            diag["b5_t0_noise_pen"] = n
            adj -= 0.04 * n

    return max(adj, -0.15), diag


# ============ v6.1 覆盖度修正（EXP-0 诊断 → B7 / T3） ============

# B7：弱指标先验表（环境变量 PAPV_METRIC_PRIOR 指向 gen_metric_prior.py 输出的 JSON）。
# 表内 acc < _B7_WEAK_ACC 的指标视为「弱指标」：其断言的正确性得分按 ×_B7_DISCOUNT 打折，
# 抑制向硬币水平指标堆断言。表缺失/加载失败时静默跳过（向后兼容）。
_B7_WEAK_ACC = 0.55
_B7_DISCOUNT = 0.7
_METRIC_PRIOR: dict[str, dict] = {}


def _load_metric_prior() -> dict[str, dict]:
    import json
    import os
    global _METRIC_PRIOR
    if _METRIC_PRIOR:
        return _METRIC_PRIOR
    path = os.getenv("PAPV_METRIC_PRIOR", "")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _METRIC_PRIOR = data.get("metrics") or {}
    except Exception:
        _METRIC_PRIOR = {}
    return _METRIC_PRIOR


def _b7_weak_discount(claims: list[dict], label: dict) -> tuple[float, dict]:
    """B7 弱指标打折。返回 (R2 乘数 ∈ (0,1], 诊断)。"""
    prior = _load_metric_prior()
    if not prior:
        return 1.0, {}
    weak = {m for m, d in prior.items()
            if isinstance(d, dict) and d.get("acc", 1.0) < _B7_WEAK_ACC}
    if not weak:
        return 1.0, {}
    # 可结算断言中弱指标占比 → 按占比线性打折（全弱 ×0.7，无弱 ×1.0）
    settleable = [c for c in claims if settle_claim(c, label) is not None]
    if not settleable:
        return 1.0, {}
    n_weak = sum(1 for c in settleable if c["metric"] in weak)
    frac = n_weak / len(settleable)
    mult = 1.0 - (1.0 - _B7_DISCOUNT) * frac
    return mult, {"b7_weak_frac": round(frac, 3), "b7_r2_mult": round(mult, 3)}


# T3：新增覆盖加分——断言引入「此前未出现的族/horizon」时给额外奖励，
# 对冲 B7 的「只挑软柿子」副作用，同时抑制同族堆叠。
_T3_NEW_COVER_BONUS = 0.06


def _t3_coverage_bonus(claims: list[dict]) -> tuple[float, dict]:
    """T3 新增覆盖加分。返回 (加分 ∈ [0, 0.12], 诊断)。"""
    seen_fam: set[str] = set()
    seen_hor: set[str] = set()
    new_fam = new_hor = 0
    for c in claims:
        fam = metric_family(c["metric"])
        if fam not in seen_fam:
            seen_fam.add(fam)
            if fam != "other":
                new_fam += 1
        if "_t" in c["metric"]:
            h = "t" + c["metric"].split("_t")[-1].split("_")[0]
            if h not in seen_hor:
                seen_hor.add(h)
                new_hor += 1
    bonus = _T3_NEW_COVER_BONUS * (
        min(new_fam - 1, 2) if new_fam > 1 else 0
    ) + _T3_NEW_COVER_BONUS * min(max(new_hor - 2, 0), 2)
    diag = {"t3_new_families": new_fam, "t3_new_horizons": new_hor}
    return bonus, diag


def compute_papv_reward(completion: str, event: dict, label: dict) -> dict:
    """主入口：返回 {reward, detail}。event 仅用于日志，结算只依赖 label。"""
    detail: dict = {}

    # ---- 解析断言 ----
    claims = parse_claims(completion)
    detail["n_claims"] = len(claims)

    # R0 格式：数量 ∈ [3,6]（平滑：差一条扣一档）+ 四段齐全 + 指标族集中惩罚
    n = len(claims)
    r0_n = 1.0 if 3 <= n <= 6 else max(0.0, 1.0 - 0.25 * abs(n - 3) if n < 3 else 0.75)
    secs = sum(_has_section(completion, k) for k in SECTION_HEADERS)
    R0 = 0.6 * r0_n + 0.4 * (secs / 4.0)
    # 指标族集中惩罚：若全部断言集中在单一指标族（如全 car），视为低信息模板 → 格式打折
    _fam = {metric_family(c["metric"]) for c in claims}
    if n >= 3 and len(_fam) < 2:
        R0 *= 0.5
    detail["sections"] = secs

    if n == 0:
        return {"reward": -0.20, "detail": {**detail, "R": None}}

    # ---- 结算（drop_trivial：平凡可判断言不计分，杜绝「写大阈值送分」激励） ----
    st = settle_all(claims, label, drop_trivial=True)
    detail.update({k: v for k, v in st.items() if k != "p_corrects"})

    # R1 可验证性
    R1 = st["settleable"] / n

    # R2 判断准确性（核心）
    R2: Optional[float] = st["accuracy"]  # None 时不可结算

    # R3 校准：1 - 2·mean((p̂ - 1)²) ∈ [-1, 1]，p̂ = 指向真值的预测概率
    if st["p_corrects"]:
        brier = sum((p - 1.0) ** 2 for p in st["p_corrects"]) / len(st["p_corrects"])
        R3 = 1.0 - 2.0 * brier
    else:
        R3 = None  # 全部缺置信度 → 按 0.5 中性处理
        if st["settleable"]:
            R3 = 0.0

    # R4 逻辑链：【2】存在且长度 ≥ 40 字
    m = re.search(r"【\s*2[.\s]*逻辑链\s*】(.*?)(?=【|$)", completion, re.DOTALL)
    chain = m.group(1).strip() if m else ""
    R4 = 1.0 if len(chain) >= 40 else (0.5 if len(chain) > 0 else 0.0)

    # R5 多样性：≥3 个 horizon、≥3 个指标族（防止模板化坍缩；提高门槛）
    horizons = {c["metric"] for c in claims if "_t" in c["metric"]}
    families = {metric_family(c["metric"]) for c in claims}
    R5 = 0.5 * min(1.0, st["n_horizons"] / 3.0) + 0.5 * min(1.0, len(families) / 3.0)
    detail["n_horizons"] = st["n_horizons"]
    detail["n_families"] = len(families)

    # ---- 加权 ----
    W = {"R0": 0.15, "R1": 0.12, "R2": 0.38, "R3": 0.20, "R4": 0.05, "R5": 0.10}
    parts = {"R0": R0, "R1": R1, "R2": R2, "R3": R3, "R4": R4, "R5": R5}

    # B7 弱指标打折：R2 按可结算断言中弱指标占比线性打折
    if R2 is not None:
        b7_mult, b7_diag = _b7_weak_discount(claims, label)
        if b7_mult < 1.0:
            R2 *= b7_mult
            parts["R2"] = R2
            detail.update(b7_diag)

    total, wsum = 0.0, 0.0
    for k, v in parts.items():
        if v is not None:
            total += W[k] * v
            wsum += W[k]
    reward = total / wsum if wsum > 0 else -0.20

    # T3 新增覆盖加分（对冲 B7「只挑软柿子」；上限 +0.12）
    t3_bonus, t3_diag = _t3_coverage_bonus(claims)
    if t3_bonus > 0:
        reward = min(1.0, reward + t3_bonus)
        detail["t3_bonus"] = round(t3_bonus, 3)
    detail.update(t3_diag)

    # 不可结算占多数 → 轻罚（防止靠「编造不可结算断言」逃避校验）
    if st["settleable"] == 0:
        reward = min(reward, 0.0)

    # ---- v6.1 残留偏差修正（B3/B4/B5）----
    bias_adj, bias_diag = _residual_bias_adj(claims, event, label)
    if bias_adj:
        reward = max(-0.20, reward + bias_adj)
        detail.update(bias_diag)
        detail["bias_adj"] = round(bias_adj, 3)

    detail["R"] = {k: (round(v, 3) if v is not None else None) for k, v in parts.items()}
    return {"reward": float(reward), "detail": detail}

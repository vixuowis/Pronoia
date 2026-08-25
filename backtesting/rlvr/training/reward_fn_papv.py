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
"""
from __future__ import annotations

import re
from typing import Optional

import sys
from pathlib import Path
_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from papv_claims import parse_claims, settle_all, metric_family  # noqa: E402

SECTION_HEADERS = {
    "R0": r"【\s*0[.\s]*断言规划\s*】",
    "R1a": r"【\s*1[.\s]*断言列表\s*】",
    "R2a": r"【\s*2[.\s]*逻辑链\s*】",
    "R3a": r"【\s*3[.\s]*反方与风险\s*】",
}


def _has_section(text: str, key: str) -> bool:
    return re.search(SECTION_HEADERS[key], text) is not None


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
    total, wsum = 0.0, 0.0
    for k, v in parts.items():
        if v is not None:
            total += W[k] * v
            wsum += W[k]
    reward = total / wsum if wsum > 0 else -0.20

    # 不可结算占多数 → 轻罚（防止靠「编造不可结算断言」逃避校验）
    if st["settleable"] == 0:
        reward = min(reward, 0.0)

    detail["R"] = {k: (round(v, 3) if v is not None else None) for k, v in parts.items()}
    return {"reward": float(reward), "detail": detail}

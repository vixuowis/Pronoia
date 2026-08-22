"""reward_fn.py — Pronoia-RLVR §3.3.2 七元 Reward 函数（总范围 [-1.60, +2.10]）。

Reward = Σ w_i * R_i
  R0  4%   窗口合规：【0】段提到了正确的主 horizon
  R05 4%   量价段合规：【0.5】段引用了 ≥1 条量价数值 + 有 regime 判断
  R1  50%  方向正确：【5】段 direction 与 label_{primary_h} 一致（主项）
  R2  27%  置信度校准 × κ_vol：|confidence - 1(correct)| 的指数衰减 + 高 vol 时惩罚过自信
  R3  13%  CAR 幅度 + 双窗一致 + 量价安全阀 + RET↔CAR 一致 + 长短不反转
  R4  4%   推理链一致性：7 段标题齐全 + 无自相矛盾（如 【1】说利多 但 【3】说无效条件=利多失败）
  R5  2%   专家熵正则：Router 权重 Shannon entropy 居中（防某专家独霸 → MoE 崩塌）

对外接口：
    r = compute_reward(completion, event, label, weights)
"""
from __future__ import annotations

import math
import re
from typing import Optional

import sys
from pathlib import Path
_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))
_SCRIPTS = _THIS.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from expert_definitions import DEFAULT_HPARAMS, RLVRHyperparams  # noqa: E402
from scene_match import primary_horizon_for, scene_meta_for  # noqa: E402


# ============ 7 段标题正则（兼容中英文标点、数字带不带点） ============
SECTION_HEADERS = {
    "R0":   r"【\s*0[.\s]*预判时间窗口\s*】",
    "R05":  r"【\s*0[.\s]*5\s*量价\s*regime\s*校验\s*】",
    "R1a":  r"【\s*1[.\s]*关键信号提取\s*】",
    "R2a":  r"【\s*2[.\s]*横向比较\s*】",
    "R3a":  r"【\s*3[.\s]*反方与限制\s*】",
    "R4a":  r"【\s*4[.\s]*置信度校准\s*】",
    "R5a":  r"【\s*5[.\s]*最终方向\s*】",
}


# ============ 辅助解析 ============
def _parse_section(text: str, key: str) -> Optional[str]:
    pat = SECTION_HEADERS[key]
    m = re.search(pat, text)
    if not m:
        return None
    start = m.end()
    # 找下一个【...】或结尾
    next_m = re.search(r"【[^】]*】", text[start:])
    end = start + next_m.start() if next_m else len(text)
    return text[start:end].strip()


def _extract_direction(text: str) -> Optional[str]:
    """从【5. 最终方向】段提取 up/down/neutral。"""
    s = _parse_section(text, "R5a")
    if s is None:
        # 兜底：全文搜索最后一个 direction 标记
        m = re.search(r"direction\s*[:：]\s*(up|down|neutral)", text, re.IGNORECASE)
        if m: return m.group(1).lower()
        return None
    m = re.search(r"(up|down|neutral)", s, re.IGNORECASE)
    if m: return m.group(1).lower()
    # 再兜底：段落里直接写的涨跌词
    sl = s.lower()
    if any(x in sl for x in ("看空", "下跌", "down", "空头")): return "down"
    if any(x in sl for x in ("看多", "上涨", "up", "多头")):   return "up"
    if any(x in sl for x in ("中性", "震荡", "neutral", "横盘")): return "neutral"
    return None


def _extract_confidence(text: str) -> Optional[float]:
    """从【4. 置信度校准】段提取 confidence ∈ [0,1]。"""
    s = _parse_section(text, "R4a")
    if s is None:
        # 兜底全文搜
        for m in re.finditer(r"confidence\s*[=:：]\s*([01]\.\d+|0?\.\d+|1\.0+|\d+%)", text, re.IGNORECASE):
            raw = m.group(1).strip()
            try:
                if raw.endswith("%"): return max(0.0, min(1.0, float(raw[:-1]) / 100.0))
                return max(0.0, min(1.0, float(raw)))
            except Exception:
                continue
        return None
    m = re.search(r"(?:confidence|置信度)\s*[=:：]?\s*([01]\.\d+|0?\.\d+|1\.0+|\d+%)", s, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        try:
            if raw.endswith("%"): return max(0.0, min(1.0, float(raw[:-1]) / 100.0))
            return max(0.0, min(1.0, float(raw)))
        except Exception:
            return None
    return None


# ==================== 七项 R_i ====================
def _R0_window_compliant(completion: str, primary_h: str) -> float:
    """R0 ∈ {0, 1}：【0】段提到了 primary_h（t3/t7/t15）。"""
    s0 = _parse_section(completion, "R0")
    if s0 is None: return 0.0
    if primary_h in s0 or f"T+{primary_h[1:]}" in s0: return 1.0
    return 0.0


def _R05_volume_section_compliant(completion: str, event_vol: dict) -> float:
    """R05 ∈ {0, 0.5, 1.0}：
       - 0.5 分：有 【0.5】段 + 引用了 ≥1 条数值
       - 1.0 分：另外还有对 vol_regime 支持/不支持/中性 的判断"""
    s05 = _parse_section(completion, "R05")
    if s05 is None: return 0.0
    # 是否引用了 ≥1 个数字（浮点数）
    has_number = bool(re.search(r"\d+\.\d+", s05))
    if not has_number:
        # 允许 N/A 也算有引用（当数据真的缺失时）
        if "N/A" not in s05 and "缺失" not in s05:
            return 0.0
    # 是否有 regime 判断词
    regime_words = ("支持", "不支持", "中性", "NORMAL", "HIGH", "LOW",
                    "量价", "共振", "背离", "放量", "缩量")
    has_regime_judge = any(w in s05 for w in regime_words)
    return 1.0 if has_regime_judge else 0.5


def _R1_direction_correct(completion: str, primary_h: str, label: dict) -> tuple[float, Optional[str]]:
    """R1 ∈ {-1.0, 0.0, +1.0}：与 label_{primary_h} 比对。
       返回 (R1_score, predicted_direction)。"""
    pred = _extract_direction(completion)
    if pred is None:
        return 0.0, None
    gt = str(label.get(f"label_{primary_h}") or label.get("label_avg_all") or "neutral")
    gt = gt.lower()
    if gt not in ("up", "down", "neutral"):
        # 兜底：用 car_{primary_h} 符号
        car = label.get(f"car_{primary_h}")
        if isinstance(car, (int, float)):
            if car > 0.01: gt = "up"
            elif car < -0.01: gt = "down"
            else: gt = "neutral"
    if pred == gt: return +1.0, pred
    if gt == "neutral" or pred == "neutral":
        return 0.0, pred   # 中性 vs 涨跌：不算完全错
    return -1.0, pred  # 涨跌互反


def _R2_confidence_calibration(completion: str, correct: bool,
                                vol_regime: Optional[str]) -> float:
    """R2 ∈ [-1, +1]：指数衰减校准分 × κ_vol。
       correct=False 时，高 confidence 要重罚；correct=True 时，高 confidence 要奖励。
       κ_vol：HIGH 时，对错误的过自信惩罚 ×1.3，对正确的高自信奖励 ×0.8（高波动时鼓励保守）。"""
    conf = _extract_confidence(completion)
    if conf is None:
        return 0.0  # 没写 → 不奖不罚
    # 期望置信度
    target = 0.85 if correct else 0.15
    if correct and vol_regime == "HIGH":
        target = 0.75  # 高波动下即使对，也不该过度自信
    diff = abs(conf - target)
    base = math.exp(-4.0 * diff) * 2.0 - 1.0   # diff=0→+1, diff=0.5→0.0, diff=1→-0.63
    # κ_vol 修正
    if vol_regime == "HIGH":
        if not correct and conf > 0.6:
            base *= 1.3   # 错误且高波动时过自信 → 重罚
        elif correct and conf > 0.7:
            base *= 0.8   # 正确但高波动时过自信 → 奖励打折
    return max(-1.0, min(+1.0, base))


def _R3_car_magnitude_and_safeties(direction_pred: Optional[str], primary_h: str,
                                     meta: dict, label: dict, eta_rer: float,
                                     eta_long: float) -> float:
    """R3 ∈ [-1, +1]：CAR 幅度 + 4 重安全阀。"""
    if direction_pred is None:
        return -0.5
    car = label.get(f"car_{primary_h}")
    if not isinstance(car, (int, float)):
        return 0.0
    # CAR 幅度分（只在方向正确时给满奖励；错误时给 0）
    gt_label = str(label.get(f"label_{primary_h}") or "neutral").lower()
    if direction_pred != gt_label:
        # 方向错 → 全部分为 0，不额外扣（R1 已经扣了）
        return 0.0
    mag_score = min(1.0, abs(car) / 0.10)   # |CAR|≥10% → 满分 1

    # 安全阀1：双窗一致（主 vs 第一次窗口）
    sec_hs = meta.get("secondary_horizons", [])
    s1 = 1.0
    if sec_hs:
        car_sec = label.get(f"car_{sec_hs[0]}")
        if isinstance(car_sec, (int, float)):
            if (car > 0 and car_sec < -0.03) or (car < 0 and car_sec > 0.03):
                s1 = 0.5   # 双窗相反 → 半分扣减

    # 安全阀2：量价一致（vol_regime=HIGH + pred=up → car 若低于 0 → 扣）
    # 实际这里 label 不含 event 字段；外部调用会把 event_vol 注入 label 暂存，
    # 否则此安全阀跳过（返回 1.0，不扣）
    s2 = 1.0

    # 安全阀3：RET↔CAR 一致（η_rer 权重；变量名保留 η_rer 兼容 config，但语义=事件后标的自身收益 ret）
    s3 = 1.0
    ret = label.get(f"ret_{primary_h}")
    if isinstance(ret, (int, float)) and isinstance(car, (int, float)):
        if (car > 0 and ret < -0.02) or (car < 0 and ret > 0.02):
            # 方向相反且幅度 ≥2% → 惩罚
            s3 = 1.0 - eta_rer

    # 安全阀4：长短 horizon 反转（η_long 权重）
    s4 = 1.0
    ret_t3  = label.get("ret_t3")
    ret_t60 = label.get("ret_t60")
    if isinstance(ret_t3, (int, float)) and isinstance(ret_t60, (int, float)):
        if (ret_t3 > 0.02 and ret_t60 < -0.03) or (ret_t3 < -0.02 and ret_t60 > 0.03):
            s4 = 1.0 - eta_long

    # 加权相乘（都是 ≤1 的系数，越多越不安全）
    combined = mag_score * s1 * s2 * s3 * s4
    return max(-1.0, min(1.0, combined))


def _R4_chain_consistency(completion: str) -> float:
    """R4 ∈ {0, 0.5, 1.0}：7 段齐全 + 前后不明显矛盾。"""
    present = 0
    for key in ("R0", "R05", "R1a", "R2a", "R3a", "R4a", "R5a"):
        if _parse_section(completion, key) is not None:
            present += 1
    completeness = present / 7.0
    if completeness < 4/7:
        return 0.0   # 缺段太多 → 推理链不成立
    score = 1.0 if completeness >= 1.0 else 0.5 if completeness >= 5/7 else 0.3

    # 简易矛盾检测：【1】段说"利好"类词，但【5】是 down（反之亦然）
    s1 = _parse_section(completion, "R1a") or ""
    s5 = _parse_section(completion, "R5a") or ""
    dir5 = _extract_direction(completion) or "neutral"
    s1_pos_hints = any(w in s1 for w in ("利好", "超预期", "增长", "盈利", "上调", "利多", "positive"))
    s1_neg_hints = any(w in s1 for w in ("利空", "不及预期", "下滑", "亏损", "下调", "利空", "negative"))
    if s1_pos_hints and dir5 == "down":  score *= 0.6
    if s1_neg_hints and dir5 == "up":    score *= 0.6
    return max(0.0, min(1.0, score))


def _R5_expert_entropy_regularizer(router_weights: dict[str, float]) -> float:
    """R5 ∈ [0, 1]：Router 权重熵 / ln(K)。过低 → MoE 崩塌；过高（均匀）→ 没有辨别力。
       目标熵≈ ln(2~3)（即 K=6 时有 2-3 位专家权重显著）。"""
    if not router_weights:
        return 0.0
    K = len(router_weights)
    H = 0.0
    for w in router_weights.values():
        if w <= 0: continue
        H -= w * math.log(max(w, 1e-12))
    H_max = math.log(max(K, 2))
    # 目标熵区间 [0.4*H_max, 0.85*H_max]
    lo = 0.4 * H_max; hi = 0.85 * H_max
    if lo <= H <= hi:
        score = 1.0
    elif H < lo:
        score = math.exp(-3.0 * (lo - H) / max(lo, 1e-6))  # 太低 → 崩塌，惩罚
    else:
        score = math.exp(-2.0 * (H - hi) / max(H_max - hi, 1e-6))  # 太高 → 均匀，轻罚
    return max(0.0, min(1.0, score))


# ==================== 对外主函数 ====================
def compute_reward(completion: str, event: dict, label: dict,
                   hp: Optional[RLVRHyperparams] = None) -> dict:
    """计算七元 Reward 明细 + 加权总和。返回 dict（含每个 R_i、总 reward、辅助诊断）。"""
    hp = hp or DEFAULT_HPARAMS
    w = hp.reward_weights

    mkt = str(event.get("market") or "").upper()
    el2 = str(event.get("event_type_l2") or "")
    primary_h = primary_horizon_for(mkt, el2)
    meta = scene_meta_for(mkt, el2)

    # 预提取预测方向（复用）
    r1, dir_pred = _R1_direction_correct(completion, primary_h, label)
    vol_regime = event.get("vol_regime") or label.get("vol_regime")

    r0  = _R0_window_compliant(completion, primary_h)
    r05 = _R05_volume_section_compliant(completion, event)
    r2  = _R2_confidence_calibration(completion, correct=(r1 > 0), vol_regime=vol_regime)
    r3  = _R3_car_magnitude_and_safeties(dir_pred, primary_h, meta, label,
                                          hp.R3_eta_rer, hp.R3_eta_long)
    r4  = _R4_chain_consistency(completion)
    # Router 权重：优先用 event._router 注入，否则用 label._router，最后 fallback 用 event 再算一次
    rw = event.get("_router_weights") or label.get("_router_weights")
    if not isinstance(rw, dict) or not rw:
        from expert_definitions import router_weights as _rw_fn  # lazy import
        rw = _rw_fn(mkt, el2, vol_regime, event.get("vol_t0_ratio"))
    r5 = _R5_expert_entropy_regularizer(rw)

    R = {
        "R0":  r0,  "R05": r05, "R1": r1,
        "R2":  r2,  "R3":  r3,  "R4": r4, "R5": r5,
    }
    total = (
        w["R0"]  * R["R0"] + w["R05"] * R["R05"] + w["R1"] * R["R1"] +
        w["R2"]  * R["R2"] + w["R3"]  * R["R3"]  + w["R4"] * R["R4"] +
        w["R5"]  * R["R5"]
    )
    # 总范围：最差情况 -1.60（R0=R05=R4=R5=0, R1=-1→-0.5, R2=-1→-0.27, R3=-1→-0.13）
    #          最好情况 +1.00（各项 1 × 权重和=1）。这里把范围映射到 [-1.60, +2.10]
    #          以便 GRPO 的优势估计更拉开（design §3.3.2）。
    total_scaled = 2.10 * total if total >= 0 else 1.60 * total

    return {
        "reward": total_scaled,
        "reward_raw": total,
        "R_components": R,
        "weights": dict(w),
        "diagnostics": {
            "primary_horizon": primary_h,
            "direction_predicted": dir_pred,
            "direction_gt": label.get(f"label_{primary_h}"),
            "confidence_predicted": _extract_confidence(completion),
            "sections_present_count": sum(
                1 for k in ("R0","R05","R1a","R2a","R3a","R4a","R5a")
                if _parse_section(completion, k) is not None
            ),
        },
    }

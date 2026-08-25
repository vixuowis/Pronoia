"""papv_claims.py — Pronoia-PAPV 统一断言表征 + 事后结算器。

PAPV 范式（预测-断言-事后验证）：
  · 指标面板（任意指标）放在【输入】里，只给定义不给数值；
  · 模型自主提出 K 条可验证断言并判断真假；
  · T+k 用 labels.jsonl 的客观数值结算，度量"断言提得准不准"。

统一断言语法（一切结构类断言均可分解为单指标断言，保持简洁）：
  CLAIM-n: <指标> <op> <阈值> @<验证时点> | 判断: TRUE|FALSE | 置信度: 0.xx | 依据: ...

三条件（PAPV 提案 §二）：
  1. 单一事实答案（二值化）  → op + 阈值
  2. 明确验证时点            → @tX（隐含在指标名的 horizon 里）
  3. 客观结算源              → METRIC_PANEL 内的指标（labels 自动结算）
"""
from __future__ import annotations

import re
from typing import Optional

# ============ 指标面板（模型可见的定义；结算源 = labels.jsonl 客观数值） ============
_HORIZONS = (1, 3, 5, 7, 15, 30, 60)

METRIC_PANEL: dict[str, str] = {}
for _h in _HORIZONS:
    METRIC_PANEL[f"car_t{_h}"] = (
        f"事件后 {_h} 个交易日累计超额收益（市场模型 AR 加总，含 T0 当日反应；小数，如 0.02=+2%）")
    METRIC_PANEL[f"ret_t{_h}"] = (
        f"事件后 {_h} 个交易日标的自身累计收益（绝对口径，不含基准；小数）")
    METRIC_PANEL[f"bm_ret_t{_h}"] = f"同期基准累计收益（小数）"
for _h in (3, 7, 15, 30, 60):
    METRIC_PANEL[f"car_t{_h}_pvalue"] = (
        f"car_t{_h} 的市场模型显著性 p 值（<0.05 视为统计显著，取值 [0,1]）")
METRIC_PANEL["car_avg_short"] = "短窗口平均超额（t3/t5/t7 均值，小数）"
METRIC_PANEL["car_avg_mid"] = "中窗口平均超额（t7/t15 均值，小数）"
METRIC_PANEL["car_avg_long"] = "长窗口平均超额（t30/t60 均值，小数）"
METRIC_PANEL["car_avg_all"] = "全窗口平均超额（t3~t60 均值，小数）"

# 指标族（多样性奖励用）
def metric_family(m: str) -> str:
    if "pvalue" in m: return "significance"
    if m.startswith("car_avg"): return "avg_family"
    if m.startswith("car"): return "car"
    if m.startswith("ret"): return "ret"
    if m.startswith("bm"): return "benchmark"
    return "other"


# ============ CLAIM 行解析 ============
# CLAIM-1: car_t7 > 0 @t7 | 判断: TRUE | 置信度: 0.72 | 依据: xxx
_CLAIM_RE = re.compile(
    r"CLAIM[-–—\s]*(?P<idx>\d+)\s*[:：]\s*"
    r"(?P<metric>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<op>>=|<=|>|<|≥|≤|大于|小于|不低于|高于|超过|低于)\s*"
    r"(?P<thr>[+-]?\d+(?:\.\d+)?%?)\s*"
    r"(?:@\s*(?P<horizon>t\d+|T\+\d+))?\s*"
    r"[|｜]\s*(?:判断|verdict)\s*[:：]\s*(?P<judge>true|false|真|假|对|错|成立|不成立)",
    re.IGNORECASE,
)
_CONF_RE = re.compile(
    r"(?:置信度|confidence)\s*[:：]?\s*(0?\.\d+|1(?:\.0+)?|\d+%)", re.IGNORECASE)

_OP_MAP = {
    ">": ">", "<": "<", "≥": ">=", "≤": "<=",
    "大于": ">", "超过": ">", "高于": ">", "不低于": ">=",
    "小于": "<", "低于": "<",
}

# 阈值单位守卫：裸数字 |thr| > 0.15 视为「百分数误写」（2.5 意为 2.5%）→ 归一为小数。
# 依据：v5 OOS 复盘发现 42.6% 断言阈值数量级错位（5.0/2.5/2.0/…），且合法小数阈值
# 实际最大仅 0.10（=10%），两者在 0.15 处天然分界。带 % 符号的阈值不受影响。
_THR_UNIT_CUT = 0.15


def parse_claims(text: str) -> list[dict]:
    """从 completion 解析全部 CLAIM 行 → [{metric, op, thr, judge, conf}]。"""
    claims = []
    for m in _CLAIM_RE.finditer(text):
        # 该 CLAIM 所在行内找置信度（就近匹配）
        line_end = text.find("\n", m.end())
        tail = text[m.end():line_end if line_end != -1 else len(text)]
        cm = _CONF_RE.search(tail) or _CONF_RE.search(m.group(0))
        conf = None
        if cm:
            raw = cm.group(1)
            conf = float(raw[:-1]) / 100.0 if raw.endswith("%") else float(raw)
            conf = max(0.0, min(1.0, conf))
        thr_raw = m.group("thr")
        if thr_raw.endswith("%"):
            thr = float(thr_raw[:-1]) / 100.0
        else:
            thr = float(thr_raw)
            if abs(thr) > _THR_UNIT_CUT:
                thr /= 100.0   # 裸数字百分数误写 → 按本意归一为小数口径
        judge_raw = m.group("judge").lower()
        judge = judge_raw in ("true", "真", "对", "成立")
        claims.append({
            "metric": m.group("metric"),
            "op": _OP_MAP.get(m.group("op"), m.group("op")),
            "thr": thr,
            "thr_raw": thr_raw,      # 原始阈值书写（诊断单位问题用）
            "judge": judge,          # True=断言成立 / False=断言不成立
            "conf": conf,
        })
    return claims


# ============ 事后结算 ============
def settle_claim_truth(claim: dict, label: dict) -> Optional[bool]:
    """断言客观真值：断言描述的命题是否成立。

    返回：
      True/False — 命题成立 / 不成立
      None       — 不可结算（指标不在面板 / label 缺数值）
    """
    metric = claim["metric"]
    if metric not in METRIC_PANEL:
        return None
    val = label.get(metric)
    if val is None or not isinstance(val, (int, float)):
        return None
    op, thr = claim["op"], claim["thr"]
    if op == ">":   return val > thr
    elif op == "<": return val < thr
    elif op == ">=": return val >= thr
    elif op == "<=": return val <= thr
    return None


def settle_claim(claim: dict, label: dict) -> Optional[bool]:
    """模型判断是否正确（judge vs 客观真值）。"""
    truth = settle_claim_truth(claim, label)
    if truth is None:
        return None
    return truth == claim["judge"]


def is_trivial_claim(claim: dict, label: dict) -> bool:
    """平凡可判：|实际值| 远小于 |阈值|（数量级差使答案预先确定，如 car ≥ -150%）。

    v5 复盘：单位错位产生的「送分题」99.7% 满足 |实际值| < |阈值|/2。
    仅适用于收益率量纲指标（car/ret/bm/avg 族）；pvalue 族数值天然微小
    （p<0.05 且实际 0.019 是高信息断言），不做平凡判定。
    """
    if metric_family(claim["metric"]) == "significance":
        return False
    val = label.get(claim["metric"])
    thr = abs(claim.get("thr") or 0.0)
    if not isinstance(val, (int, float)) or thr == 0:
        return False
    return abs(val) * 2 < thr


def settle_all(claims: list[dict], label: dict, drop_trivial: bool = False) -> dict:
    """结算一组断言 → 汇总统计（reward 与评估共用）。

    drop_trivial=True 时平凡可判断言不计入 settleable（reward 用：杜绝送分激励）；
    评估侧默认 False 以如实反映模型产出。

    p_corrects：每条可结算断言的「指向真值的预测概率」——
      p_claim = conf if judge==TRUE else 1-conf（模型对断言成立的主观概率）
      p_corrects = p_claim if truth else 1-p_claim（Brier 用，越接近 1 越准）
    """
    settleable, correct, n_trivial = 0, 0, 0
    p_corrects: list[float] = []
    for c in claims:
        truth = settle_claim_truth(c, label)
        if truth is None:
            continue
        if drop_trivial and is_trivial_claim(c, label):
            n_trivial += 1
            continue
        settleable += 1
        correct += int(truth == c["judge"])
        p = c["conf"] if c["conf"] is not None else 0.5
        p_claim = p if c["judge"] else (1.0 - p)
        p_corrects.append(p_claim if truth else (1.0 - p_claim))
    horizons = {c["metric"].split("_t")[-1] for c in claims if "_t" in c["metric"]}
    families = {metric_family(c["metric"]) for c in claims}
    return {
        "n_claims": len(claims),
        "settleable": settleable,
        "correct": correct,
        "accuracy": (correct / settleable) if settleable else None,
        "p_corrects": p_corrects,
        "n_trivial": n_trivial,
        "n_horizons": len({h for h in horizons if h.isdigit()}),
        "n_families": len(families),
    }

"""prompt_template_papv.py — Pronoia-PAPV 输入拼装（预测-断言-事后验证）。

与旧范式（七段 CoT → direction+confidence）的区别：
  · 指标面板（任意指标）进【输入】——只给结算源定义，不给数值；
  · 输出 = 模型自主提出 K 条可验证断言（CLAIM）+ 真假判断 + 置信度 + 逻辑链；
  · 不再有固定的 direction 输出位，CAR/RET 只是可断言属性中的两类。

复用：render_research_context（前置研究上下文）、scene_match（MoE 专家路由提示）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))
_SCRIPTS = _THIS.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from papv_claims import METRIC_PANEL                                  # noqa: E402
from prompt_template import render_research_context, _fmt_pct          # noqa: E402
from scene_match import primary_horizon_for, expert_targets_for        # noqa: E402


def _soft_moe_prior_text(event: dict, research: dict | None) -> str | None:
    """软 MoE 阶段 0：Router 先验权重作为显式 prompt 条件注入单模型。

    开关：环境变量 PAPV_SOFT_MOE=1。返回 top-K 专家权重文本；失败返回 None。
    """
    if os.getenv("PAPV_SOFT_MOE", "0") != "1":
        return None
    try:
        from expert_definitions import router_weights
        vol = (research or {}).get("vol_features") or {}
        w = router_weights(
            str(event.get("market") or "?").upper(),
            str(event.get("event_type_l2") or event.get("event_type") or ""),
            vol_regime=vol.get("vol_regime"),
            vol_t0_ratio=vol.get("vol_t0_ratio"),
        )
        top = sorted(w.items(), key=lambda kv: -kv[1])[:3]
        top = [(k, v) for k, v in top if v >= 0.05]
        if not top:
            return None
        items = "，".join(f"{k}({v:.2f})" for k, v in top)
        return (f"软 MoE Router 先验（各专家激活权重，供判断时分工参考，"
                f"非结论）：{items}")
    except Exception:
        return None

SYSTEM_PROMPT_PAPV = """你是 Pronoia-PAPV 事件研究断言师（PAPV = 预测-断言-事后验证）。
面对事件与前置研究上下文，你的任务不是给出涨跌观点，而是：
提出 3~6 条「可事后验证的二值断言」并对每条断言给出你的真假判断与置信度。

断言三条件（缺一不可）：
1. 单一事实答案：指标 + 关系符 + 阈值，二值可判；
2. 明确验证时点：指标自带的 horizon（@tX）；
3. 客观结算源：只允许使用【可断言指标面板】中列出的指标。

CLAIM 行格式（必须逐字段严格遵守，一行一条）：
CLAIM-1: car_t7 > 0 @t7 | 判断: TRUE | 置信度: 0.72 | 依据: 量价背离与前5日漂移同向
（关系符支持 > < >= <=；阈值一律以小数书写，与输入数值同口径：2.5% 写作 0.025，禁止写裸百分数；
判断只写 TRUE 或 FALSE；置信度 ∈ [0,1]）

要求：
· 覆盖至少 2 个不同 horizon（如 t3 与 t15）和至少 2 类指标族（car/ret/基准/p值/均值系列）；
· 允许提出「断言不成立」的判断（FALSE 也是有效判断，质疑本身是能力）；
· 依据必须引用输入中的证据（量价数字、同类事件基率、动量等），不得伪造数值；
· 输出四段：【0. 断言规划】【1. 断言列表】【2. 逻辑链】【3. 反方与风险】；
· 紧凑表达：【0】≤2 句；【2】每条断言 1~2 句（总共 ≤8 句）；【3】≤3 句。全文不超过 500 字。
"""


def _panel_text() -> str:
    """指标面板（按族压缩：27 个指标 → 5 行，数值一律不给出）。"""
    hs = "/".join(str(h) for h in (1, 3, 5, 7, 15, 30, 60))
    hs2 = "/".join(str(h) for h in (3, 7, 15, 30, 60))
    lines = [
        "## 可断言指标面板（结算源定义；数值 T+k 由客观 K 线结算，现在未知；小数计，0.02=+2%）",
        f"- car_t{{{hs}}}：事件后 X 个交易日累计超额收益（市场模型 AR 加总，含 T0 当日反应）",
        f"- ret_t{{{hs}}}：事件后 X 个交易日标的自身累计收益（绝对口径，不含基准）",
        f"- bm_ret_t{{{hs}}}：同期基准累计收益",
        f"- car_t{{{hs2}}}_pvalue：对应 car 的显著性 p 值（<0.05 视为统计显著）",
        "- car_avg_short / car_avg_mid / car_avg_long / car_avg_all：短/中/长/全窗口平均超额",
        "（断言指标名必须逐字取自以上面板，如 car_t7、ret_t15、car_t3_pvalue、car_avg_all）",
    ]
    return "\n".join(lines)


def build_messages_for_papv(event: dict, research: dict | None = None) -> list[dict]:
    """PAPV prompt：事件 + 前置研究上下文 + 指标面板 + 任务指令。"""
    symbol = str(event.get("symbol") or "?")
    market = str(event.get("market") or "?").upper()
    etime = str(event.get("event_time") or event.get("event_date") or "?")[:10]
    title = str(event.get("title") or "")[:120]
    etype = str(event.get("event_type_l2") or event.get("event_type") or "未分类")
    body = str(event.get("event_text") or event.get("body") or "").strip()
    if len(body) > 900:
        body = body[:900] + "…（截断）"

    parts = ["## 事件元信息"]
    parts.append(f"- Market: {market}  |  Symbol: {symbol}  |  EventDate: {etime}")
    parts.append(f"- EventType L2: {etype}")
    parts.append(f"- 标题：{title}")
    parts.append("")
    parts.append("## 事件正文")
    parts.append(body if body else "（无正文，仅标题）")

    if research:
        ctx = render_research_context(research)
        if ctx:
            parts.append("")
            parts.append(ctx)

        # Team full 深度研究摘要（v4：多窗口推理链 + 依据原文；只给推理过程，
        # 不给结构化结论 horizons——断言须由模型独立提出并判断）
        rat = str(research.get("rationale") or "").strip()
        if rat:
            if len(rat) > 800:
                rat = rat[:800] + "…（截断）"
            parts.append("")
            parts.append("### 深度研究摘要（Team 前置推理链与证据，仅供参考；断言与判断须独立作出）")
            parts.append(rat)

    vol = (research or {}).get("vol_features") or {}
    if vol.get("vol_t0_ratio") is not None:
        parts.append("")
        parts.append("### 量价特征（T0 已知，事件当日）")
        parts.append(
            f"- vol_t0_ratio={vol.get('vol_t0_ratio'):.3f}（T0 量/前20日均量）；"
            f"vol_pre5_ratio={vol.get('vol_pre5_ratio'):.3f}（前5日均量/前20日均量）；"
            f"price_vol_diverge={vol.get('price_vol_diverge'):.2f}（正=量价共振）；"
            f"range_t0_normalized={vol.get('range_t0_normalized'):.2f}"
        )

    parts.append("")
    parts.append(_panel_text())

    try:
        ph = primary_horizon_for(event)
        experts = expert_targets_for(event)
        parts.append("")
        parts.append("## 提示")
        parts.append(
            f"- 场景主 horizon：t{ph}（本事件类型的典型反应窗口；断言不必局限于此，"
            f"但应覆盖它）；MoE 专家路由先验：{', '.join(experts)}。")
    except Exception:
        pass

    # 软 MoE 阶段 0：Router 先验权重注入（PAPV_SOFT_MOE=1 时启用）
    smoe = _soft_moe_prior_text(event, research)
    if smoe:
        parts.append(f"- {smoe}")

    parts.append("")
    parts.append(
        "## 任务\n提出 3~6 条可验证断言（覆盖 ≥2 个 horizon、≥2 个指标族），"
        "逐条给出 TRUE/FALSE 判断与置信度。输出四段："
        "【0. 断言规划】【1. 断言列表】【2. 逻辑链】【3. 反方与风险】。")

    return [
        {"role": "system", "content": SYSTEM_PROMPT_PAPV},
        {"role": "user", "content": "\n".join(parts)},
    ]

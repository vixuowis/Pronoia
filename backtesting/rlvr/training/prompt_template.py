"""prompt_template.py — Pronoia-RLVR §3.3.1 七段 CoT 推理链模板 + INPUT 块拼装。

7 段 CoT 结构（训练时监督生成，推理时强制遵守）：
  【0. 预判时间窗口】   → R0 合规：引用 scene_match 的主 horizon
  【0.5 量价 regime 校验】→ R05 合规：显式引用 4 维量价特征数值
  【1. 关键信号提取】   → Claim 级关键信息摘录（公告/数据核心内容）
  【2. 横向比较】       → 同类事件历史表现 / 行业同期 / 基准对比
  【3. 反方与限制】     → 看空理由 + 条件限制（何时判断失效）
  【4. 置信度校准】     → 输出 confidence ∈ [0,1]，引用波动率分位数 κ_vol
  【5. 最终方向】       → up/down/neutral + 融合来源说明（哪几位专家主导）

训练格式：对齐 trl 的 GRPOTrainer / SFTTrainer 期望的 "messages" 或 "prompt-completion"。
"""
from __future__ import annotations

import json
from typing import Optional

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from scene_match import primary_horizon_for, scene_meta_for, expert_targets_for  # noqa: E402
from expert_definitions import router_weights  # noqa: E402


SYSTEM_PROMPT_BASE = """你是 Pronoia 事件驱动交易研究员（RLVR v1 训练版）。
你必须以严格的七段思维链回答，最后必须给出：最终方向（up/down/neutral）+ 置信度 [0,1]。
禁止输出思维链以外的闲聊。若缺少量价数字或事件细节，必须在【0.5】或【3】中如实标注，不得伪造数值。
"""


def _fmt_f(v: Optional[float], digits: int = 3) -> str:
    if v is None: return "N/A（数据缺失，已降级为 NORMAL）"
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return "N/A"


def _fmt_pct(v, signed: bool = True) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "N/A"
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def render_research_context(rc: dict) -> str:
    """把 precompute_research_cache.py 的单条缓存渲染成紧凑的前置研究上下文文本。

    对应 Team Pipeline 前置部分（PLAN → FAN-OUT Experts）的离线预计算产出：
      market_analyst  → market_ctx / volume features
      基准对比        → benchmark_ctx
      event_scout    → 事件记录本身（title/event_text 已在事件正文段）
      deep_researcher→ evidence_items（证据图核心节点）
      predictor      → scenarios（三情景推演）
    全部 as-of T0（expanding window 防泄漏）。
    """
    lines = ["## 前置研究上下文（Tier 1 Experts 离线预计算，strict as-of T0）"]

    # ---- market_analyst：趋势/波动/位置 ----
    m = rc.get("market_ctx") or {}
    if m.get("ok"):
        parts = []
        for label_, key in (("5日动量", "mom_5d_pct"), ("20日动量", "mom_20d_pct")):
            v = m.get(key)
            if v is not None:
                parts.append(f"{label_} {_fmt_pct(v)}")
        if m.get("vol_20d_ann_pct") is not None:
            parts.append(f"20日年化波动 {m['vol_20d_ann_pct']:.1f}%")
        for w in (20, 60):
            v = m.get(f"pos_vs_ma{w}_pct")
            if v is not None:
                parts.append(f"vs MA{w} {_fmt_pct(v)}")
        if m.get("pos_52w_pct") is not None:
            parts.append(f"52周位置 {m['pos_52w_pct']:.0f}%")
        if m.get("drawdown_20d_pct") is not None:
            parts.append(f"距20日高点 {_fmt_pct(m['drawdown_20d_pct'])}")
        if parts:
            lines.append("### 行情分析师（趋势/波动/位置）")
            lines.append("- " + "；".join(parts))

    # ---- 基准对比 ----
    b = rc.get("benchmark_ctx") or {}
    bs = b.get("benchmark_stats") or {}
    if bs.get("ok"):
        parts = []
        if bs.get("mom_20d_pct") is not None:
            parts.append(f"基准20日动量 {_fmt_pct(bs['mom_20d_pct'])}")
        if b.get("relative_strength_20d_pct") is not None:
            parts.append(f"标的20日相对强度（超额） {_fmt_pct(b['relative_strength_20d_pct'])}")
        if parts:
            lines.append("### 基准对比")
            lines.append("- " + "；".join(parts))

    # ---- 同类事件基率（expanding window）----
    st = rc.get("bucket_stats") or {}
    if st.get("n_prior", 0) >= 5:
        note = "（样本较少，仅供参考）" if st.get("insufficient") else ""
        parts = [f"同类历史事件 n={st['n_prior']}{note}"]
        for k, lab in (("p_up", "P(up)"), ("p_down", "P(down)"), ("p_neutral", "P(neutral)")):
            if st.get(k) is not None:
                parts.append(f"{lab} {st[k]*100:.0f}%")
        if st.get("avg_car_primary_pct") is not None:
            parts.append(f"定向平均CAR {_fmt_pct(st['avg_car_primary_pct'])}")
        if st.get("p_car_pos") is not None:
            parts.append(f"正CAR占比 {st['p_car_pos']*100:.0f}%")
        lines.append("### 同类事件基率（expanding window，严格早于本次事件）")
        lines.append("- " + "；".join(parts))

    # ---- 多情景推演 ----
    sc = rc.get("scenarios") or {}
    if sc.get("ok"):
        lines.append("### 多情景推演（基率 ± 当前趋势微调）")
        lines.append(f"- 乐观(up) P={sc['bull']['prob']:.2f}"
                     + (f"，历史平均CAR {_fmt_pct(sc['bull'].get('avg_car'))}" if sc['bull'].get('avg_car') is not None else "")
                     + f"；中性 P={sc['base']['prob']:.2f}；悲观(down) P={sc['bear']['prob']:.2f}")

    # ---- 证据摘要（证据图节点）----
    ev_items = rc.get("evidence_items") or []
    if ev_items:
        lines.append("### 证据摘要（证据图节点，direction/strength）")
        dir_cn = {"up": "偏多", "down": "偏空", "neutral": "中性"}
        for it in ev_items[:6]:
            lines.append(f"- [{it.get('source','?')}] {it.get('claim','')} → {dir_cn.get(it.get('direction'), '?')}（{it.get('strength','?')}）")

    return "\n".join(lines)


def build_input_block(event: dict, label: Optional[dict] = None,
                       include_ground_truth: bool = False,
                       research: Optional[dict] = None) -> dict:
    """构建单条样本的 INPUT 结构化上下文（放入 user message 中）。

    字段：
      · 事件元信息（market/symbol/日期/类型/标题）
      · 正文 event_text（截断到 1500 chars 防 seq_len 爆炸）
      · 四维量价特征（由 precompute_research_cache.py 写入 events）
      · 定向场景信息：主 horizon、次 horizon、scene_priority、激活专家
      · Router 初始权重（由无参数 Router 计算得到）
      · [可选] research：precompute_research_cache.py 的研究缓存行 →
        渲染成「前置研究上下文」段（Tier 1 Experts 预计算，GRPO rollout 不再重跑）
      · [可选] ground truth：只在 SFT/RFT 的 completion 中出现，prompt 里绝不出现
    """
    mkt   = str(event.get("market") or "").upper()
    el2   = str(event.get("event_type_l2") or "")
    sym   = str(event.get("symbol") or "")
    ev_id = str(event.get("event_id") or "")
    ev_dt = str(event.get("event_time") or event.get("event_date") or "")[:10]
    title = str(event.get("title") or "")
    text  = (event.get("event_text") or "")
    if len(text) > 1500: text = text[:1500] + "\n... [truncated 1500 chars for RLVR seq_len budget]"

    meta = scene_meta_for(mkt, el2)
    primary_h = meta["primary_horizon"]
    secondary_hs = meta["secondary_horizons"]
    priority = meta["scene_priority"]

    # 四维量价（来自 events.jsonl，若缺失则标记 N/A）
    vol = {
        "vol_t0_ratio":        event.get("vol_t0_ratio"),
        "vol_pre5_ratio":      event.get("vol_pre5_ratio"),
        "price_vol_diverge":   event.get("price_vol_diverge"),
        "range_t0_normalized": event.get("range_t0_normalized"),
        "vol_regime":          event.get("vol_regime", "NORMAL"),
    }

    # Router 初始权重
    rw = router_weights(mkt, el2, vol.get("vol_regime"), vol.get("vol_t0_ratio"))
    active_experts = expert_targets_for(mkt, el2, vol.get("vol_regime"))

    block = {
        "event_id": ev_id,
        "market": mkt,
        "symbol": sym,
        "event_date": ev_dt,
        "event_type_l2": el2,
        "title": title,
        "event_text": text,
        "scene": {
            "primary_horizon": primary_h,
            "secondary_horizons": secondary_hs,
            "scene_priority": priority,
            "active_experts": active_experts,
        },
        "volume_features": {
            "vol_t0_ratio (T0 量 / 前20 均量)":  _fmt_f(vol["vol_t0_ratio"]),
            "vol_pre5_ratio (前5 均量 / 前20)": _fmt_f(vol["vol_pre5_ratio"]),
            "price_vol_diverge (5日量价背离：正=共振 负=背离)": _fmt_f(vol["price_vol_diverge"], 2),
            "range_t0_normalized (T0 振幅倍数)": _fmt_f(vol["range_t0_normalized"], 2),
            "vol_regime": vol["vol_regime"],
        },
        "router_prior_weights": {k: round(v, 3) for k, v in rw.items()},
    }
    if research is not None:
        block["research_context_text"] = render_research_context(research)
        block["_research"] = research
    if include_ground_truth and label:
        # 仅供 RFT 拼装 reference completion 时单独使用；不进 user prompt
        block["_gt"] = {
            f"label_{primary_h}": label.get(f"label_{primary_h}"),
            f"car_{primary_h}":   label.get(f"car_{primary_h}"),
            f"ret_{primary_h}":   label.get(f"ret_{primary_h}"),
            "horizons_complete":  label.get("horizons_complete"),
            "ret_car_agree_5h":   label.get("ret_car_agree_5h"),
        }
    return block


def user_message_from_block(block: dict) -> str:
    """把 INPUT block 渲染成自然语言 user message（喂给 LLM 的 prompt 部分）。"""
    b = block
    s = b["scene"]
    v = b["volume_features"]
    lines = [
        "## 事件元信息",
        f"- Market: {b['market']}  |  Symbol: {b['symbol']}  |  EventDate: {b['event_date']}",
        f"- EventType L2: {b['event_type_l2']}",
        f"- 标题：{b['title']}",
        "",
        "## 事件正文",
        b['event_text'],
        "",
        "## 定向场景（Pronoia-RLVR 内置）",
        f"- 主评估窗口：T+{s['primary_horizon'][1:]}（primary horizon = {s['primary_horizon']}）",
        f"- 次窗口：{', '.join(f'T+{h[1:]}' for h in s['secondary_horizons'])}",
        f"- 场景信号强度：{s['scene_priority']}",
        f"- 初始激活专家（Router 先验）：{', '.join(s['active_experts'])}",
        f"- Router 权重先验：{json.dumps(b['router_prior_weights'], ensure_ascii=False)}",
        "",
        "## 四维量价特征（strict as-of T0，严禁未来数据）",
    ]
    for kk, vv in v.items():
        lines.append(f"- {kk}：{vv}")
    if b.get("research_context_text"):
        lines += ["", b["research_context_text"]]
    lines += [
        "",
        "请按 7 段 CoT 严格推理，并在【5. 最终方向】中输出：direction(up/down/neutral) + confidence(0~1) + 融合来源。",
        "要求：",
        "  · 【0】必须显式写出主窗口（上面给的 primary horizon）；",
        "  · 【0.5】必须引用 ≥1 条上面给出的量价数值，并判断 vol_regime 是否支持你最终方向；",
        "  · 【1】请引用「前置研究上下文」中与本次事件最相关的证据（趋势/相对强度/同类基率）；",
        "  · 【2】横向比较必须引用同类事件基率数值（若给出）；",
        "  · 【4】必须显式写出 confidence（如 confidence=0.68），并给出来源（如：量价背离 +0.12，历史同类型命中率 62% → 合并 0.68）；",
        "  · 【5】最终方向只输出一个单词（up 或 down 或 neutral），并用一句话说明融合来源（哪几位专家权重高）。",
    ]
    return "\n".join(lines)


def build_rft_reference(block: dict, strict: bool = True) -> str:
    """RFT 阶段的「标准参考 completion」—— 按 7 段模板 + GT 自动生成。
    （真实训练时会再用 trained annotator model 精修一遍；此处作为 RFT step1 bootstrap。）"""
    gt = block.get("_gt") or {}
    s = block["scene"]; v = block["volume_features"]; b = block
    dir_gt = gt.get(f"label_{s['primary_horizon']}", "neutral") or "neutral"
    car_gt = gt.get(f"car_{s['primary_horizon']}")
    ret_gt = gt.get(f"ret_{s['primary_horizon']}")
    complete = bool(gt.get("horizons_complete"))
    agree5h = bool(gt.get("ret_car_agree_5h"))

    # 基于 car_gt 大小给一个合理的 confidence 启发式（RFT 启动用，GRPO 阶段模型会自己学会校准）
    try:
        car_abs = abs(float(car_gt)) if isinstance(car_gt, (int, float)) else 0.0
    except Exception:
        car_abs = 0.0
    conf_naive = 0.5 + min(0.4, car_abs / 0.20)  # car=20% → conf≈0.9
    if not complete: conf_naive -= 0.10
    if not agree5h:  conf_naive -= 0.05
    conf_naive = max(0.25, min(0.95, conf_naive))

    # 量价段：按 vol_regime 给出支持 / 不支持的判断
    regime = str(v.get("vol_regime") or "NORMAL")
    regime_support = "支持"
    if regime == "HIGH" and dir_gt == "up":
        regime_support = "部分支持（放量上涨需警惕后续获利回吐，置信度应降低 0.05）"
    elif regime == "HIGH" and dir_gt == "down":
        regime_support = "支持（放量下跌确认空头信号）"
    elif regime == "LOW" and dir_gt == "up":
        regime_support = "不支持（缩量上涨为假突破概率高，建议谨慎）"
    elif regime == "LOW" and dir_gt == "down":
        regime_support = "中性（缩量下跌无恐慌盘，但也不排除阴跌）"

    # 融合来源：取 Router 前 2 位专家
    rw = sorted(b["router_prior_weights"].items(), key=lambda x: -x[1])
    top2 = [e for e, _ in rw[:2]]

    # ---- 前置研究上下文引用（若有）----
    rc = b.get("_research") or {}
    mctx = rc.get("market_ctx") or {}
    bctx = rc.get("benchmark_ctx") or {}
    bstat = rc.get("bucket_stats") or {}
    sig_parts = []
    if isinstance(mctx.get("mom_20d_pct"), (int, float)):
        sig_parts.append(f"事件前20日动量 {mctx['mom_20d_pct']:+.2f}%")
    if isinstance(bctx.get("relative_strength_20d_pct"), (int, float)):
        sig_parts.append(f"相对基准20日超额 {bctx['relative_strength_20d_pct']:+.2f}%")
    if isinstance(mctx.get("pos_52w_pct"), (int, float)):
        sig_parts.append(f"52周区间位置 {mctx['pos_52w_pct']:.0f}%")
    sig_text = ("研究上下文佐证：" + "；".join(sig_parts) + "。") if sig_parts else ""
    if bstat.get("n_prior", 0) >= 5 and bstat.get("p_up") is not None:
        comp_text = (f"同类 {b['market']} × {b['event_type_l2']} 历史事件 n={bstat['n_prior']}："
                     f"P(up)={bstat['p_up']*100:.0f}%，P(down)={bstat['p_down']*100:.0f}%，P(neutral)={bstat['p_neutral']*100:.0f}%"
                     + (f"，定向平均 CAR {bstat['avg_car_primary_pct']:+.2f}%" if bstat.get("avg_car_primary_pct") is not None else "")
                     + (f"，正 CAR 占比 {bstat['p_car_pos']*100:.0f}%" if bstat.get("p_car_pos") is not None else "")
                     + "（expanding window，严格早于本次事件）。")
    else:
        comp_text = "同类事件历史样本不足（n<5），无可靠基率，横向比较退化为场景先验判断。"

    lines = [
        f"【0. 预判时间窗口】主评估窗口为 T+{s['primary_horizon'][1:]}（{s['primary_horizon']}），"
        f"因为 {b['event_type_l2']} 类事件属于{'宏观短期吸收快' if s['primary_horizon']=='t3' else '财报指引中短期动量' if s['primary_horizon']=='t7' else '并购重组中期落地'}场景。",
        "",
        f"【0.5 量价 regime 校验】四维：vol_t0_ratio={v.get('vol_t0_ratio (T0 量 / 前20 均量)','N/A')}，"
        f"vol_pre5_ratio={v.get('vol_pre5_ratio (前5 均量 / 前20)','N/A')}，"
        f"price_vol_diverge={v.get('price_vol_diverge (5日量价背离：正=共振 负=背离)','N/A')}，"
        f"range_t0_normalized={v.get('range_t0_normalized (T0 振幅倍数)','N/A')} → "
        f"vol_regime={regime}。对最终方向的判断：{regime_support}。",
        "",
        f"【1. 关键信号提取】事件《{b['title']}》属于 {b['event_type_l2']}，"
        f"正文关键点：{b['event_text'][:120]}。{sig_text}",
        "",
        f"【2. 横向比较】{comp_text}",
        "",
        f"【3. 反方与限制】失效条件：① T+{s['secondary_horizons'][0][1:]} 方向与主窗口相反（双窗不一致）；"
        f"② RET↔CAR 同号率低于 70%（alpha 不纯：事件后标的自身收益 vs 相对基准超额方向背离）；③ vol_regime 从 {regime} 跳到反向桶。",
        "",
        f"【4. 置信度校准】confidence={conf_naive:.2f}（来源：主窗口 CAR 幅度启发 {car_abs*100:.2f}% → 基础分，"
        f"{'horizons_complete=✓' if complete else 'horizons 不全 -0.10'}，"
        f"{'RET 5h 同号=✓' if agree5h else 'RET 5h 不全同号 -0.05'}，量价 regime 修正已计入）。",
        "",
        f"【5. 最终方向】direction: {dir_gt}，融合来源：专家组合 {top2}（Router 先验权重 Top2，加上量价 regime 修正后得到最终判断）。",
    ]
    return "\n".join(lines)


def build_messages_for_sft(event: dict, label: dict,
                           research: Optional[dict] = None) -> list[dict]:
    """SFT/RFT 标准 messages 格式（兼容 trl SFTTrainer）。"""
    block = build_input_block(event, label, include_ground_truth=True, research=research)
    return [
        {"role": "system", "content": SYSTEM_PROMPT_BASE},
        {"role": "user",   "content": user_message_from_block(block)},
        {"role": "assistant", "content": build_rft_reference(block, strict=True)},
    ]


def build_prompt_completion_for_grpo(event: dict,
                                     research: Optional[dict] = None) -> dict:
    """GRPO 阶段：prompt = 不含 completion 的 input（含前置研究上下文）；
    label / reward 所需字段由 GRPO 数据集行携带（TRL 会把额外列透传给 reward_funcs）。"""
    block = build_input_block(event, label=None, include_ground_truth=False, research=research)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_BASE},
        {"role": "user",   "content": user_message_from_block(block)},
    ]
    return {
        "event_id": event.get("event_id"),
        "messages": messages,
        "_scene_primary_h": block["scene"]["primary_horizon"],
        "_router_prior": block["router_prior_weights"],
    }

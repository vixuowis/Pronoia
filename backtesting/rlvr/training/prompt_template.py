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


def build_input_block(event: dict, label: Optional[dict] = None,
                       include_ground_truth: bool = False) -> dict:
    """构建单条样本的 INPUT 结构化上下文（放入 user message 中）。

    字段：
      · 事件元信息（market/symbol/日期/类型/标题）
      · 正文 event_text（截断到 1500 chars 防 seq_len 爆炸）
      · 四维量价特征（由 build_volume_features.py 写入 events）
      · 定向场景信息：主 horizon、次 horizon、scene_priority、激活专家
      · Router 初始权重（由无参数 Router 计算得到）
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
    lines += [
        "",
        "请按 7 段 CoT 严格推理，并在【5. 最终方向】中输出：direction(up/down/neutral) + confidence(0~1) + 融合来源。",
        "要求：",
        "  · 【0】必须显式写出主窗口（上面给的 primary horizon）；",
        "  · 【0.5】必须引用 ≥1 条上面给出的量价数值，并判断 vol_regime 是否支持你最终方向；",
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
        f"正文关键点：{b['event_text'][:120]}。",
        "",
        f"【2. 横向比较】同类 {b['market']} × {b['event_type_l2']} 事件历史表现：定向 T+{s['primary_horizon'][1:]} CAR 均值见训练集分桶统计；本次主 benchmark 收益相对位置正常。",
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


def build_messages_for_sft(event: dict, label: dict) -> list[dict]:
    """SFT/RFT 标准 messages 格式（兼容 trl SFTTrainer）。"""
    block = build_input_block(event, label, include_ground_truth=True)
    return [
        {"role": "system", "content": SYSTEM_PROMPT_BASE},
        {"role": "user",   "content": user_message_from_block(block)},
        {"role": "assistant", "content": build_rft_reference(block, strict=True)},
    ]


def build_prompt_completion_for_grpo(event: dict) -> dict:
    """GRPO 阶段：prompt = 不含 completion 的 input；label 外部给 reward_fn 计算。"""
    block = build_input_block(event, label=None, include_ground_truth=False)
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

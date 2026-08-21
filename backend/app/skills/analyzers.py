"""分析推理 Skills（Tier 2 信号处理 + Tier 1 市场分析思维）。

设计目标
========
当前系统的 14 个已有 skill 全是数据采集工具（拉行情/财报/新闻），
"怎么判断方向"的逻辑全压在 LLM system prompt 的评分卡里——一套评分卡打天下。

本模块新建 7 个分析推理 skill，分两层：

Tier 2 · 信号处理（跨市场通用，解决 case study 三个本质缺陷）：
  - announcement_classifier: 公告子类型分类（7 类规则 + 泛化接口）
  - ar_decomposer: T0 AR 主动/被动分解
  - drift_context_analyzer: 事前漂移非线性映射 + 出尽系数

Tier 1 · 市场分析思维（按 market × event_type 路由，替代一刀切评分卡）：
  - cn_ma_analyzer: A 股并购分析思维
  - cn_earnings_analyzer: A 股财报分析思维
  - us_ma_analyzer: 美股并购分析思维

泛化性设计
========
1. 规则集可扩展：announcement_classifier 的规则是 list[dict]，业务方可追加
2. 阈值可配置：drift_context_analyzer 的分档阈值是参数，默认值来自 case study
3. 权重矩阵可覆盖：市场分析 skill 的信号权重是 dict，调用方可传自定义权重
4. 不硬编码个股/行业：所有 skill 只接收结构化信号，不依赖具体 symbol
"""
from __future__ import annotations

import re
from typing import Any

from .registry import err, meta, ok, skill


# ============================================================ Tier 2
# ====== announcement_classifier ======
# 公告子类型分类器：按标题+正文关键词分为 7 类。
# 解决问题：case study 发现"报告书/草案"24% ACC、"合规/进展"46% ACC，
#   子类型差异巨大但当前系统一视同仁。

_ANNOUNCEMENT_RULES: list[dict[str, Any]] = [
    # NOTE: 匹配顺序很重要，高信息量/强方向性的规则放前面：
    #   先终止（强空）> 首次披露（强多）> 完成 > 合规 > 中介 > 进展 > 报告书 > 财报类
    {
        "subtype": "termination",
        "label": "终止/失败",
        "patterns": [r"终止.*?重组", r"终止.*?收购", r"撤回", r"失败", r"不予.*?审核",
                     r"重组.*?终止"],
        "description": "重组终止/失败，明确利空",
        "info_tier": "high",
        "default_prior": "down",
    },
    {
        "subtype": "first_disclosure",
        "label": "首次披露/预案",
        "patterns": [r"预案", r"第一次", r"首次披露", r"初步方案", r"筹划.*?停牌"],
        "description": "首次披露重组方案/预案，通常含对价、比例等实质信息",
        "info_tier": "high",
        "default_prior": "up",
    },
    {
        "subtype": "completion",
        "label": "完成/交割",
        "patterns": [r"完成.*?交割", r"过户完成", r"股份.*?过户", r"标的.*?交割",
                     r"已完成.*?收购"],
        "description": "交易完成/交割，尘埃落定",
        "info_tier": "medium",
        "default_prior": "up",
    },
    {
        "subtype": "compliance_reply",
        "label": "合规/问询回复/监管说明",
        "patterns": [r"问询.*?回复", r"回复.*?问询", r"说明函", r"不构成.*?重组上市",
                     r"不构成.*?重大资产重组", r"核查意见", r"合规.*?说明",
                     r"不存在.*?上市公司监管指引", r"本次重组.*?符合",
                     r"监管指引第", r"内幕信息知情人", r"自查报告",
                     r"符合.*?重组.*?规定"],
        "description": "合规回复/问询函回复/监管指引合规说明/自查，程序性文件为主",
        "info_tier": "low",
        "default_prior": "down",
    },
    {
        "subtype": "intermediary_opinion",
        "label": "中介机构意见",
        "patterns": [r".*?证券.*?关于", r"保荐.*?意见", r"独立财务顾问.*?意见",
                     r"律师.*?意见", r"评估.*?报告", r"审计.*?报告"],
        "description": "中介机构（券商/律所/评估/审计）核查意见，纯流程文件",
        "info_tier": "low",
        "default_prior": "neutral",
    },
    {
        "subtype": "progress_update",
        "label": "进展/风险提示",
        "patterns": [r"进展公告", r"风险提示公告$", r"提示性公告$", r"复牌公告",
                     r"停牌.*?进展公告", r"重大资产重组事项进展公告",
                     r"重大资产重组.*?进展情况$", r"资产重组.*?进展情况公告"],
        "description": "进展/风险提示公告（无「报告书/草案/问询回复」等更强关键词时），信息量取决于是否含新实质内容",
        "info_tier": "medium",
        "default_prior": "neutral",
    },
    {
        "subtype": "report_draft",
        "label": "报告书/草案",
        "patterns": [r"报告书", r"草案", r"修订稿", r"上会稿"],
        "description": "报告书/草案发布，流程节点，市场通常已提前反应",
        "info_tier": "low",
        "default_prior": "down",
    },
    {
        "subtype": "earnings_notice_meeting",
        "label": "业绩说明会/投资者交流会预告",
        "patterns": [r"业绩说明会", r"投资者.*?接待日", r"集体业绩说明会",
                     r"年报.*?业绩说明会", r"季报.*?业绩说明会",
                     r"业绩说明会.*?预告", r"投资者说明会", r"业绩说明会.*?公告"],
        "description": "业绩说明会/投资者集体接待日预告通知——不含实际业绩数值，管理层倾向回避披露利空，默认偏弱。",
        "info_tier": "low",
        "default_prior": "down",
    },
    {
        "subtype": "earnings_actual_report",
        "label": "实际业绩报告/快报/预告",
        "patterns": [r"年度业绩预告", r"季度业绩预告", r"业绩预告", r"年度业绩快报",
                     r"季度报告.*?业绩", r"年度报告.*?业绩", r"归母净利",
                     r"营业收入.*?同比", r"净利润.*?同比", r"业绩快报"],
        "description": "含实际业绩数字（净利/营收/增速）的报告/预告/快报，信息量高，方向需要看具体数值。",
        "info_tier": "high",
        "default_prior": "neutral",
    },
]

# 美股 SEC filing 类型映射（补充规则）
_US_FILING_RULES: list[dict[str, Any]] = [
    {
        "subtype": "us_rule_425",
        "label": "Rule 425 程序性备案",
        "patterns": [r"rule\s*425", r"425\s*filing"],
        "description": "美股 Rule 425 并购程序性备案，信息量低",
        "info_tier": "low",
        "default_prior": "down",
    },
    {
        "subtype": "us_8k_material",
        "label": "8-K 实质事项",
        "patterns": [r"8-k", r"item\s*9\.01", r"material.*?agreement",
                     r"entry.*?into.*?agreement"],
        "description": "8-K 实质协议签署，信息量较高",
        "info_tier": "medium",
        "default_prior": "up",
    },
]


@skill(
    "announcement_classifier",
    "公告子类型分类器：按标题+正文关键词将公告分为 7 类"
    "（首次披露/预案、报告书/草案、合规/问询回复、中介机构意见、"
    "进展/风险提示、完成/交割、终止/失败），"
    "每类附带信息量评级（high/medium/low）和默认方向先验。"
    "美股 Rule 425 / 8-K 自动识别。"
    "用于解决 A 股并购中不同子类型准确率差异巨大的问题（24%-100%）。",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "公告标题"},
            "text": {"type": "string", "description": "公告正文（可截断）"},
            "market": {"type": "string", "enum": ["CN", "US", "HK"],
                       "description": "市场：CN=A股, US=美股, HK=港股"},
            "custom_rules": {"type": "array", "items": {"type": "object"},
                             "description": "自定义规则（扩展用），每条含 subtype/label/patterns/info_tier/default_prior"},
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    category="skill",
    internal=False,
)
async def announcement_classifier(title: str, text: str = "",
                                  market: str = "CN",
                                  custom_rules: list[dict] | None = None) -> dict:
    rules = list(_ANNOUNCEMENT_RULES)
    if market == "US":
        rules = list(_US_FILING_RULES) + rules
    if custom_rules:
        rules = list(custom_rules) + rules

    title_lower = (title or "").lower()
    text_lower = (text or "")[:2000].lower()
    search_pool = f"{title_lower} {text_lower}"

    matches: list[dict] = []
    for rule in rules:
        for pat in rule.get("patterns", []):
            try:
                if re.search(pat, search_pool, re.IGNORECASE):
                    matches.append({
                        "subtype": rule["subtype"],
                        "label": rule["label"],
                        "info_tier": rule["info_tier"],
                        "default_prior": rule["default_prior"],
                        "matched_pattern": pat,
                        "description": rule.get("description", ""),
                    })
                    break
            except re.error:
                continue

    if not matches:
        return ok({
            "subtype": "unclassified",
            "label": "未分类",
            "info_tier": "medium",
            "default_prior": "neutral",
            "matched_pattern": None,
            "description": "未匹配到已知规则，建议人工判断或补充规则",
            "all_matched": [],
        }, meta("announcement_classifier", 1))

    primary = matches[0]
    primary["all_matched"] = [m["subtype"] for m in matches]
    return ok(primary, meta("announcement_classifier", 1))


# ====== ar_decomposer ======
# T0 AR 主动/被动分解：解决 case study 缺陷一
# "基准跌导致的虚假超额"被当成方向信号。
# 例：NFLX +0.23%, QQQ -1.86%, AR=+2.09% → 主动收益 +0.23%, 被动超额 +1.86%
# 只有主动收益有方向信号价值。

@skill(
    "ar_decomposer",
    "T0 超额收益(AR)主动/被动分解：将 AR 分解为'个股主动涨跌'和'基准波动被动超额'。"
    "解决问题：基准大跌时个股微涨产生虚假 AR，被误判为 up 信号。"
    "输入：stock_return（个股 T0 涨跌%）、benchmark_return（基准 T0 涨跌%）。"
    "输出：active_return（主动收益，有方向信号价值）、"
    "passive_excess（被动超额，来自基准波动，噪声）、signal_valid（是否可用于方向判断）。",
    {
        "type": "object",
        "properties": {
            "stock_return_pct": {"type": "number",
                                 "description": "个股 T0 当日涨跌幅（%，如 0.23 表示 +0.23%）"},
            "benchmark_return_pct": {"type": "number",
                                     "description": "基准 T0 当日涨跌幅（%，如 -1.86 表示 -1.86%）"},
            "threshold_pct": {"type": "number",
                              "description": "主动收益绝对值低于此阈值时 signal_valid=False（默认 0.5%）"},
        },
        "required": ["stock_return_pct", "benchmark_return_pct"],
        "additionalProperties": False,
    },
    category="skill",
    internal=False,
)
async def ar_decomposer(stock_return_pct: float, benchmark_return_pct: float,
                        threshold_pct: float = 0.5) -> dict:
    stock = float(stock_return_pct)
    bench = float(benchmark_return_pct)
    ar = stock - bench  # 传统 AR
    active = stock  # 主动收益 = 个股绝对涨跌
    passive = -bench  # 被动超额 = 来自基准波动的部分（基准跌时为正，基准涨时为负）

    signal_valid = abs(active) >= threshold_pct
    # 主动收益方向（只看个股自己涨跌了没有）
    if active > threshold_pct:
        active_direction = "up"
    elif active < -threshold_pct:
        active_direction = "down"
    else:
        active_direction = "neutral"

    return ok({
        "ar_pct": round(ar, 4),
        "active_return_pct": round(active, 4),
        "passive_excess_pct": round(passive, 4),
        "signal_valid": signal_valid,
        "active_direction": active_direction,
        "note": (
            f"个股 {'涨' if stock > 0 else '跌'} {abs(stock):.2f}%，"
            f"基准 {'涨' if bench > 0 else '跌'} {abs(bench):.2f}%，"
            f"AR={ar:+.2f}% 但其中被动超额={passive:+.2f}%。"
            + ("主动收益有方向信号价值。" if signal_valid
               else "个股自身涨跌幅度太小，AR 主要来自基准波动，方向信号无效。")
        ),
    }, meta("ar_decomposer", 1))


# ====== drift_context_analyzer ======
# 事前漂移非线性映射 + 出尽系数：解决 case study 缺陷二和三
# pre5/pre20 漂移从线性 1/2/3 分改为非线性映射
# 引入"出尽系数"：pre5≥5% AND pre20≥10% 时触发利好出尽信号

@skill(
    "drift_context_analyzer",
    "事前漂移非线性映射 + 多horizon持续性 + 利好出尽系数计算。"
    "解决：① 评分卡线性映射低估大幅漂移 ② 缺乏'前期涨太多=见光死'反向规则 "
    "③ 仅用pre5/pre20两个窗口不够判断趋势持续性。"
    "必填 pre5_pct / pre20_pct（事前5/20日累计涨跌幅%）。"
    "可选 pre1_pct / pre10_pct / pre66_pct（更多窗口，增强持续性判断）。"
    "输出：各horizon分值、drift_score、direction_hint、sell_the_news_*、以及 "
    "horizon_consistency（同向比例0~1）、drift_monotonic、long_term_persistence_direction。",
    {
        "type": "object",
        "properties": {
            "pre5_pct": {"type": "number", "description": "事前 5 日累计涨跌幅%（必填）"},
            "pre20_pct": {"type": "number", "description": "事前 20 日累计涨跌幅%（必填）"},
            "pre1_pct": {"type": "number", "description": "事前 1 日涨跌幅%（可选，增强持续性判断）"},
            "pre10_pct": {"type": "number", "description": "事前 10 日累计涨跌幅%（可选）"},
            "pre66_pct": {"type": "number", "description": "事前 66 日（≈季度）累计涨跌幅%（可选，长周期趋势）"},
            "thresholds": {"type": "object", "description": "自定义分档阈值（泛化用），可选"},
        },
        "required": ["pre5_pct", "pre20_pct"],
        "additionalProperties": False,
    },
    category="skill",
    internal=False,
)
async def drift_context_analyzer(pre5_pct: float, pre20_pct: float,
                                 pre1_pct: float | None = None,
                                 pre10_pct: float | None = None,
                                 pre66_pct: float | None = None,
                                 thresholds: dict | None = None) -> dict:
    p1 = float(pre1_pct) if pre1_pct is not None else None
    p5 = float(pre5_pct)
    p10 = float(pre10_pct) if pre10_pct is not None else None
    p20 = float(pre20_pct)
    p66 = float(pre66_pct) if pre66_pct is not None else None

    # 默认分档阈值（可通过 thresholds 参数覆盖，保持泛化性）
    t = {
        "small": 2.0,    # <2% → 1 分
        "medium": 5.0,    # 2-5% → 2 分
        "large": 10.0,    # 5-10% → 3 分
        # >10% → 4 分
    }
    if thresholds:
        t.update(thresholds)

    def _score(val: float) -> int:
        a = abs(val)
        if a < t["small"]:
            return 1
        if a < t["medium"]:
            return 2
        if a < t["large"]:
            return 3
        return 4

    def _dir(val: float, eps: float = 0.5) -> str:
        if val > eps:
            return "up"
        if val < -eps:
            return "down"
        return "neutral"

    s1 = _score(p1) if p1 is not None else None
    s5 = _score(p5)
    s10 = _score(p10) if p10 is not None else None
    s20 = _score(p20)
    s66 = _score(p66) if p66 is not None else None

    # 取全部非空窗口的最大分值作为漂移强度
    all_scores = [s for s in [s1, s5, s10, s20, s66] if s is not None]
    drift_score = max(all_scores) if all_scores else max(s5, s20)
    # 方向以 pre20 为主（更长窗口更稳定）；如果 pre66 可用且与 pre20 一致，就更有信心
    base_dir = _dir(p20)
    if p66 is not None:
        d66 = _dir(p66)
        if d66 != "neutral":
            base_dir = d66 if base_dir == "neutral" or base_dir == d66 else base_dir
    direction_hint = base_dir

    # ---- 多 horizon 一致性 & 持续性 ----
    dirs: list[tuple[str, float]] = []  # (direction, abs_pct) 非 neutral 才加入
    for name, val in [("pre1", p1), ("pre5", p5), ("pre10", p10), ("pre20", p20), ("pre66", p66)]:
        if val is None: continue
        d = _dir(val)
        if d != "neutral": dirs.append((d, abs(val)))
    n_valid = len(dirs)
    if n_valid >= 2:
        up_cnt = sum(1 for d,_ in dirs if d == "up")
        down_cnt = sum(1 for d,_ in dirs if d == "down")
        maj = max(up_cnt, down_cnt)
        horizon_consistency: float | None = maj / n_valid
        long_term_persistence: str | None = (
            "up" if up_cnt > down_cnt else ("down" if down_cnt > up_cnt else "neutral")
        )
        # 单调：如果所有非空窗口同向（一致性=1且全up或全down）
        drift_monotonic = bool(horizon_consistency and horizon_consistency >= 0.99 and (up_cnt == 0 or down_cnt == 0))
    else:
        horizon_consistency = None
        long_term_persistence = None
        drift_monotonic = False

    # 出尽系数：当 pre5 和 pre20 同向且均大幅上涨时触发出尽信号
    # 系数 = max(0, pre5/5) × max(0, pre20/10)，当两者都超过阈值时 >1
    # 有 pre66 同向时额外再 ×1.2（长周期也在涨，出尽风险更大）
    sell_coeff = 0.0
    extra_boost = 1.0
    if p5 > 0 and p20 > 0:
        if p66 is not None and p66 > 0: extra_boost = 1.2
        sell_coeff = (max(0, p5 / t["medium"]) * max(0, p20 / t["large"])) * extra_boost
    elif p5 < 0 and p20 < 0:
        if p66 is not None and p66 < 0: extra_boost = 1.2
        sell_coeff = (max(0, abs(p5) / t["medium"]) * max(0, abs(p20) / t["large"])) * extra_boost

    sell_triggered = sell_coeff > 1.0
    sell_direction = "down" if p5 > 0 and p20 > 0 else "up" if p5 < 0 and p20 < 0 else None

    result = {
        "pre1_score": s1,
        "pre5_score": s5,
        "pre10_score": s10,
        "pre20_score": s20,
        "pre66_score": s66,
        "drift_score": drift_score,
        "direction_hint": direction_hint,
        "horizon_consistency": round(horizon_consistency, 3) if horizon_consistency is not None else None,
        "n_horizons_used": n_valid,
        "drift_monotonic": drift_monotonic,
        "long_term_persistence_direction": long_term_persistence,
        "sell_the_news_coefficient": round(sell_coeff, 3),
        "sell_the_news_triggered": sell_triggered,
        "sell_the_news_direction": sell_direction,
    }
    note_parts = []
    hor = [(n,p,s) for n,p,s in [("pre1",p1,s1),("pre5",p5,s5),("pre10",p10,s10),("pre20",p20,s20),("pre66",p66,s66)] if p is not None]
    segs = [f"{n}={p:+.2f}%(分{s})" for n,p,s in hor]
    note_parts.append(", ".join(segs) + f"; 漂移强度={drift_score}, 方向={direction_hint}.")
    if n_valid >= 2:
        note_parts.append(
            f"多窗口一致性={horizon_consistency*100:.0f}%({n_valid}窗) "
            f"{'单调✅' if drift_monotonic else ''} 长周期={long_term_persistence or 'n/a'}.")
    if sell_triggered:
        note_parts.append(
            f"⚠️ 出尽信号触发：系数={sell_coeff:.2f}>1"
            + (f"(含pre66同向×{extra_boost})" if extra_boost != 1.0 else "")
            + f"，前期{'大涨' if p5 > 0 else '大跌'}后见光死风险，建议反向。")
    else:
        note_parts.append("未触发出尽信号。")
    result["note"] = " ".join(note_parts)
    return ok(result, meta("drift_context_analyzer", 1))


# ============================================================ Tier 1
# ====== 市场分析思维 Skills ======
# 每个 skill 是一套"怎么想"的框架，接收结构化信号，输出 ScoreCard。
# 路由器在 Plan 阶段按 market × event_type_l2 选用。
# 权重矩阵可通过参数覆盖，保持泛化性。

def _default_signal_weights() -> dict[str, float]:
    """默认信号权重（可被各市场 analyzer 覆盖）。"""
    return {
        "announcement_text": 1.0,    # 公告文本语义信号
        "t0_active_return": 1.5,     # T0 主动收益（ar_decomposer 输出）
        "pre_drift": 1.0,            # 事前漂移（drift_context_analyzer 输出）
        "fundamentals": 1.0,          # 基本面信号
        "event_subtype_prior": 0.5,  # 公告子类型先验
        "sell_the_news": 2.0,        # 利好出尽反向信号（高权重）
    }


def _compute_scorecard(signals: dict, weights: dict) -> dict:
    """通用评分卡计算：signals 是各信号的方向+强度，weights 是权重。
    返回 {direction, confidence, net_score, detail}。
    """
    net = 0.0
    detail: list[dict] = []
    for key, sig in signals.items():
        w = weights.get(key, 1.0)
        direction = sig.get("direction", "neutral")
        strength = float(sig.get("strength", 0))
        if direction == "up":
            contribution = strength * w
        elif direction == "down":
            contribution = -strength * w
        else:
            contribution = 0.0
        net += contribution
        detail.append({
            "signal": key,
            "direction": direction,
            "strength": strength,
            "weight": w,
            "contribution": round(contribution, 2),
        })

    abs_net = abs(net)
    if abs_net >= 6:
        direction = "up" if net > 0 else "down"
        confidence = min(0.85, 0.60 + abs_net * 0.02)
    elif abs_net >= 3:
        direction = "up" if net > 0 else "down"
        confidence = min(0.70, 0.52 + abs_net * 0.03)
    elif abs_net >= 0.5:
        # 收窄 neutral：|net| >= 0.5 就必须给方向（原阈值 1.0 → 80% neutral，改到 0.5 → neutral 仅剩纯噪声）
        direction = "up" if net > 0 else "down"
        confidence = max(0.51, 0.50 + abs_net * 0.02)
    else:
        direction = "neutral"
        confidence = 0.50

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "net_score": round(net, 2),
        "signal_detail": detail,
    }


# ====== cn_ma_analyzer ======

@skill(
    "cn_ma_analyzer",
    "A 股并购分析思维框架：针对中国 A 股并购/重组事件的方向判断。"
    "思维特点：① 程序性公告默认偏空（报告书/草案/合规回复/中介意见信息量低）"
    "② 利好出尽反向规则（pre5+pre20 大涨后见光死）"
    "③ *ST 保壳重组 T0 涨停≠持续涨 ④ 连续亏损+程序性公告=强空头组合。"
    "输入：各信号的方向+强度（由 event_study_skill/ar_decomposer/drift_context_analyzer 等产出）。"
    "输出：direction + confidence + 评分明细。",
    {
        "type": "object",
        "properties": {
            "signals": {"type": "object",
                        "description": "结构化信号：每个 key 是信号名，value 含 direction/strength"},
            "announcement_subtype": {"type": "string",
                                    "description": "announcement_classifier 输出的子类型"},
            "announcement_info_tier": {"type": "string",
                                       "description": "公告信息量评级 high/medium/low"},
            "custom_weights": {"type": "object",
                               "description": "自定义信号权重（覆盖默认值，泛化用）"},
        },
        "required": ["signals"],
        "additionalProperties": False,
    },
    category="skill",
    internal=False,
)
async def cn_ma_analyzer(signals: dict, announcement_subtype: str = "",
                         announcement_info_tier: str = "",
                         custom_weights: dict | None = None) -> dict:
    weights = _default_signal_weights()
    # A 股并购特化权重
    weights.update({
        "announcement_text": 0.3 if announcement_info_tier == "low" else 1.5,
        "t0_active_return": 1.5,
        "pre_drift": 1.2,
        "fundamentals": 1.3,  # A 股并购中基本面连续亏损是强信号
        "event_subtype_prior": 1.0,  # 程序性公告先验权重加强
        "sell_the_news": 2.5,  # 出尽信号权重最高
    })
    if custom_weights:
        weights.update(custom_weights)

    # 注入子类型先验信号
    if announcement_subtype and "event_subtype_prior" not in signals:
        prior_map = {
            "report_draft": ("down", 2),
            "compliance_reply": ("down", 2),   # 合规/监管指引/自查公告=程序性节点，市场普遍偏弱
            "intermediary_opinion": ("down", 1),
            "progress_update": ("neutral", 0),
            "first_disclosure": ("up", 2),
            "completion": ("up", 1),
            "termination": ("down", 3),       # 终止=强空（最多可抵消 pre5≈+18% 的利好漂移）
        }
        prior = prior_map.get(announcement_subtype, ("neutral", 0))
        signals["event_subtype_prior"] = {"direction": prior[0], "strength": prior[1]}

    scorecard = _compute_scorecard(signals, weights)
    scorecard["analyzer"] = "cn_ma_analyzer"
    scorecard["market"] = "CN"
    scorecard["event_type"] = "M&A"
    scorecard["weights_used"] = weights
    return ok(scorecard, meta("cn_ma_analyzer", 1))


# ====== cn_earnings_analyzer ======

@skill(
    "cn_earnings_analyzer",
    "A 股财报分析思维框架：针对中国 A 股业绩预告/快报/定期报告的方向判断。"
    "思维特点：① 基本面数字（同比增速）权重>T0 行情权重"
    "② 预告修正方向量化（上修/下修幅度）"
    "③ 同比增速区间映射：≥50% 强 up，0-50% 弱 up（可能出尽），<0 down"
    "④ 监管工作函='监管'二字本身是利空信号。",
    {
        "type": "object",
        "properties": {
            "signals": {"type": "object",
                        "description": "结构化信号：每个 key 是信号名，value 含 direction/strength"},
            "yoy_growth_pct": {"type": "number",
                               "description": "归母净利润同比增速%（如 90.0 表示 +90%）"},
            "custom_weights": {"type": "object",
                               "description": "自定义信号权重（覆盖默认值，泛化用）"},
        },
        "required": ["signals"],
        "additionalProperties": False,
    },
    category="skill",
    internal=False,
)
async def cn_earnings_analyzer(signals: dict, yoy_growth_pct: float | None = None,
                               announcement_subtype: str = "",
                               announcement_info_tier: str = "",
                               custom_weights: dict | None = None) -> dict:
    weights = _default_signal_weights()
    # A 股财报特化权重
    weights.update({
        "announcement_text": 2.0,   # 财报正文含数字，权重高
        "t0_active_return": 0.8,    # T0 行情权重降低（市场反应可能滞后/出尽）
        "pre_drift": 1.0,
        "fundamentals": 2.5,        # 基本面数字是最强信号
        "sell_the_news": 1.5,       # 财报出尽效应比并购弱
        "event_subtype_prior": 1.2, # 财报公告子类型先验（说明会预告=偏空）
    })
    if announcement_info_tier == "low":
        # low info 公告（业绩说明会预告）：LLM 文本语义基本不可靠，降权
        weights["announcement_text"] = 0.3
    if custom_weights:
        weights.update(custom_weights)

    # 注入公告子类型先验（earnings_notice_meeting = 偏空）
    if announcement_subtype and "event_subtype_prior" not in signals:
        prior_map = {
            "earnings_notice_meeting": ("down", 2),
            "earnings_actual_report": ("neutral", 0),
            "report_draft": ("down", 1),      # 财报里误分类时的兜底
            "compliance_reply": ("down", 1),
        }
        prior = prior_map.get(announcement_subtype, ("neutral", 0))
        if prior[1] > 0:
            signals["event_subtype_prior"] = {"direction": prior[0], "strength": prior[1]}

    # 注入同比增速信号
    if yoy_growth_pct is not None and "fundamentals" not in signals:
        growth = float(yoy_growth_pct)
        if growth >= 50:
            signals["fundamentals"] = {"direction": "up", "strength": 3}
        elif growth > 0:
            signals["fundamentals"] = {"direction": "up", "strength": 1}
        elif growth < -20:
            signals["fundamentals"] = {"direction": "down", "strength": 3}
        else:
            signals["fundamentals"] = {"direction": "down", "strength": 1}

    scorecard = _compute_scorecard(signals, weights)
    scorecard["analyzer"] = "cn_earnings_analyzer"
    scorecard["market"] = "CN"
    scorecard["event_type"] = "Earnings"
    scorecard["weights_used"] = weights
    return ok(scorecard, meta("cn_earnings_analyzer", 1))


# ====== us_ma_analyzer ======

@skill(
    "us_ma_analyzer",
    "美股并购分析思维框架：针对美国市场 M&A/Rule 425/Business Combination 的方向判断。"
    "思维特点：① Rule 425 程序性备案默认偏空（新股稀释）"
    "② T0 AR 主动/被动分解（基准大跌时虚假 AR 降权）"
    "③ 8-K 实质协议 > Rule 425 程序性备案 ④ 美股财报直接反应（无出尽）。",
    {
        "type": "object",
        "properties": {
            "signals": {"type": "object",
                        "description": "结构化信号：每个 key 是信号名，value 含 direction/strength"},
            "announcement_subtype": {"type": "string",
                                     "description": "announcement_classifier 输出的子类型"},
            "custom_weights": {"type": "object",
                               "description": "自定义信号权重（覆盖默认值，泛化用）"},
        },
        "required": ["signals"],
        "additionalProperties": False,
    },
    category="skill",
    internal=False,
)
async def us_ma_analyzer(signals: dict, announcement_subtype: str = "",
                         custom_weights: dict | None = None) -> dict:
    weights = _default_signal_weights()
    # 美股并购特化权重
    weights.update({
        "announcement_text": 1.5,   # 美股公告正文信息量较高
        "t0_active_return": 2.0,    # 美股 T0 行情信号更有效
        "pre_drift": 1.2,
        "fundamentals": 1.0,
        "event_subtype_prior": 1.8, # Rule 425 程序备案收购方历史跑输，高权重
        "sell_the_news": 1.5,       # 美股出尽效应比 A 股弱
    })
    if custom_weights:
        weights.update(custom_weights)

    # 注入子类型先验（Rule 425 = 收购方偏空，力度加强）
    if announcement_subtype and "event_subtype_prior" not in signals:
        prior_map = {
            "us_rule_425": ("down", 3),        # 收购方发 425，历史大概率跑输基准 → 强空
            "us_8k_material": ("up", 2),
            "first_disclosure": ("up", 2),
            "termination": ("down", 3),
            "completion": ("up", 1),
        }
        prior = prior_map.get(announcement_subtype, ("neutral", 0))
        signals["event_subtype_prior"] = {"direction": prior[0], "strength": prior[1]}

    scorecard = _compute_scorecard(signals, weights)
    scorecard["analyzer"] = "us_ma_analyzer"
    scorecard["market"] = "US"
    scorecard["event_type"] = "M&A"
    scorecard["weights_used"] = weights
    return ok(scorecard, meta("us_ma_analyzer", 1))


# ================================================================ Tier 2
# ====== volume_regime_analyzer ======
# 4 维量价特征计算 + 3 桶 vol_regime 分桶（RLVR 方案 §3.2.2）
# strict as-of T0：所有计算只用到事件日（T0）及 T0 以前的数据。
#
# 四维特征定义（按 Pronoia-RLVR v1 方案 §3.2.2 / §1.3）：
#   vol_t0_ratio           = T0 成交量 / 前 20 交易日均值
#   vol_pre5_ratio         = 前 5 日均量 / 前 20 日均量
#   price_vol_diverge      = 近 5 日日收益率 × 日成交量变化率 的符号均值；
#                            正→量价齐升/齐跌（共振）；负→背离
#   range_t0_normalized    = (T0 振幅 / T0 收) / 近 20 日均振幅倍数
#
# vol_regime 三桶（对应 §5.2 VOLUME 3 桶分桶 / §4.2 κ_vol）：
#   LOW    : vol_t0_ratio < 0.8  AND vol_pre5_ratio < 0.9
#   HIGH   : vol_t0_ratio > 1.5  OR  (vol_t0_ratio > 1.2 AND vol_pre5_ratio > 1.15)
#   NORMAL : 其余
#
# 两个调用入口：
#   compute_volume_regime(rows: list[dict], event_date)  —— 离线批处理，直接喂 K 线 dict 列表
#   volume_regime_analyzer(symbol, event_date)           —— 在线 Agent 用，内部调 get_stock_daily 查 K 线

def compute_volume_regime(rows: list[dict], event_date: str | None = None,
                          ) -> dict:
    """纯 Python 量价特征核心计算（离线批处理、在线 skill 都复用）。

    Args:
        rows: list[dict]，K 线按日期升序；每条必须至少含 date/close/volume；
              算 range_t0_normalized 时最好有 high/low，缺失用 (high≈low≈close) 兜底。
        event_date: "YYYY-MM-DD"。不传时把 rows 最后一条当 T0（离线构造数据时常用）。

    Returns:
        dict: 四维特征 + vol_regime 桶 + 诊断（T0 定位用了哪条、前 20/5 均值样本量等）。
    """
    import math

    if not isinstance(rows, list) or not rows:
        return {
            "vol_t0_ratio": None, "vol_pre5_ratio": None,
            "price_vol_diverge": None, "range_t0_normalized": None,
            "vol_regime": None, "ok": False,
            "reason": f"empty rows: type={type(rows).__name__} len={0 if rows is None else len(rows) if isinstance(rows, list) else 'n/a'}",
        }

    # 1. 按 date 排序，清理非数值字段
    cleaned: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            d_raw = r.get("date")
            if d_raw is None:
                continue
            d_str = str(d_raw)[:10]
            c = r.get("close"); v = r.get("volume")
            if c is None or v is None:
                continue
            cf = float(c); vf = float(v)
            if not (math.isfinite(cf) and math.isfinite(vf)) or cf <= 0 or vf < 0:
                continue
            h = r.get("high"); l = r.get("low")
            try: hf = float(h) if h is not None else cf
            except Exception: hf = cf
            try: lf = float(l) if l is not None else cf
            except Exception: lf = cf
            if not math.isfinite(hf): hf = cf
            if not math.isfinite(lf): lf = cf
            cleaned.append({"date": d_str, "close": cf, "volume": vf, "high": hf, "low": lf})
        except Exception:
            continue
    if not cleaned:
        return {
            "vol_t0_ratio": None, "vol_pre5_ratio": None,
            "price_vol_diverge": None, "range_t0_normalized": None,
            "vol_regime": None, "ok": False, "reason": "rows 清理后为空（缺 close/volume 或非有限数）",
        }
    cleaned.sort(key=lambda x: x["date"])

    # 2. 定位 T0（第一个 >= event_date 的交易日；不传 event_date 时 T0 = 最后一条）
    if event_date:
        ed = str(event_date)[:10]
        t0_idx = None
        for i, r in enumerate(cleaned):
            if r["date"] >= ed:
                t0_idx = i
                break
        if t0_idx is None:
            # event_date 晚于所有可用 K 线 → 放弃
            return {
                "vol_t0_ratio": None, "vol_pre5_ratio": None,
                "price_vol_diverge": None, "range_t0_normalized": None,
                "vol_regime": None, "ok": False,
                "reason": f"event_date={event_date} 晚于最晚可用 K 线日期 {cleaned[-1]['date']}",
            }
    else:
        t0_idx = len(cleaned) - 1
    t0_row = cleaned[t0_idx]

    # 3. 前 20 / 前 5 窗口（不含 T0 自己；strict as-of）
    pre20 = cleaned[max(0, t0_idx - 20):t0_idx]
    pre5  = cleaned[max(0, t0_idx -  5):t0_idx]
    n_pre20 = len(pre20); n_pre5 = len(pre5)
    if n_pre20 < 5:
        # 前向历史太少（上市初期、事件贴近样本起点），给中性值并写原因
        return {
            "vol_t0_ratio": 1.0, "vol_pre5_ratio": 1.0,
            "price_vol_diverge": 0.0, "range_t0_normalized": 1.0,
            "vol_regime": "NORMAL", "ok": True,
            "degraded": True,
            "reason": f"pre20 样本不足（仅 {n_pre20} < 5），所有量价维度中性兜底",
            "t0_date": t0_row["date"], "n_pre20": n_pre20, "n_pre5": n_pre5,
        }

    pre20_vol_avg = sum(r["volume"] for r in pre20) / n_pre20
    pre5_vol_avg  = (sum(r["volume"] for r in pre5) / n_pre5) if n_pre5 > 0 else pre20_vol_avg

    # 4. vol_t0_ratio & vol_pre5_ratio（保护除 0）
    if pre20_vol_avg > 0:
        vol_t0_ratio   = t0_row["volume"] / pre20_vol_avg
        vol_pre5_ratio = pre5_vol_avg / pre20_vol_avg
    else:
        vol_t0_ratio = 1.0; vol_pre5_ratio = 1.0

    # 5. price_vol_diverge：近 5 天（pre5 区间）的 日收益 × 日量变化率 符号平均
    #    正 → 量价同向（涨放量/跌缩量）；负 → 背离（涨缩量/跌放量）
    pvd_vals: list[float] = []
    if n_pre5 >= 2:
        # 基准：pre20 尾 10 条量（与 pre5 相邻）做变化率分母
        tail_ref = pre20[max(0, len(pre20) - 10):]
        ref_vol_avg = sum(r["volume"] for r in tail_ref) / len(tail_ref)
        # 用 pre5 内部相邻两天算收益、量变化率
        for i in range(1, len(pre5)):
            prev = pre5[i - 1]; cur = pre5[i]
            if prev["close"] <= 0: continue
            ret_i = (cur["close"] / prev["close"]) - 1.0
            if ref_vol_avg > 0:
                vol_chg_i = (cur["volume"] / ref_vol_avg) - 1.0
            else:
                vol_chg_i = 0.0
            sign_i = 1.0 if (ret_i * vol_chg_i) > 0 else (-1.0 if (ret_i * vol_chg_i) < 0 else 0.0)
            pvd_vals.append(sign_i)
    if pvd_vals:
        price_vol_diverge = round(sum(pvd_vals) / len(pvd_vals), 4)
    else:
        price_vol_diverge = 0.0  # 样本不足 → 中性

    # 6. range_t0_normalized = (振幅 / 收) / 近 20 日均 (振幅 / 收)
    t0_amp_pct = (t0_row["high"] - t0_row["low"]) / t0_row["close"] if t0_row["close"] > 0 else 0.0
    pre20_amp_pcts: list[float] = []
    for r in pre20:
        if r["close"] > 0:
            pre20_amp_pcts.append((r["high"] - r["low"]) / r["close"])
    if pre20_amp_pcts:
        amp_avg = sum(pre20_amp_pcts) / len(pre20_amp_pcts)
        range_t0_normalized = (t0_amp_pct / amp_avg) if amp_avg > 0 else 1.0
    else:
        range_t0_normalized = 1.0

    # 7. 3 桶分桶（严格对齐方案阈值）
    if vol_t0_ratio < 0.8 and vol_pre5_ratio < 0.9:
        vol_regime = "LOW"
    elif vol_t0_ratio > 1.5 or (vol_t0_ratio > 1.2 and vol_pre5_ratio > 1.15):
        vol_regime = "HIGH"
    else:
        vol_regime = "NORMAL"

    return {
        "ok": True,
        "vol_t0_ratio":        round(vol_t0_ratio, 4),
        "vol_pre5_ratio":      round(vol_pre5_ratio, 4),
        "price_vol_diverge":   round(price_vol_diverge, 4),
        "range_t0_normalized": round(range_t0_normalized, 4),
        "vol_regime":          vol_regime,
        "t0_date":             t0_row["date"],
        "n_pre20":             n_pre20,
        "n_pre5":              n_pre5,
        "pre20_vol_avg":       round(pre20_vol_avg, 2),
        "pre5_vol_avg":        round(pre5_vol_avg, 2),
        "t0_volume":           round(t0_row["volume"], 2),
        "t0_close":            round(t0_row["close"], 4),
    }


@skill(
    "volume_regime_analyzer",
    "【Pronoia-RLVR 新增 Tier 2 量价 skill】基于事件日 T0（strict as-of，严禁未来数据）"
    "输出 4 维量价特征 + 3 桶 vol_regime 分桶。"
    "四维：vol_t0_ratio（T0 量/前 20 均量）、vol_pre5_ratio（前 5 均量/前 20 均量）、"
    "price_vol_diverge（近 5 日量价背离符号均值，正=共振，负=背离）、"
    "range_t0_normalized（T0 振幅倍数）。三桶：LOW / NORMAL / HIGH。"
    "symbol 支持 6 位 A 股代码或美股 ticker；event_date=YYYY-MM-DD（事件日，必填）。"
    "无数据（美股缺失量、上市初期）时四维回中性兜底并返回 degraded=True，不影响上游流程。",
    {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "标的：A 股 6 位数字 或 美股 ticker（AAPL/NFLX）",
            },
            "event_date": {
                "type": "string",
                "description": "事件日 YYYY-MM-DD。定位 T0 后，只用 T0 及之前数据（strict as-of）",
            },
            "lookback_days": {
                "type": "integer",
                "description": "回溯日历天数（为了拿 20+交易日，默认 60）",
            },
        },
        "required": ["symbol", "event_date"],
        "additionalProperties": False,
    },
    category="skill",
    internal=False,
    composes=["get_stock_daily", "get_us_stock_spot"],
)
async def volume_regime_analyzer(symbol: str, event_date: str,
                                 lookback_days: int = 60) -> dict:
    from datetime import datetime, timedelta

    raw = (symbol or "").strip()
    if not raw:
        return err("symbol 不能为空")
    ed = (event_date or "").strip()[:10]
    if not ed:
        return err("event_date 不能为空")

    # ---- 解析 symbol 格式（复用 skill.py 里的 US / 6 位 分支） ----
    from .market import is_us_symbol

    us = is_us_symbol(raw)
    if us:
        sym = raw.upper()
        tasks: list[tuple[str, dict]] = [
            # 美股：yfinance 通常能给到 volume，但 get_us_stock_spot 是 spot，
            # 这里直接走 get_stock_daily 统一接口；skill.py 里 get_stock_daily
            # 对 us ticker 走 yfinance。
            ("get_stock_daily", {"symbol": sym,
                                 "start_date": (datetime.fromisoformat(ed) - timedelta(days=lookback_days)).strftime("%Y%m%d"),
                                 "end_date":   ed.replace("-", ""),
                                 "adjust": "qfq"}),
        ]
    else:
        code6 = "".join(ch for ch in raw if ch.isdigit())[-6:]
        if len(code6) != 6:
            return err(f"symbol 不合法: {symbol}")
        sym = code6
        tasks = [
            ("get_stock_daily", {"symbol": sym,
                                 "start_date": (datetime.fromisoformat(ed) - timedelta(days=lookback_days)).strftime("%Y%m%d"),
                                 "end_date":   ed.replace("-", ""),
                                 "adjust": "qfq"}),
        ]

    results = await _gather_sub(tasks)
    rows: list[dict] = []
    for r in results:
        if not isinstance(r, dict) or not r.get("ok"):
            continue
        d = r.get("data")
        if isinstance(d, list) and d:
            rows = d
            break

    feat = compute_volume_regime(rows, event_date=ed)
    if not feat.get("ok"):
        # 降级：返回但标 degraded，不 err 中断 agent（很多美股本来就没量）
        feat.setdefault("degraded", True)
        feat["t0_date"] = feat.get("t0_date") or ed
        feat["market"] = "美股" if us else "A股"
        feat["symbol"] = sym
        return ok(feat, meta("volume_regime_analyzer", 0),
                  artifacts=None)

    feat["market"] = "美股" if us else "A股"
    feat["symbol"] = sym
    # 人类可读一句话，方便 LLM 在 persona 里引用
    regime_to_human = {
        "LOW":    "放量不足（低于 20 日均量 80%），方向信号弱，neutral 惩罚放宽",
        "HIGH":   "显著放量，方向信号强，方向错惩罚翻倍",
        "NORMAL": "量能处于正常区间，按默认权重处理",
    }
    feat["interpretation"] = (
        f"事件日 T0={feat['t0_date']}；"
        f"T0 量 / 20 日均 = {feat['vol_t0_ratio']:.2f}×；"
        f"前 5 均量 / 20 均量 = {feat['vol_pre5_ratio']:.2f}×；"
        f"近 5 日量价共振/背离 = {feat['price_vol_diverge']:+.2f}（正=共振/负=背离）；"
        f"T0 振幅倍数 = {feat['range_t0_normalized']:.2f}× → "
        f"桶 {feat['vol_regime']}：{regime_to_human.get(feat['vol_regime'], '')}"
    )
    return ok(feat, meta("volume_regime_analyzer", len(rows)),
              artifacts=None)


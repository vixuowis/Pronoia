"""分析推理 skill 集成测试。

测试三个层面：
1. Tier 2 skill 功能测试（announcement_classifier, ar_decomposer, drift_context_analyzer）
2. Tier 1 skill 功能测试（cn_ma_analyzer, cn_earnings_analyzer, us_ma_analyzer）
3. Signal routing 集成测试（_route_signals 函数，从 findings+tool_trace → Tier 1 analyzer → scorecard）
4. roster 注册测试（event_scout/market_analyst/deep_researcher 的 skills 列表包含新 skill）
"""
import asyncio
import pytest

# === Tier 2 skill 功能测试 ===

class TestAnnouncementClassifier:
    """公告子类型分类器测试"""

    def test_cn_report_draft(self):
        """报告书/草案 → low info, prior=down"""
        from app.skills.analyzers import announcement_classifier
        result = asyncio.run(announcement_classifier(
            title="重大资产重组报告书暨风险提示公告",
            text="本报告书为披露文件",
            market="CN",
        ))
        assert result["ok"]
        d = result["data"]
        assert d["subtype"] == "report_draft"
        assert d["info_tier"] == "low"
        assert d["default_prior"] == "down"

    def test_cn_compliance_reply(self):
        """合规回复 → low info, prior=down"""
        from app.skills.analyzers import announcement_classifier
        result = asyncio.run(announcement_classifier(
            title="关于不构成重大资产重组的说明",
            text="经核查，本次交易不构成重组上市",
            market="CN",
        ))
        assert result["ok"]
        d = result["data"]
        assert d["info_tier"] == "low"

    def test_cn_termination(self):
        """终止/失败 → high info, prior=down"""
        from app.skills.analyzers import announcement_classifier
        result = asyncio.run(announcement_classifier(
            title="关于终止重大资产重组的公告",
            text="终止重组",
            market="CN",
        ))
        assert result["ok"]
        d = result["data"]
        assert d["subtype"] == "termination"
        assert d["info_tier"] == "high"
        assert d["default_prior"] == "down"

    def test_us_rule_425(self):
        """美股 Rule 425 → low info, prior=down"""
        from app.skills.analyzers import announcement_classifier
        result = asyncio.run(announcement_classifier(
            title="Rule 425 Filing",
            text="Securities Act Rule 425",
            market="US",
        ))
        assert result["ok"]
        d = result["data"]
        assert d["subtype"] == "us_rule_425"
        assert d["info_tier"] == "low"
        assert d["default_prior"] == "down"

    def test_unclassified(self):
        """未匹配 → unclassified"""
        from app.skills.analyzers import announcement_classifier
        result = asyncio.run(announcement_classifier(
            title="关于召开2025年第二次临时股东大会的通知",
            text="普通股东大会通知",
            market="CN",
        ))
        assert result["ok"]
        d = result["data"]
        assert d["subtype"] == "unclassified"

    def test_custom_rules(self):
        """自定义规则扩展"""
        from app.skills.analyzers import announcement_classifier
        custom = [{
            "subtype": "shareholder_meeting",
            "label": "股东大会",
            "patterns": [r"股东大会"],
            "info_tier": "low",
            "default_prior": "neutral",
        }]
        result = asyncio.run(announcement_classifier(
            title="关于召开2025年第二次临时股东大会的通知",
            market="CN",
            custom_rules=custom,
        ))
        assert result["ok"]
        assert result["data"]["subtype"] == "shareholder_meeting"


class TestARDecomposer:
    """T0 benchmark-relative AR 方向信号测试"""

    def test_passive_ar_nflx(self):
        """NFLX 虽只涨0.23%，但跑赢基准2.09% → relative up。"""
        from app.skills.analyzers import ar_decomposer
        result = asyncio.run(ar_decomposer(
            stock_return_pct=0.23, benchmark_return_pct=-1.86,
        ))
        assert result["ok"]
        d = result["data"]
        assert d["ar_pct"] == pytest.approx(2.09, abs=0.01)
        assert d["relative_return_pct"] == pytest.approx(2.09, abs=0.01)
        assert d["signal_valid"] is True
        assert d["signal_direction"] == "up"
        assert d["active_direction"] == "up"

    def test_active_ar_huanlan(self):
        """P06 瀚蓝环境: 主动收益=-3.02% → signal_valid=True, direction=down"""
        from app.skills.analyzers import ar_decomposer
        result = asyncio.run(ar_decomposer(
            stock_return_pct=-3.02, benchmark_return_pct=2.39,
        ))
        assert result["ok"]
        d = result["data"]
        assert d["relative_return_pct"] == pytest.approx(-5.41, abs=0.01)
        assert d["signal_valid"] is True
        assert d["signal_direction"] == "down"

    def test_strong_up_signal(self):
        """强 up 主动收益"""
        from app.skills.analyzers import ar_decomposer
        result = asyncio.run(ar_decomposer(
            stock_return_pct=5.67, benchmark_return_pct=-0.65,
        ))
        assert result["ok"]
        d = result["data"]
        assert d["signal_direction"] == "up"
        assert d["signal_valid"] is True

    def test_absolute_up_but_relative_down(self):
        """个股上涨但跑输基准时，benchmark-relative 方向必须为 down。"""
        from app.skills.analyzers import ar_decomposer
        result = asyncio.run(ar_decomposer(
            stock_return_pct=0.8, benchmark_return_pct=1.5,
        ))
        assert result["ok"]
        d = result["data"]
        assert d["relative_return_pct"] == pytest.approx(-0.7, abs=0.01)
        assert d["signal_valid"] is True
        assert d["signal_direction"] == "down"


class TestDriftContextAnalyzer:
    """事前漂移+出尽系数测试"""

    def test_sell_the_news_amzn(self):
        """N02 AMZN: pre5=+12.74%, pre20=+14.23% → 出尽系数>1, triggered=True"""
        from app.skills.analyzers import drift_context_analyzer
        result = asyncio.run(drift_context_analyzer(
            pre5_pct=12.74, pre20_pct=14.23,
        ))
        assert result["ok"]
        d = result["data"]
        assert d["pre5_score"] == 4
        assert d["pre20_score"] == 4
        assert d["sell_the_news_triggered"] is True
        assert d["sell_the_news_direction"] == "down"
        assert d["sell_the_news_coefficient"] > 1.0

    def test_no_sell_the_news(self):
        """小幅漂移不触发出尽"""
        from app.skills.analyzers import drift_context_analyzer
        result = asyncio.run(drift_context_analyzer(
            pre5_pct=1.2, pre20_pct=2.5,
        ))
        assert result["ok"]
        d = result["data"]
        assert d["sell_the_news_triggered"] is False
        assert d["pre5_score"] == 1
        assert d["pre20_score"] == 2

    def test_custom_thresholds(self):
        """自定义阈值（泛化性）。

        当前实现使用左闭右开区间：
          [<small)              -> 1
          [small, medium)       -> 2
          [medium, large)       -> 3
          [large, +)            -> 4
        所以 pre5=3.0, small=1, medium=3, large=6 → 落在 [medium, large) → 3
        pre20=6.0, large=6 → 落在 [large, +) → 4
        """
        from app.skills.analyzers import drift_context_analyzer
        result = asyncio.run(drift_context_analyzer(
            pre5_pct=3.0, pre20_pct=6.0,
            thresholds={"small": 1.0, "medium": 3.0, "large": 6.0},
        ))
        assert result["ok"]
        d = result["data"]
        assert d["pre5_score"] == 3  # 3.0 在 [medium=3, large=6) 区间
        assert d["pre20_score"] == 4  # 6.0 >= large=6 → 第4档


# === Tier 1 skill 功能测试 ===

class TestCNMAAnalyzer:
    """A 股并购分析思维测试"""

    def test_st_jinggu_case(self):
        """N04 *ST 景谷: 出尽信号+报告书先验压低 net_score"""
        from app.skills.analyzers import cn_ma_analyzer
        signals = {
            "announcement_text": {"direction": "up", "strength": 2},
            "t0_active_return": {"direction": "up", "strength": 3},
            "pre_drift": {"direction": "up", "strength": 1},
            "fundamentals": {"direction": "up", "strength": 2},
            "sell_the_news": {"direction": "down", "strength": 2},
        }
        result = asyncio.run(cn_ma_analyzer(
            signals=signals,
            announcement_subtype="report_draft",
            announcement_info_tier="low",
        ))
        assert result["ok"]
        d = result["data"]
        # 出尽信号(weight=2.5) + 报告书先验(weight=1.0, down strength=2)
        # 应该把 net_score 从纯 up 信号的 ~8.9 压到更低
        assert d["net_score"] < 3.0  # 大幅压缩
        assert d["analyzer"] == "cn_ma_analyzer"

    def test_termination_prior(self):
        """终止类先验注入"""
        from app.skills.analyzers import cn_ma_analyzer
        signals = {
            "announcement_text": {"direction": "neutral", "strength": 0},
        }
        result = asyncio.run(cn_ma_analyzer(
            signals=signals,
            announcement_subtype="termination",
        ))
        assert result["ok"]
        d = result["data"]
        # termination 先验 = (down, 3)
        assert d["direction"] == "down"

    def test_custom_weights(self):
        """自定义权重覆盖（泛化性）"""
        from app.skills.analyzers import cn_ma_analyzer
        signals = {
            "announcement_text": {"direction": "up", "strength": 2},
        }
        result = asyncio.run(cn_ma_analyzer(
            signals=signals,
            custom_weights={"announcement_text": 5.0},
        ))
        assert result["ok"]
        d = result["data"]
        # announcement_text weight=5.0, strength=2 → contribution=10
        assert d["net_score"] == pytest.approx(10.0, abs=0.1)


class TestCNEarningsAnalyzer:
    """A 股财报分析思维测试"""

    def test_zhongshi_tech_case(self):
        """N08 中石科技: +90% 同比增速 → fundamentals up strength=3, weight=2.5"""
        from app.skills.analyzers import cn_earnings_analyzer
        signals = {
            "announcement_text": {"direction": "up", "strength": 1},
            "t0_active_return": {"direction": "down", "strength": 2},
            "pre_drift": {"direction": "down", "strength": 1},
            "sell_the_news": {"direction": "down", "strength": 2},
        }
        result = asyncio.run(cn_earnings_analyzer(
            signals=signals, yoy_growth_pct=90.0,
        ))
        assert result["ok"]
        d = result["data"]
        # fundamentals: up, strength=3, weight=2.5 → contribution=7.5
        # 其他 down 信号 total: -1.6-1.0-3.0 = -5.6
        # net = 2.0*2.0 + 7.5 - 5.6 = 4.0 + 7.5 - 5.6 = 5.9
        assert d["direction"] == "up"  # 基本面压过 T0
        assert d["confidence"] > 0.55

    def test_yoy_auto_signal(self):
        """同比增速自动注入 fundamentals 信号"""
        from app.skills.analyzers import cn_earnings_analyzer
        signals = {}
        result = asyncio.run(cn_earnings_analyzer(
            signals=signals, yoy_growth_pct=-50.0,
        ))
        assert result["ok"]
        d = result["data"]
        assert d["direction"] == "down"  # -50% → down strength=3


class TestUSMAAnalyzer:
    """美股并购分析思维测试"""

    def test_rule425_prior(self):
        """Rule 425 先验注入"""
        from app.skills.analyzers import us_ma_analyzer
        signals = {
            "announcement_text": {"direction": "neutral", "strength": 0},
        }
        result = asyncio.run(us_ma_analyzer(
            signals=signals,
            announcement_subtype="us_rule_425",
        ))
        assert result["ok"]
        d = result["data"]
        # us_rule_425 先验 = (down, 2), weight=0.8
        assert d["direction"] == "down"

    def test_8k_material_prior(self):
        """8-K 实质协议先验注入"""
        from app.skills.analyzers import us_ma_analyzer
        signals = {
            "announcement_text": {"direction": "neutral", "strength": 0},
        }
        result = asyncio.run(us_ma_analyzer(
            signals=signals,
            announcement_subtype="us_8k_material",
        ))
        assert result["ok"]
        d = result["data"]
        assert d["direction"] == "up"


# === Signal routing 集成测试 ===

class TestSignalRouting:
    """信号路由集成测试"""

    def test_route_cn_ma_with_findings(self):
        """从 findings 文本提取信号 → cn_ma_analyzer"""
        from app.agents.team import _route_signals
        event_meta = {
            "market": "CN",
            "event_type_l2": "并购/分拆/再融资",
            "title": "重大资产重组报告书暨风险提示公告",
            "event_text": "本报告书为披露文件",
        }
        findings = {
            "market_analyst": "T0 个股跌3.02%，基准涨2.39%。pre5 +24.93%，pre20 +53.49%。",
            "fundamentals_analyst": "连续亏损，2025年归母净利-2929万。",
        }
        tool_trace = []
        result = asyncio.run(_route_signals(event_meta, findings, tool_trace))
        assert result is not None
        assert result["analyzer"] == "cn_ma_analyzer"
        # 应该有出尽信号和基本面信号
        assert "sell_the_news" in result.get("signals_extracted", [])
        assert "fundamentals" in result.get("signals_extracted", [])

    def test_route_cn_earnings_with_tool_trace(self):
        """从 tool_trace 提取 Tier 2 调用 → cn_earnings_analyzer"""
        from app.agents.team import _route_signals
        event_meta = {
            "market": "CN",
            "event_type_l2": "财报超预期/不及预期",
            "title": "2025年前三季度业绩预告",
            "event_text": "预计归母净利2.5亿，同比+90%",
        }
        findings = {
            "fundamentals_analyst": "业绩预增，同比+90%。",
        }
        # 模拟 tool_trace 中有 ar_decomposer 调用
        tool_trace = [
            {"type": "tool", "skill": "ar_decomposer",
             "args": {"stock_return_pct": -2.37, "benchmark_return_pct": -0.50},
             "preview": "active=-2.37%, signal_valid=True", "ok": True},
        ]
        result = asyncio.run(_route_signals(event_meta, findings, tool_trace))
        assert result is not None
        assert result["analyzer"] == "cn_earnings_analyzer"
        assert "t0_active_return" in result.get("signals_extracted", [])
        assert "fundamentals" in result.get("signals_extracted", [])

    def test_route_us_ma(self):
        """美股并购路由"""
        from app.agents.team import _route_signals
        event_meta = {
            "market": "US",
            "event_type_l2": "并购/分拆/再融资",
            "title": "Rule 425 Filing",
            "event_text": "Securities Act Rule 425",
        }
        findings = {
            "market_analyst": "T0 个股涨0.23%，基准跌1.86%。pre5 -2.21%，pre20 -14.03%。",
        }
        tool_trace = []
        result = asyncio.run(_route_signals(event_meta, findings, tool_trace))
        assert result is not None
        assert result["analyzer"] == "us_ma_analyzer"

    def test_route_no_analyzer_match(self):
        """不支持的 market×event_type → 返回 None"""
        from app.agents.team import _route_signals
        event_meta = {
            "market": "HK",
            "event_type_l2": "其他",
        }
        result = asyncio.run(_route_signals(event_meta, {}, []))
        assert result is None

    def test_route_no_event_meta(self):
        """无 event_meta → 返回 None"""
        from app.agents.team import _route_signals
        result = asyncio.run(_route_signals(None, {}, []))
        assert result is None


# === Roster 注册测试 ===

class TestRosterRegistration:
    """验证新 skill 已注册到 agent rosters"""

    def test_event_scout_has_announcement_classifier(self):
        from app.agents.roster import AGENTS
        skills = AGENTS["event_scout"]["skills"]
        assert "announcement_classifier" in skills

    def test_market_analyst_has_tier2(self):
        from app.agents.roster import AGENTS
        skills = AGENTS["market_analyst"]["skills"]
        assert "ar_decomposer" in skills
        assert "drift_context_analyzer" in skills

    def test_deep_researcher_has_all_tier2(self):
        from app.agents.roster import AGENTS
        skills = AGENTS["deep_researcher"]["skills"]
        assert "announcement_classifier" in skills
        assert "ar_decomposer" in skills
        assert "drift_context_analyzer" in skills

    def test_all_skills_in_registry(self):
        """所有新 skill 已注册到 REGISTRY"""
        from app.skills.analyzers import (
            announcement_classifier, ar_decomposer, drift_context_analyzer,
            cn_ma_analyzer, cn_earnings_analyzer, us_ma_analyzer,
        )
        from app.skills.registry import REGISTRY
        for name in ["announcement_classifier", "ar_decomposer",
                      "drift_context_analyzer", "cn_ma_analyzer",
                      "cn_earnings_analyzer", "us_ma_analyzer"]:
            assert name in REGISTRY, f"{name} not in REGISTRY"

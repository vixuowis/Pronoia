import unittest

from backend.app.agents.evidence_navigator import EvidenceNavigator
from backend.app.skills.evidence_graph import EvidenceGraph


class TestEvidenceNavigator(unittest.TestCase):
    def test_prioritizes_explicit_high_priority_missing(self):
        graph = EvidenceGraph(question="q")
        claim_id = graph.add_claim("推断：市场预期存在分歧", status="needs_more")
        graph.add_missing("财务盈利质量", "缺少最新季度利润与现金流", priority=5)

        decision = EvidenceNavigator(max_dispatches=1).plan(graph)

        self.assertEqual(decision.action, "dispatch")
        self.assertEqual(len(decision.dispatches), 1)
        task = decision.dispatches[0]
        self.assertEqual(task.target_kind, "missing")
        self.assertIn("financial_research", task.allowed_skills)
        self.assertIn(claim_id, {item["id"] for item in graph.audit()["claims_without_substantive_evidence"]})

    def test_unverified_claim_dispatches_targeted_verification(self):
        graph = EvidenceGraph(question="q")
        claim_id = graph.add_claim("推断：近期股价反应已计入市场预期", status="needs_more")

        decision = EvidenceNavigator(max_dispatches=1).plan(graph)

        self.assertEqual(decision.action, "dispatch")
        task = decision.dispatches[0]
        self.assertEqual(task.target_id, claim_id)
        self.assertEqual(task.target_kind, "claim_unverified")
        self.assertIn("market_research", task.allowed_skills)
        self.assertIn("只允许调用一次数据 Skill", task.task)

    def test_conflict_is_resolved_before_other_unverified_claims(self):
        graph = EvidenceGraph(question="q")
        conflict_id = graph.add_claim("推断：政策事件对收入有正面影响", status="needs_more")
        other_id = graph.add_claim("推断：估值仍有上行空间", status="needs_more")
        support_id = graph.add_evidence("source", "s1", "支持", "支持该判断")
        contradict_id = graph.add_evidence("source", "s2", "反驳", "反驳该判断")
        graph.link(conflict_id, support_id, "supports", "正向证据")
        graph.link(conflict_id, contradict_id, "contradicts", "反向证据")

        decision = EvidenceNavigator(max_dispatches=1).plan(graph)

        self.assertEqual(decision.action, "dispatch")
        self.assertEqual(decision.dispatches[0].target_id, conflict_id)
        self.assertEqual(decision.dispatches[0].target_kind, "claim_conflict")
        self.assertNotEqual(decision.dispatches[0].target_id, other_id)

    def test_stops_when_graph_is_sufficient(self):
        graph = EvidenceGraph(question="q")
        graph.set_sufficient(True, "核心结论已有交叉验证")

        decision = EvidenceNavigator().plan(graph)

        self.assertEqual(decision.action, "stop")
        self.assertFalse(decision.dispatches)


if __name__ == "__main__":
    unittest.main()

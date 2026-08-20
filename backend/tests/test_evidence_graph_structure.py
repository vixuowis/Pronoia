from __future__ import annotations

import unittest

from backend.app.skills.evidence_graph import EvidenceGraph, check_claim_title


class TestEvidenceGraphStructure(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = EvidenceGraph(question="test")
        self.evidence_id = self.graph.add_evidence("test", "source", "事实锚点", "数值资料")
        self.claim_id = self.graph.add_claim("推断：利润弹性承压")
        self.missing_id = self.graph.add_missing("订单数据", "缺少订单金额")

    def test_claim_to_evidence_relations_are_allowed(self):
        edge = self.graph.link(self.claim_id, self.evidence_id, "supports", "支持利润比较")
        self.assertEqual(edge, f"{self.claim_id}--supports-->{self.evidence_id}")

    def test_evidence_to_missing_addresses_is_allowed(self):
        edge = self.graph.link(self.evidence_id, self.missing_id, "addresses", "补足订单缺口")
        self.assertEqual(edge, f"{self.evidence_id}--addresses-->{self.missing_id}")

    def test_invalid_relation_endpoint_types_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "claim → evidence"):
            self.graph.link(self.evidence_id, self.claim_id, "supports")
        with self.assertRaisesRegex(ValueError, "evidence → missing"):
            self.graph.link(self.claim_id, self.missing_id, "addresses")

    def test_audit_reports_expected_coverage_and_edge_quality_gaps(self):
        context_claim = self.graph.add_claim("推断：行业环境仍需观察")
        orphan_claim = self.graph.add_claim("推断：订单表现或将改善")
        duplicate_claim = self.graph.add_claim("推断：利润弹性承压")
        self.graph.link(context_claim, self.evidence_id, "context", "行业背景")
        self.graph.link(duplicate_claim, self.evidence_id, "supports")
        self.graph.link(duplicate_claim, self.evidence_id, "supports")

        audit = self.graph.audit()
        self.assertEqual(
            {x["id"] for x in audit["claims_without_substantive_evidence"]},
            {self.claim_id, context_claim, orphan_claim},
        )
        self.assertEqual(
            {x["id"] for x in audit["context_only_claims"]}, {context_claim},
        )
        self.assertEqual(
            {x["id"] for x in audit["unaddressed_missing"]}, {self.missing_id},
        )
        self.assertEqual(audit["duplicate_edges"][0]["count"], 2)
        self.assertEqual(len(audit["edges_missing_note"]), 2)

    def test_audit_reports_orphan_evidence_and_export_includes_audit(self):
        orphan_evidence = self.graph.add_evidence("test", "unused", "未连接资料", "资料摘要")
        payload = self.graph.to_payload()
        self.assertEqual(
            {x["id"] for x in payload["audit"]["orphan_evidence"]},
            {self.evidence_id, orphan_evidence},
        )
        self.assertIn("图谱自检（待处理）", payload["markdown"])

    def test_merge_requires_claim_nodes_and_deduplicates_rewired_edges(self):
        duplicate_claim = self.graph.add_claim("推断：利润弹性仍承压")
        self.graph.link(self.claim_id, self.evidence_id, "supports", "利润率下降")
        self.graph.link(duplicate_claim, self.evidence_id, "supports", "同一事实支持")

        with self.assertRaisesRegex(ValueError, "keep_id 必须是 claim"):
            self.graph.merge_claims(self.evidence_id, [], "不应允许")
        with self.assertRaisesRegex(ValueError, "merge_id 必须是 claim"):
            self.graph.merge_claims(self.claim_id, [self.missing_id], "不应允许")

        self.graph.merge_claims(self.claim_id, [duplicate_claim], "推断：利润弹性承压")
        self.assertEqual(len(self.graph.nodes), 3)
        supports = [e for e in self.graph.edges if e.relation == "supports"]
        self.assertEqual(len(supports), 1)
        self.assertEqual(supports[0].note, "利润率下降")

    def test_claim_title_check_warns_without_rejecting(self):
        result = check_claim_title(
            "推断：2026Q1营收增长9.3%、利润增长0.9%；股价可能继续承压。"
        )
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertGreater(result["length"], 0)
        self.assertIn("title_numeric_overload", codes)
        self.assertIn("title_multiple_sentences", codes)

    def test_reporting_period_and_final_stop_do_not_trigger_bulky_warnings(self):
        result = check_claim_title("推断：2026Q1利润弹性仍然承压。")
        self.assertEqual(result["warnings"], [])

    def test_title_length_and_rationale_marker_are_reported(self):
        result = check_claim_title(
            "推断：事实：一季度收入增长但利润率下降，且行业需求仍有不确定性，需要继续观察后续订单、现金流与利润率能否在下半年持续改善"
        )
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertIn("title_too_long", codes)
        self.assertIn("title_contains_rationale", codes)

    def test_short_atomic_claim_title_has_no_warning(self):
        result = check_claim_title("推断：收入增长尚未转化为利润弹性")
        self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()

"""Graph-level gap selection for team research.

This is the bounded, non-trained first version of an Argus-style Navigator.
It never invents evidence or answers the research question itself: it observes
the shared evidence graph, selects the highest-value unresolved gap, and asks a
single bounded follow-up Searcher to address it.  The follow-up works on the
same graph, so any new evidence can be linked back to the original Claim or
Missing node rather than becoming another isolated research trace.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..skills.evidence_graph import EvidenceGraph


@dataclass(frozen=True)
class NavigatorDispatch:
    """One targeted verification request derived from the graph state."""

    target_id: str
    target_kind: str
    reason: str
    task: str
    allowed_skills: tuple[str, ...]
    priority: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NavigatorDecision:
    action: str  # "dispatch" | "stop"
    reason: str
    audit_summary: dict[str, int]
    dispatches: tuple[NavigatorDispatch, ...] = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["dispatches"] = [item.to_dict() for item in self.dispatches]
        return payload


class EvidenceNavigator:
    """Select evidence gaps in global priority order, under a fixed budget.

    Missing nodes are explicit requests left by the researcher and therefore
    have highest priority.  Next come conflicting claims and claims that have
    no substantive support/contradiction edge.  Purely cosmetic audit findings
    (for example an edge without a note) are deliberately not dispatched to an
    external data source.
    """

    def __init__(self, *, max_dispatches: int = 1) -> None:
        self.max_dispatches = max(1, int(max_dispatches or 1))

    @staticmethod
    def _skills_for(text: str) -> tuple[str, ...]:
        value = str(text or "").lower()
        if any(word in value for word in ("财务", "业绩", "盈利", "营收", "利润", "负债", "股东", "估值")):
            return ("financial_research", "holder_research", "evidence_graph")
        if any(word in value for word in ("行情", "价格", "股价", "资金", "成交", "估值", "波动", "收益", "技术")):
            return ("market_research", "event_study_skill", "evidence_graph")
        if any(word in value for word in ("宏观", "政策", "利率", "汇率", "行业")):
            return ("macro_intel", "news_intel", "evidence_graph")
        return ("news_intel", "stock_overview", "evidence_graph")

    @staticmethod
    def _conflicted_claim_ids(graph: EvidenceGraph) -> set[str]:
        by_claim: dict[str, set[str]] = {}
        for edge in graph.edges:
            if edge.relation in {"supports", "contradicts"}:
                by_claim.setdefault(edge.src, set()).add(edge.relation)
        return {claim_id for claim_id, relations in by_claim.items()
                if {"supports", "contradicts"}.issubset(relations)}

    def plan(self, graph: EvidenceGraph) -> NavigatorDecision:
        audit = graph.audit()
        summary = dict(audit.get("summary") or {})
        if graph.sufficient:
            return NavigatorDecision("stop", "图谱已标记为充分", summary)

        nodes = {node.id: node for node in graph.nodes}
        candidates: list[NavigatorDispatch] = []

        # Explicit missing nodes encode a researcher-authored research gap.
        for item in audit.get("unaddressed_missing") or []:
            node = nodes.get(str(item.get("id") or ""))
            if node is None:
                continue
            focus = f"{node.title} {node.body}".strip()
            candidates.append(NavigatorDispatch(
                target_id=node.id,
                target_kind="missing",
                reason="高优先级 Missing 尚未被任何新证据 addresses",
                task=(
                    "【Evidence Navigator 定向补证】只处理图谱中的 Missing "
                    f"{node.id}：{node.title}。缺口说明：{node.body or '未说明'}。\n"
                    "只允许调用一次数据 Skill；得到结果后立即写入 evidence_graph，"
                    "并用 evidence → missing 的 addresses 边说明它补足了什么。"
                    "不要扩展到无关研究面；若资料仍不足，保留 Missing 并明确限制。"
                ),
                allowed_skills=self._skills_for(focus),
                priority=300 + int(node.priority or 1),
            ))

        conflicted = self._conflicted_claim_ids(graph)
        for claim_id in conflicted:
            node = nodes.get(claim_id)
            if node is None:
                continue
            candidates.append(NavigatorDispatch(
                target_id=node.id,
                target_kind="claim_conflict",
                reason="Claim 同时存在 supports 与 contradicts，需补权威证据裁决",
                task=(
                    "【Evidence Navigator 定向补证】只处理存在冲突的 Claim "
                    f"{node.id}：{node.title}。\n"
                    "只允许调用一次数据 Skill，优先原始公告、财报或权威行情来源。"
                    "将新资料写入 evidence_graph；只有资料直接支持或削弱该 Claim 时，"
                    "才建立 supports/contradicts 边并更新 Claim 状态。"
                ),
                allowed_skills=self._skills_for(f"{node.title} {node.body}"),
                priority=200,
            ))

        for item in audit.get("claims_without_substantive_evidence") or []:
            node = nodes.get(str(item.get("id") or ""))
            if node is None or node.id in conflicted:
                continue
            candidates.append(NavigatorDispatch(
                target_id=node.id,
                target_kind="claim_unverified",
                reason="Claim 缺少 supports/contradicts 实质证据",
                task=(
                    "【Evidence Navigator 定向补证】只验证图谱中的 Claim "
                    f"{node.id}：{node.title}。\n"
                    "只允许调用一次数据 Skill，寻找独立的支持或反驳证据。"
                    "把新资料写入 evidence_graph；仅当资料直接相关时建立 "
                    "Claim → Evidence 的 supports/contradicts 边，否则保留 needs_more。"
                ),
                allowed_skills=self._skills_for(f"{node.title} {node.body}"),
                priority=100,
            ))

        # A target may appear in more than one audit category; keep its best task.
        best_by_target: dict[str, NavigatorDispatch] = {}
        for candidate in candidates:
            previous = best_by_target.get(candidate.target_id)
            if previous is None or candidate.priority > previous.priority:
                best_by_target[candidate.target_id] = candidate
        selected = sorted(best_by_target.values(), key=lambda item: (-item.priority, item.target_id))
        selected = selected[:self.max_dispatches]
        if not selected:
            return NavigatorDecision(
                "stop",
                "没有可通过定向外部补证解决的关键图谱缺口",
                summary,
            )
        return NavigatorDecision(
            "dispatch",
            f"围绕 {len(selected)} 个最高优先级图谱缺口补证",
            summary,
            tuple(selected),
        )

    @staticmethod
    def compact_context(graph: EvidenceGraph, *, max_chars: int = 5000) -> str:
        """Give a follow-up Searcher the graph state without replaying its full question."""
        counts = graph._counts()
        lines = [
            "当前共享证据图（仅供定向补证；不要重做整题）：",
            f"统计：evidence={counts['n_evidence']} claim={counts['n_claim']} "
            f"missing={counts['n_missing']} edges={counts['n_edges']}",
        ]
        for node in graph.nodes:
            if node.kind == "claim":
                lines.append(f"Claim {node.id} [{node.status}]：{node.title}；{node.body[:500]}")
            elif node.kind == "missing":
                lines.append(f"Missing {node.id} [prio {node.priority}]：{node.title}；{node.body[:500]}")
            elif node.kind == "evidence":
                lines.append(f"Evidence {node.id}：{node.title}；{node.body[:350]}")
        for edge in graph.edges:
            lines.append(f"Edge {edge.src} -{edge.relation}-> {edge.dst}：{edge.note[:160]}")
        return "\n".join(lines)[:max_chars]

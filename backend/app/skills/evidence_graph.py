"""证据图 (Evidence Graph) 操作技能 —— 三层模型下唯一的「图」层 Skill。

设计要点
========

1. 状态通过 `ContextVar` 持有 —— 团队编排层 (`team.py`) 在调用 deep_researcher
   agent 前用 `eg_attach(graph)` 绑定一张新图，run 结束自动 detach。
   这样图状态能在 deep_researcher agent 多次 tool call 之间持久化，
   而无需在 `run_agent` 或 skill schema 上动外科手术。

2. 暴露给 LLM 的只有一个 **skill** ``evidence_graph``，由它 dispatcher
   到 9 个 ``_eg_*`` sub-tool（internal=True，LLM 不可见）：
   - _eg_add_evidence   —— 添加 evidence 节点（来源 = skill 返回的数据）
   - _eg_add_claim      —— 添加 claim 节点（可证伪陈述）
   - _eg_link           —— 把 claim 链到 evidence（supports/contradicts/context）
   - _eg_set_claim_status —— 修改 claim 状态
   - _eg_merge_claims   —— 合并重复 claim
   - _eg_add_missing    —— 记录尚未覆盖的研究面（用于下一轮 follow-up）
   - _eg_set_sufficient —— 标记图已充分（终止信号）
   - _eg_export         —— 导出图（默认 markdown 摘要 + JSON）
   - _eg_clear          —— 重置图（保留 question/scope，清空节点）

3. 图同时作为产出物 (artifact kind='graph') 落库，payload 含：
   {nodes, edges, missing, sufficient, stats, markdown}
   前端用现有 markdown 渲染或 DataTable 即可呈现；未来可换专用 GraphView。

4. deep_researcher agent 自身也是「消费者」——它会先调 skill 拿数据，
   再调 evidence_graph(action="add_evidence") 把结果塞进图。所以 deep_researcher
   的 skills 列表 = 一组数据 skill + 一个 evidence_graph skill。
"""
from __future__ import annotations

import contextvars
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from .registry import err, meta, ok, skill

# ---------------------------------------------------------------- state ---

_CURRENT_GRAPH: contextvars.ContextVar[Optional["EvidenceGraph"]] = contextvars.ContextVar(
    "evidence_graph_var", default=None
)
_DEFER_EXPORT_ARTIFACT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "evidence_graph_defer_export_artifact", default=False
)


def eg_attach(graph: "EvidenceGraph") -> contextvars.Token:
    """绑定一张新图到当前 async 上下文。返回 token，配合 eg_detach 释放。"""
    return _CURRENT_GRAPH.set(graph)


def eg_detach(token: contextvars.Token) -> None:
    _CURRENT_GRAPH.reset(token)


def eg_defer_export_artifact(enabled: bool = True) -> contextvars.Token:
    """Temporarily keep ``export`` as a graph snapshot, not a persisted artifact.

    Team-mode Evidence Navigator may execute more than one graph-editing pass.
    Deferring intermediate exports avoids persisting stale duplicate graph
    artifacts; the orchestration layer persists one final snapshot instead.
    """
    return _DEFER_EXPORT_ARTIFACT.set(bool(enabled))


def eg_restore_export_artifact(token: contextvars.Token) -> None:
    _DEFER_EXPORT_ARTIFACT.reset(token)


def get_current_graph() -> Optional["EvidenceGraph"]:
    return _CURRENT_GRAPH.get()


def _current_or_none() -> Optional["EvidenceGraph"]:
    return _CURRENT_GRAPH.get()


def _require_graph() -> "EvidenceGraph":
    g = _CURRENT_GRAPH.get()
    if g is None:
        raise ValueError("当前没有 attach 证据图；请团队编排层在 deep_researcher agent 启动前 eg_attach(EvidenceGraph(...))")
    return g


# ------------------------------------------------------------- dataclass ---

VALID_CLAIM_STATUS = {"exploring", "verified", "rejected", "needs_more", "insufficient"}
VALID_RELATIONS = {"supports", "contradicts", "context", "addresses"}
RELATION_ENDPOINT_KINDS: dict[str, tuple[str, str]] = {
    "supports": ("claim", "evidence"),
    "contradicts": ("claim", "evidence"),
    "context": ("claim", "evidence"),
    "addresses": ("evidence", "missing"),
}
CLAIM_TITLE_SOFT_MAX_LENGTH = 50


def check_claim_title(title: str) -> dict:
    """对 Claim 标题做非阻断式质量检查。"""
    compact = "".join(str(title or "").split())
    warnings: list[dict[str, str]] = []
    if len(compact) > CLAIM_TITLE_SOFT_MAX_LENGTH:
        warnings.append({
            "code": "title_too_long",
            "message": f"Claim 标题为 {len(compact)} 字，建议控制在 {CLAIM_TITLE_SOFT_MAX_LENGTH} 字以内。",
        })
    if any(marker in compact for marker in ("事实：", "比较：", "反方/限制：", "验证条件：")):
        warnings.append({
            "code": "title_contains_rationale",
            "message": "Claim 标题含有 rationale 段落标记，应只保留一个原子化推断。",
        })
    title_without_time_labels = re.sub(
        r"(?:19|20)\d{2}(?:[-/.]\d{1,2}(?:[-/.]\d{1,2})?|[Qq][1-4])?",
        "",
        compact,
    )
    if len(re.findall(r"\d+(?:\.\d+)?", title_without_time_labels)) >= 2:
        warnings.append({
            "code": "title_numeric_overload",
            "message": "Claim 标题包含多个数字；建议移入 rationale 或 Evidence。",
        })
    if "；" in compact or compact.count("。") >= 2:
        warnings.append({
            "code": "title_multiple_sentences",
            "message": "Claim 标题含多个分句；检查是否应拆成独立 Claim。",
        })
    return {"length": len(compact), "soft_max_length": CLAIM_TITLE_SOFT_MAX_LENGTH, "warnings": warnings}


@dataclass
class EvidenceNode:
    id: str
    kind: str  # "evidence" | "claim" | "missing"
    title: str
    body: str = ""
    status: str = "exploring"      # claim 专属: exploring/verified/rejected/needs_more/insufficient
    confidence: float = 0.5        # 0..1
    source_kind: str = ""          # evidence 专属: "akshare" | "external" | "inference"
    source_ref: str = ""           # evidence 专属: 源 URL 或 "akshare.skill_name(args)"
    source_data: dict = field(default_factory=dict)  # evidence 专属: 原始数据摘要
    priority: int = 1              # missing 专属
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceEdge:
    src: str
    dst: str
    relation: str  # supports/contradicts/context/addresses
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceGraph:
    question: str
    scope: str = ""
    nodes: list[EvidenceNode] = field(default_factory=list)
    edges: list[EvidenceEdge] = field(default_factory=list)
    sufficient: bool = False
    stop_reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    # ---- counters --------------------------------------------------------

    def _counts(self) -> dict:
        n_evidence = sum(1 for n in self.nodes if n.kind == "evidence")
        n_claim = sum(1 for n in self.nodes if n.kind == "claim")
        n_missing = sum(1 for n in self.nodes if n.kind == "missing")
        n_supports = sum(1 for e in self.edges if e.relation == "supports")
        n_contradicts = sum(1 for e in self.edges if e.relation == "contradicts")
        claim_status_breakdown: dict[str, int] = {}
        for n in self.nodes:
            if n.kind == "claim":
                claim_status_breakdown[n.status] = claim_status_breakdown.get(n.status, 0) + 1
        return {
            "n_evidence": n_evidence,
            "n_claim": n_claim,
            "n_missing": n_missing,
            "n_edges": len(self.edges),
            "n_supports": n_supports,
            "n_contradicts": n_contradicts,
            "claim_status": claim_status_breakdown,
        }

    # ---- mutators --------------------------------------------------------

    def add_evidence(self, source_kind: str, source_ref: str, title: str,
                     summary: str, raw: dict | None = None) -> str:
        nid = self._next_id("E")
        node = EvidenceNode(
            id=nid, kind="evidence", title=title[:200], body=summary[:2000],
            source_kind=source_kind[:40], source_ref=source_ref[:500],
            source_data=raw or {},
        )
        self.nodes.append(node)
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        return nid

    def add_claim(self, claim: str, rationale: str = "",
                  status: str = "exploring", confidence: float = 0.5) -> str:
        if status not in VALID_CLAIM_STATUS:
            raise ValueError(f"claim status 非法: {status}（应为 {sorted(VALID_CLAIM_STATUS)}）")
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        nid = self._next_id("C")
        node = EvidenceNode(
            id=nid, kind="claim", title=claim[:200], body=rationale[:2000],
            status=status, confidence=conf,
        )
        self.nodes.append(node)
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        return nid

    def link(self, source_id: str, target_id: str, relation: str = "supports",
             note: str = "") -> str:
        if relation not in VALID_RELATIONS:
            raise ValueError(f"relation 非法: {relation}（应为 {sorted(VALID_RELATIONS)}）")
        nodes_by_id = {n.id: n for n in self.nodes}
        source = nodes_by_id.get(source_id)
        target = nodes_by_id.get(target_id)
        if source is None:
            raise ValueError(f"source_id 不存在: {source_id}")
        if target is None:
            raise ValueError(f"target_id 不存在: {target_id}")
        expected_source, expected_target = RELATION_ENDPOINT_KINDS[relation]
        if source.kind != expected_source or target.kind != expected_target:
            raise ValueError(
                f"{relation} 只能连接 {expected_source} → {expected_target}，"
                f"当前为 {source.kind}({source_id}) → {target.kind}({target_id})"
            )
        edge = EvidenceEdge(src=source_id, dst=target_id, relation=relation, note=note[:200])
        self.edges.append(edge)
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        return f"{source_id}--{relation}-->{target_id}"

    def set_claim_status(self, claim_id: str, status: str,
                         confidence: float | None = None, rationale: str = "") -> EvidenceNode:
        if status not in VALID_CLAIM_STATUS:
            raise ValueError(f"claim status 非法: {status}")
        for n in self.nodes:
            if n.id == claim_id and n.kind == "claim":
                n.status = status
                if confidence is not None:
                    try:
                        n.confidence = max(0.0, min(1.0, float(confidence)))
                    except (TypeError, ValueError):
                        pass
                if rationale:
                    n.body = (n.body + "\n— " + rationale[:1500]).strip()[-2000:]
                self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                return n
        raise ValueError(f"claim_id 不存在或不是 claim: {claim_id}")

    def merge_claims(self, keep_id: str, merge_ids: list, canonical: str, rationale: str = "") -> str:
        nodes_by_id = {n.id: n for n in self.nodes}
        keep = nodes_by_id.get(keep_id)
        if keep is None:
            raise ValueError(f"keep_id 不存在: {keep_id}")
        if keep.kind != "claim":
            raise ValueError(f"keep_id 必须是 claim: {keep_id} 当前为 {keep.kind}")
        if not isinstance(merge_ids, list):
            raise ValueError("merge_ids 必须是 claim_id 列表")
        for mid in merge_ids:
            node = nodes_by_id.get(mid)
            if node is None:
                raise ValueError(f"merge_id 不存在: {mid}")
            if node.kind != "claim":
                raise ValueError(f"merge_id 必须是 claim: {mid} 当前为 {node.kind}")
            if mid == keep_id:
                continue
        # 把被合并的节点的入边/出边转移给 keep_id
        new_edges: list[EvidenceEdge] = []
        for e in self.edges:
            src = keep_id if e.src in merge_ids else e.src
            dst = keep_id if e.dst in merge_ids else e.dst
            if src == dst:
                continue  # 自环
            new_edges.append(EvidenceEdge(src=src, dst=dst, relation=e.relation, note=e.note))
        self.edges = self._deduplicate_edges(new_edges)
        # 删除被合并的 claim 节点
        self.nodes = [n for n in self.nodes if not (n.id in merge_ids and n.id != keep_id)]
        # 更新 keep_id 的 title 为 canonical
        for n in self.nodes:
            if n.id == keep_id:
                n.title = canonical[:200]
                if rationale:
                    n.body = (n.body + "\n[merge] " + rationale[:1500]).strip()[-2000:]
                break
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        return keep_id

    @staticmethod
    def _deduplicate_edges(edges: list[EvidenceEdge]) -> list[EvidenceEdge]:
        unique: dict[tuple[str, str, str], EvidenceEdge] = {}
        for edge in edges:
            key = (edge.src, edge.dst, edge.relation)
            previous = unique.get(key)
            if previous is None or (not previous.note.strip() and edge.note.strip()):
                unique[key] = edge
        return list(unique.values())

    def audit(self) -> dict:
        """返回非阻断、机器可读的图谱结构质量检查。"""
        outgoing: dict[str, list[EvidenceEdge]] = {n.id: [] for n in self.nodes}
        incoming: dict[str, list[EvidenceEdge]] = {n.id: [] for n in self.nodes}
        edge_groups: dict[tuple[str, str, str], list[EvidenceEdge]] = {}
        for edge in self.edges:
            outgoing.setdefault(edge.src, []).append(edge)
            incoming.setdefault(edge.dst, []).append(edge)
            edge_groups.setdefault((edge.src, edge.dst, edge.relation), []).append(edge)

        def node_ref(node: EvidenceNode) -> dict[str, str]:
            return {"id": node.id, "title": node.title}

        claims_without_substantive_evidence = []
        context_only_claims = []
        for node in self.nodes:
            if node.kind != "claim":
                continue
            relations = {edge.relation for edge in outgoing.get(node.id, [])}
            if not relations.intersection({"supports", "contradicts"}):
                claims_without_substantive_evidence.append(node_ref(node))
                if relations == {"context"}:
                    context_only_claims.append(node_ref(node))
        orphan_evidence = [
            node_ref(node) for node in self.nodes
            if node.kind == "evidence" and not outgoing.get(node.id) and not incoming.get(node.id)
        ]
        unaddressed_missing = [
            node_ref(node) for node in self.nodes
            if node.kind == "missing"
            and not any(edge.relation == "addresses" for edge in incoming.get(node.id, []))
        ]
        duplicate_edges = [
            {"source_id": src, "target_id": dst, "relation": relation, "count": len(group)}
            for (src, dst, relation), group in edge_groups.items() if len(group) > 1
        ]
        edges_missing_note = [
            {"source_id": edge.src, "target_id": edge.dst, "relation": edge.relation}
            for edge in self.edges if not edge.note.strip()
        ]
        categories = {
            "claims_without_substantive_evidence": claims_without_substantive_evidence,
            "context_only_claims": context_only_claims,
            "orphan_evidence": orphan_evidence,
            "unaddressed_missing": unaddressed_missing,
            "duplicate_edges": duplicate_edges,
            "edges_missing_note": edges_missing_note,
        }
        counts = {name: len(items) for name, items in categories.items()}
        return {"summary": {**counts, "total_findings": sum(counts.values())}, **categories}

    def add_missing(self, aspect: str, why_missing: str, priority: int = 1) -> str:
        try:
            prio = max(1, min(5, int(priority)))
        except (TypeError, ValueError):
            prio = 1
        nid = self._next_id("M")
        node = EvidenceNode(
            id=nid, kind="missing", title=aspect[:200], body=why_missing[:2000],
            priority=prio,
        )
        self.nodes.append(node)
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        return nid

    def set_sufficient(self, sufficient: bool, stop_reason: str = "") -> None:
        self.sufficient = bool(sufficient)
        self.stop_reason = stop_reason[:500]
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self.sufficient = False
        self.stop_reason = ""
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_payload(self) -> dict:
        return {
            "question": self.question,
            "scope": self.scope,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "missing": [n.to_dict() for n in self.nodes if n.kind == "missing"],
            "sufficient": self.sufficient,
            "stop_reason": self.stop_reason,
            "stats": self._counts(),
            "audit": self.audit(),
            "markdown": self.to_markdown(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# 证据图：{self.question}")
        if self.scope:
            lines.append(f"> 范围：{self.scope}")
        c = self._counts()
        lines.append("")
        lines.append(f"**统计**：evidence {c['n_evidence']} · claim {c['n_claim']} · "
                     f"边 {c['n_edges']}（supports {c['n_supports']} / contradicts {c['n_contradicts']}）"
                     f" · missing {c['n_missing']} · 充分={self.sufficient}")
        if self.sufficient and self.stop_reason:
            lines.append(f"> 终止：{self.stop_reason}")

        # claim 节点（带 status 颜色标记）
        claims = [n for n in self.nodes if n.kind == "claim"]
        if claims:
            lines.append("")
            lines.append("## Claims（可证伪陈述）")
            for n in claims:
                mark = {
                    "verified": "✅", "rejected": "❌", "needs_more": "🟡",
                    "insufficient": "⚠️", "exploring": "🔍",
                }.get(n.status, "•")
                lines.append(f"- {mark} **{n.id}** [{n.status} · conf={n.confidence:.2f}] {n.title}")
                if n.body:
                    for ln in n.body.splitlines()[:3]:
                        lines.append(f"  > {ln[:200]}")
                # 关联 evidence
                rel_evidence = [(e, n2) for e in self.edges if e.src == n.id
                                for n2 in self.nodes if n2.id == e.dst and n2.kind == "evidence"]
                if rel_evidence:
                    for e, ev in rel_evidence:
                        lines.append(f"    — {e.relation} → [{ev.id}] {ev.title[:120]}")

        # evidence 节点
        evs = [n for n in self.nodes if n.kind == "evidence"]
        if evs:
            lines.append("")
            lines.append("## Evidence（数据证据）")
            for n in evs:
                lines.append(f"- **{n.id}** ({n.source_kind}) {n.title}")
                if n.source_ref:
                    lines.append(f"  > src: `{n.source_ref[:200]}`")
                if n.body:
                    for ln in n.body.splitlines()[:2]:
                        lines.append(f"  > {ln[:200]}")

        # missing 节点
        miss = sorted([n for n in self.nodes if n.kind == "missing"],
                      key=lambda x: -x.priority)
        if miss:
            lines.append("")
            lines.append("## 尚未覆盖（next focus）")
            for n in miss:
                lines.append(f"- 🕳️ **[prio {n.priority}] {n.id}** {n.title}")
                if n.body:
                    lines.append(f"  > {n.body[:300]}")

        audit_counts = self.audit()["summary"]
        if audit_counts["total_findings"]:
            lines.append("")
            lines.append("## 图谱自检（待处理）")
            labels = {
                "claims_without_substantive_evidence": "缺少 supports/contradicts 的 Claim",
                "context_only_claims": "仅有 context 的 Claim",
                "orphan_evidence": "孤立 Evidence",
                "unaddressed_missing": "未被 addresses 补足的 Missing",
                "duplicate_edges": "重复关系边",
                "edges_missing_note": "缺少说明的关系边",
            }
            for key, label in labels.items():
                if audit_counts[key]:
                    lines.append(f"- ⚠️ {label}：{audit_counts[key]}")

        return "\n".join(lines)

    # ---- internals -------------------------------------------------------

    def _next_id(self, prefix: str) -> str:
        max_n = 0
        for n in self.nodes:
            if n.id.startswith(prefix):
                try:
                    max_n = max(max_n, int(n.id[len(prefix):]))
                except ValueError:
                    pass
        return f"{prefix}{max_n + 1}"


# ---------------------------------------------------------------- helpers ---

def _new_gid() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------- skills ---

# 注意：所有 _eg_* sub-tool 的 handler 都通过 _require_graph() 从 ContextVar 拿图。
# 这样 deep_researcher agent 多次 tool call 之间图状态自动累积，无需在 skill signature 上
# 多塞一个 graph_id 参数。

_DEFAULT_PARAMS_BASE = {
    "type": "object",
    "additionalProperties": False,
}


def _params(props: dict, required: list[str]) -> dict:
    """Build a JSON schema with additionalProperties:false enforced."""
    p = dict(_DEFAULT_PARAMS_BASE)
    p["properties"] = props
    p["required"] = required
    return p


@skill(
    "_eg_add_evidence",
    "向当前证据图添加一条 evidence 节点（通常来自 akshare 类技能的取数结果）。"
    "source_kind 写 'akshare' 或 'inference'，source_ref 写源参数或 URL，"
    "title 一句话标题，summary 是对数据内容的事实摘要（不含主观判断），"
    "raw 是关键数据字段的字典（用于后续查询）。返回 evidence_id。",
    _params(
        {
            "source_kind": {"type": "string", "description": "数据来源种类：akshare / external / inference"},
            "source_ref": {"type": "string", "description": "数据来源的具体引用，如 'akshare.stock_zh_a_daily(symbol=600519)' 或 URL"},
            "title": {"type": "string", "description": "evidence 的一句话标题"},
            "summary": {"type": "string", "description": "数据内容的事实摘要（不含判断）"},
            "raw": {"type": "object", "description": "可选：关键数据字段（限定为 JSON-safe 的基本类型）"},
        },
        ["source_kind", "source_ref", "title", "summary"],
    ),
    internal=True,
)
def _eg_add_evidence(source_kind: str, source_ref: str, title: str,
                    summary: str, raw: dict | None = None) -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        # 限制 raw 大小以免压垮 prompt
        if raw is not None:
            raw = json.loads(json.dumps(raw, ensure_ascii=False, default=str))
            if not isinstance(raw, dict):
                raw = {"_value": raw}
        eid = g.add_evidence(
            source_kind=str(source_kind)[:40],
            source_ref=str(source_ref)[:500],
            title=str(title)[:200],
            summary=str(summary)[:2000],
            raw=raw,
        )
        return ok(
            {"evidence_id": eid, "graph_stats": g._counts()},
            meta("evidence_graph", 1),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_add_evidence 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_add_claim",
    "向当前证据图添加一条 claim 节点（一个可证伪的陈述或假设）。"
    "status 默认 exploring，可选 verified/rejected/needs_more/insufficient。"
    "confidence 是 0~1 之间的初始确信度。返回 claim_id。",
    _params(
        {
            "claim": {"type": "string", "description": "一句话陈述（可证伪）"},
            "rationale": {"type": "string", "description": "为什么提这个 claim 的说明"},
            "status": {"type": "string", "description": "初始状态，默认 exploring",
                       "enum": ["exploring", "verified", "rejected", "needs_more", "insufficient"]},
            "confidence": {"type": "number", "description": "0~1 初始确信度", "minimum": 0, "maximum": 1},
        },
        ["claim"],
    ),
    internal=True,)
def _eg_add_claim(claim: str, rationale: str = "", status: str = "exploring",
                 confidence: float = 0.5) -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        cid = g.add_claim(claim, rationale, status, confidence)
        return ok(
            {"claim_id": cid, "graph_stats": g._counts(),
             "title_check": check_claim_title(claim)},
            meta("evidence_graph", 1),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_add_claim 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_link",
    "创建有语义约束的图关系：supports / contradicts / context 必须是 claim → evidence；"
    "addresses 必须是 evidence → missing。source_id 和 target_id 来自此前图操作的返回。",
    _params(
        {
            "source_id": {"type": "string", "description": "边起点 ID"},
            "target_id": {"type": "string", "description": "边终点 ID"},
            "relation": {"type": "string",
                         "enum": ["supports", "contradicts", "context", "addresses"]},
            "note": {"type": "string", "description": "简短说明关系含义"},
        },
        ["source_id", "target_id"],
    ),
    internal=True,)
def _eg_link(source_id: str = "", target_id: str = "", relation: str = "supports",
            note: str = "", claim_id: str = "", evidence_id: str = "") -> dict:
    # 兼容旧的直接 Python 调用；LLM schema 仅暴露 source_id/target_id。
    source_id = source_id or claim_id
    target_id = target_id or evidence_id
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        edge_id = g.link(source_id, target_id, relation, note)
        return ok(
            {"edge_id": edge_id, "graph_stats": g._counts()},
            meta("evidence_graph", 1),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_link 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_set_claim_status",
    "更新 claim 的状态（verified/rejected/needs_more/insufficient）和确信度。"
    "当 claim 已被充分 evidence 支持/反驳时调用。",
    _params(
        {
            "claim_id": {"type": "string"},
            "status": {"type": "string",
                       "enum": ["exploring", "verified", "rejected", "needs_more", "insufficient"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
        },
        ["claim_id", "status"],
    ),
    internal=True,)
def _eg_set_claim_status(claim_id: str, status: str, confidence: float | None = None,
                        rationale: str = "") -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        n = g.set_claim_status(claim_id, status, confidence, rationale)
        return ok(
            {"claim_id": claim_id, "status": n.status, "confidence": n.confidence,
             "graph_stats": g._counts()},
            meta("evidence_graph", 1),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_set_claim_status 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_merge_claims",
    "合并重复/相似的 claim 节点：保留 keep_id，把 merge_ids 列表里的节点合并进来，"
    "并把它们的入边/出边转移到 keep_id。canonical 是合并后的统一陈述。",
    _params(
        {
            "keep_id": {"type": "string", "description": "要保留的 claim_id"},
            "merge_ids": {"type": "array", "items": {"type": "string"},
                          "description": "要被合并的 claim_id 列表"},
            "canonical_claim": {"type": "string", "description": "合并后的统一 claim 陈述"},
            "rationale": {"type": "string", "description": "为何要合并"},
        },
        ["keep_id", "merge_ids", "canonical_claim"],
    ),
    internal=True,)
def _eg_merge_claims(keep_id: str, merge_ids: list, canonical_claim: str,
                    rationale: str = "") -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        cid = g.merge_claims(keep_id, merge_ids, canonical_claim, rationale)
        return ok(
            {"kept_id": cid, "graph_stats": g._counts()},
            meta("evidence_graph", 1),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_merge_claims 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_add_missing",
    "记录尚未覆盖的研究面（用于自我反思 / 下一轮 follow-up）。"
    "priority 1~5（5 最重要），why_missing 说明为何这个面还没被覆盖。",
    _params(
        {
            "aspect": {"type": "string", "description": "研究面的一句话描述"},
            "why_missing": {"type": "string", "description": "为何这个面还没被覆盖"},
            "priority": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        ["aspect", "why_missing"],
    ),
    internal=True,)
def _eg_add_missing(aspect: str, why_missing: str, priority: int = 1) -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        mid = g.add_missing(aspect, why_missing, priority)
        return ok(
            {"missing_id": mid, "graph_stats": g._counts()},
            meta("evidence_graph", 1),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_add_missing 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_set_sufficient",
    "标记当前图已充分（终止信号）。当你认为已经有足够 evidence + claim 闭环时调用。"
    "stop_reason 简要说明为何认为已充分。",
    _params(
        {
            "sufficient": {"type": "boolean", "description": "true=已充分；false=还需要继续"},
            "stop_reason": {"type": "string"},
        },
        ["sufficient"],
    ),
    internal=True,)
def _eg_set_sufficient(sufficient: bool, stop_reason: str = "") -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        g.set_sufficient(bool(sufficient), stop_reason)
        return ok(
            {"sufficient": g.sufficient, "stop_reason": g.stop_reason,
             "graph_stats": g._counts()},
            meta("evidence_graph", 1),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_set_sufficient 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_export",
    "导出当前图为 markdown 摘要 + JSON。当你认为研究完成时调用一次，"
    "会作为 artifact 落库并展示给用户。format 默认 markdown。",
    _params(
        {
            "format": {"type": "string", "enum": ["markdown", "json"],
                       "description": "导出格式，默认 markdown"},
        },
        [],
    ),
    internal=True,)
def _eg_export(format: str = "markdown") -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        fmt = (format or "markdown").lower()
        if fmt == "json":
            payload_str = json.dumps(g.to_payload(), ensure_ascii=False, default=str)
            return ok(
                {"format": "json", "markdown": g.to_markdown(),
                 "graph_stats": g._counts(), "audit": g.audit()},
                meta("evidence_graph", len(g.nodes) + len(g.edges)),
                # JSON 单独不入主 artifact（太大），但 markdown 会进
            )
        # markdown：作为 artifact 落库
        md = g.to_markdown()
        artifact = None if _DEFER_EXPORT_ARTIFACT.get() else {
            "kind": "graph",
            "title": "证据图",
            "payload": g.to_payload(),
        }
        return ok(
            {"format": "markdown", "markdown": md,
             "graph_stats": g._counts(), "audit": g.audit(),
             "artifact_deferred": artifact is None},
            meta("evidence_graph", len(g.nodes) + len(g.edges)),
            artifact=artifact,
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_export 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_audit",
    "机械检查当前图谱质量：返回缺少实质证据的 Claim、孤立 Evidence、"
    "未补足 Missing、重复边及缺少 note 的边；不修改图谱。",
    _params({}, []),
    internal=True,)
def _eg_audit() -> dict:
    try:
        g = _require_graph()
        return ok({"audit": g.audit(), "graph_stats": g._counts()}, meta("evidence_graph", 1))
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_audit 失败: {type(e).__name__}: {e}")


@skill(
    "_eg_clear",
    "重置当前图（保留 question/scope，清空所有节点和边）。"
    "用于研究路线跑偏需要重新开始时。",
    _params({}, []),
    internal=True,)
def _eg_clear() -> dict:
    try:
        g = _require_graph()
    except ValueError as e:
        return err(str(e))
    try:
        g.clear()
        return ok(
            {"graph_stats": g._counts(), "note": "图已重置（question/scope 保留）"},
            meta("evidence_graph", 0),
        )
    except Exception as e:  # noqa: BLE001
        return err(f"_eg_clear 失败: {type(e).__name__}: {e}")

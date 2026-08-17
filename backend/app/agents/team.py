"""team 模式编排 (design.md §6.3): plan → fan-out(串行) → synthesize → verify → extract.

修订: 改为串行执行 experts，避免并发 reasoning_content 交错污染前端。
新增: 5) extract —— 从最终结论中抽取「待验证推演」作为研究逻辑库条目。
新增: deep_researcher 作为专家（基于证据图的多轮研究），跑前 attach 证据图、跑后 export 为图谱 artifact。
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from .. import config
from ..llm import ArtifactStore, complete_json, run_agent
from .research_context import ResearchContext
from ..skills.evidence_graph import (
    EvidenceGraph, eg_attach, eg_detach, get_current_graph,
)
from .roster import AGENTS, get_agent, system_prompt

EXPERT_IDS = ["event_scout", "market_analyst", "fundamentals_analyst", "deep_researcher", "predictor"]

PLANNER_INSTRUCTION = """你是任务规划器。把用户问题拆成 2~4 个子任务，每个子任务指定一个专家 Agent：
- event_scout（事件猎手：新闻/公告/快讯检索，筛高影响事件）
- market_analyst（行情分析师：K线/指数/板块/龙虎榜/融资融券/事件研究）
- fundamentals_analyst（基本面分析师：财务摘要/财务指标/研报评级/宏观）
- deep_researcher（深度研究者：基于证据图的多轮研究 —— 适合需要从多个数据源反复验证假设的复杂问题；
  会把研究过程沉淀为一张可回看的证据图谱作为产出物。问题较深、可量化、可分多轮验证时优先用）
- predictor（事件预测员：后市推演世界模型 —— 基于近期 K线/资金/新闻/板块输出
  「乐观/中性/悲观」三档情景 + 概率 + 关键催化 + 可证伪假设。
  适合「接下来怎么走 / 后市如何 / 某事件后行情」类前瞻问题）

【硬规则 —— 深度研究团队必派 deep_researcher】
无论问题类型，plan 列表里 **必须** 包含 deep_researcher —— 它是"研究主控"，负责：
  1) 在 expert 各自完成片段研究后，把所有 evidence/claim 串到一张证据图上
  2) 在合成阶段提供图谱视角，让 router 拿到结构化的 claim/evidence 集合
  3) 标记 research gap（add_missing），让团队下一步 follow-up 有据可依

【软规则 —— 涉及预测/后市时加派 predictor】
当用户问题含「预测 / 后市 / 怎么看 / 接下来 / 会不会 / 行情推演 / 短期 / 未来 X 天 / 下周」等
前瞻关键词时，plan 列表里 **应当** 包含 predictor —— 它专门做多情景推演，比 deep_researcher
更轻、更有针对性（不沉淀证据图，只输出概率 + 情景 + 催化）。

通常结构（推荐 3 任务）：
- event_scout：扫事件/公告/快讯
- market_analyst 或 fundamentals_analyst：行情/基本面之一（按问题倾向选一个）
- deep_researcher：**始终最后**，把上面所有 expert 拿到的数据建图、标 claim、最后 export
- （预测类问题）predictor：可加在 deep_researcher 之后或之前，由 LLM 按需调度

简单事实型问题也至少派 1 个 expert + deep_researcher 两任务。

严格输出 JSON：{"tasks": [{"agent": "<id>", "task": "<具体子问题，含标的与时间范围>"}]}
同一个专家最多出现一次；deep_researcher 必出现一次。"""

HYPOTHESIS_EXTRACT_INSTRUCTION = """你是「研究逻辑提炼员」。从下面的研究结论中抽取**待市场验证的推演/假设/情景/条件预测**（不是已经成立的事实）。

每条是一个可证伪的论断，例如：
- "情景A：军工板块脉冲式反弹（概率60%）"
- "若央行 7 月降息 10bp，则地产/银行股短期跑赢大盘"
- "如果 Q3 业绩同比 < 0%，则估值切换压制股价"

严格输出 JSON：{"items": [
  {
    "hypothesis": "（一句话陈述，可证伪）",
    "category": "情景 | 条件预测 | 时间窗口 | 反方观点 | 量化阈值",
    "probability": "可选，如 60% / 0.6 / 中等概率；无则空串",
    "scope": "涉及的标的/板块/指数，如 '军工板块' '600519' '沪深300'",
    "horizon": "验证时间窗口，如 '未来 5 个交易日' '2026Q3 财报' '1 个月内'",
    "check": "（一句话说明如何用市场数据验证，例如「观察 5 个交易日内板块累计涨跌幅 > 0%」「财报发布后 EPS 是否 > 0.5 元」）"
  }
]}

- 最多 5 条
- 若结论中没有可证伪的推演/假设/情景，返回 {"items": []}
- 不要把已发生的事实或数据陈述（如「今日银行涨 1.2%」）当成 hypothesis
- 严格只输出 JSON，不要其他内容。"""


def _evidence_digest(tool_trace: list[dict], max_chars: int = 3000) -> str:
    lines = []
    for t in tool_trace:
        if t.get("type") != "tool":
            continue
        args = ",".join(f"{k}={v}" for k, v in (t.get("args") or {}).items())
        status = "OK" if t.get("ok") else "FAIL"
        lines.append(f"[{t.get('agent')}] {t.get('skill')}({args}) [{status}] {t.get('preview')}")
    text = "\n".join(lines)
    return text[:max_chars]


def _short_summary(text: str, max_chars: int = 120) -> str:
    """从 expert findings 中提取一句简短总结：取首段（首个 \\n\\n 之前），
    过长则按句号/换行截到 max_chars 之前，避免 agent_done 出现长 markdown。"""
    if not text:
        return ""
    first = text.split("\n\n", 1)[0].strip()
    # 去掉行内换行（让单段更紧凑）
    first = " ".join(first.splitlines()).strip()
    if len(first) <= max_chars:
        return first
    truncated = first[:max_chars]
    for sep in ["。", "？", "！", ".", "?", "!", ";", "；", "\n"]:
        idx = truncated.rfind(sep)
        if idx > max_chars // 2:
            return truncated[: idx + 1].strip() + ("…" if sep not in "。？！.?!；" else "")
    return truncated.rstrip() + "…"


def _seed_graph_from_findings(
    graph: EvidenceGraph,
    findings: dict[str, str],
    tool_trace: list[dict],
) -> int:
    """把前序专家产出预灌进 evidence graph，确保 deep_researcher 有图可继承。"""
    added = 0
    for aid, text in findings.items():
        if not text.strip():
            continue
        graph.add_evidence(
            source_kind="expert_finding",
            source_ref=f"{aid}.findings",
            title=f"{aid} 研究摘要",
            summary=text.strip()[:1600],
            raw={"agent": aid, "kind": "finding"},
        )
        added += 1
    seen: set[tuple[str, str, str]] = set()
    for t in tool_trace:
        if t.get("type") != "tool":
            continue
        agent = str(t.get("agent") or "").strip()
        skill = str(t.get("skill") or "").strip()
        preview = str(t.get("preview") or "").strip()
        if not agent or not skill or not preview:
            continue
        key = (agent, skill, preview[:120])
        if key in seen:
            continue
        seen.add(key)
        graph.add_evidence(
            source_kind="tool_trace",
            source_ref=f"{agent}.{skill}",
            title=f"{agent} · {skill}",
            summary=preview[:1200],
            raw={
                "agent": agent,
                "skill": skill,
                "ok": bool(t.get("ok")),
                "args": t.get("args") or {},
            },
        )
        added += 1
        if added >= 12:
            break
    return added


async def _run_expert_serial(
    agent_id: str,
    task_text: str,
    question: str,
    artifact_store: ArtifactStore,
    *,
    prior_findings: dict[str, str] | None = None,
    prior_tool_trace: list[dict] | None = None,
    research_context: ResearchContext | None = None,
) -> AsyncIterator[dict]:
    """单 expert 串行执行：agent_start → events → agent_done 收尾。失败也收尾。

    对 deep_researcher：进入前 attach 一张新证据图（ContextVar 持有），
    deep_researcher 的多次 tool call 之间图状态自动累积；退出时 detach 并把图作为
    graph artifact 落库。
    """
    yield {"type": "agent_step", "phase": "agent_start", "agent": agent_id, "note": task_text}
    expert_state: dict[str, Any] = {"content": "", "tool_trace": [], "rounds": 0}
    token = None
    graph: EvidenceGraph | None = None
    if agent_id == "deep_researcher":
        graph = EvidenceGraph(question=question, scope=task_text[:200])
        token = eg_attach(graph)
        _seed_graph_from_findings(graph, prior_findings or {}, prior_tool_trace or [])
    try:
        evidence_context = ""
        if agent_id == "deep_researcher":
            digest_blocks: list[str] = []
            for aid, txt in (prior_findings or {}).items():
                if txt.strip():
                    digest_blocks.append(f"【{aid} 既有发现】\n{txt[:800]}")
            tool_digest = _evidence_digest(prior_tool_trace or [], max_chars=1800)
            if tool_digest:
                digest_blocks.append(f"【已有工具证据摘要】\n{tool_digest}")
            if digest_blocks:
                evidence_context = (
                    "\n\n【你必须先继承这些既有证据并补全证据图】\n"
                    "当前 evidence graph 已经预载入前序专家的 findings / tool trace，"
                    "你必须优先围绕这张图工作：先补 claim / link / status / missing，再决定是否继续取数。\n\n"
                    + "\n\n".join(digest_blocks)
                )
        messages = [
            {"role": "system", "content": system_prompt(agent_id)},
            {"role": "user", "content":
                f"【用户原始问题】{question}\n\n【你的子任务】{task_text}\n\n"
                "请调用你的技能获取真实数据后作答；最后用不超过600字总结发现（含关键数字+来源）。"
                + evidence_context},
        ]
        async def team_skill_executor(name: str, args: dict) -> dict:
            if research_context is None:
                from ..llm import execute_skill
                return await execute_skill(name, args)
            from ..llm import execute_skill
            return await research_context.execute(execute_skill, name, args)

        async for ev in run_agent(agent_id, messages, agent_def=get_agent(agent_id),
                                  state=expert_state, artifact_store=artifact_store,
                                  skill_executor=team_skill_executor,
                                  max_rounds=config.TEAM_MAX_ROUNDS):
            yield ev
        findings = expert_state["content"].strip()
        # deep_researcher 收尾：若 LLM 没显式 export，把当前图强制导出为图谱 artifact
        if agent_id == "deep_researcher" and graph is not None:
            try:
                cur = get_current_graph()
                if cur is not None:
                    payload = cur.to_payload()
                    row = await artifact_store("graph", "证据图", payload)
                    yield {"type": "artifact", "agent": agent_id, "artifact": row}
                    expert_state["tool_trace"].append({
                        "type": "tool", "agent": agent_id, "id": "evidence_graph_export",
                        "skill": "evidence_graph", "args": {"action": "export"},
                        "ok": True, "preview": f"导出图谱 {payload['stats']}",
                        "artifact_ids": [row.get("id")],
                    })
                    # 附加一段文字总结到 findings（前端能看到图谱已沉淀）
                    stats = payload["stats"]
                    tail = (f"\n\n**证据图已沉淀**：evidence {stats['n_evidence']} 条、"
                            f"claim {stats['n_claim']} 条（"
                            f"{'、'.join(f'{k} {v}' for k, v in stats['claim_status'].items()) or '无'}）、"
                            f"边 {stats['n_edges']} 条（supports {stats['n_supports']} / "
                            f"contradicts {stats['n_contradicts']}）"
                            f"{'，已标记充分' if payload['sufficient'] else '，尚未充分'}")
                    if not findings.endswith(tail):
                        findings = (findings + tail) if findings else tail.lstrip("\n")
                        # 同步流给前端（让用户看到导出动作）
                        yield {"type": "token", "agent": agent_id, "delta": tail}
                        expert_state["content"] += tail
            except Exception as e:  # noqa: BLE001
                yield {"type": "thinking", "agent": agent_id,
                       "delta": f"\n[deep_researcher 导出图谱失败: {type(e).__name__}: {e}]\n"}
        yield {"type": "agent_step", "phase": "agent_done", "agent": agent_id,
               "note": _short_summary(findings)}
        yield {"type": "agent_findings", "agent": agent_id, "findings": findings[:600],
               "tool_trace": expert_state["tool_trace"]}
    except Exception as e:  # noqa: BLE001
        findings = f"（{agent_id} 执行失败: {type(e).__name__}: {e}）"
        yield {"type": "agent_step", "phase": "agent_done", "agent": agent_id,
               "note": "执行失败"}
        yield {"type": "agent_findings", "agent": agent_id, "findings": findings,
               "tool_trace": expert_state["tool_trace"], "error": str(e)}
    finally:
        if token is not None:
            try:
                eg_detach(token)
            except Exception:  # noqa: BLE001
                pass


async def run_team(
    question: str,
    history: list[dict],
    state: dict,
    artifact_store: ArtifactStore,
    team_members: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Yield SSE events for the whole team-mode flow. state['content'] = final answer.

    team_members: 前端可选的专家白名单（仅 EXPERT_IDS 内的子集生效）。
                  None / 空 = 全部可调度。deep_researcher 是硬规则（不剔除）。
    """
    # ------------------------------------------------------------ 1) plan --
    plan: list[dict] = []
    try:
        plan_json = await complete_json(
            system_prompt("router") + "\n\n" + PLANNER_INSTRUCTION,
            f"用户问题：{question}",
            max_tokens=2000,
        )
        if plan_json:
            for t in plan_json.get("tasks", []):
                aid = str(t.get("agent", "")).strip()
                task_text = str(t.get("task", "")).strip()
                if aid in EXPERT_IDS and task_text and all(p["agent"] != aid for p in plan):
                    plan.append({"agent": aid, "task": task_text})
    except Exception:  # noqa: BLE001
        plan = []
    if not plan:  # fallback：行情+基本面双视角 + deep_researcher 必派
        plan = [
            {"agent": "market_analyst", "task": f"围绕「{question}」分析行情、资金与关键事件的价格反应"},
            {"agent": "fundamentals_analyst", "task": f"围绕「{question}」分析基本面、财务与机构观点"},
            {"agent": "deep_researcher", "task":
             f"把 market_analyst / fundamentals_analyst 的发现沉淀到证据图：每条关键数字作为 evidence，"
             f"每条可证伪推断作为 claim，标 supports/contradicts 关系，最后 export 证据图"},
        ]
    # 应用 team_members 白名单：
    # 1) 剔除未勾选的专家（deep_researcher 永不被剔除，硬规则）
    # 2) 若剔除后没有任何 deep_researcher 之外的任务则保留 deep_researcher 单跑
    # 3) 若剔除后 plan 为空，退化为仅 deep_researcher
    if team_members is not None:
        allow = set(team_members) | {"deep_researcher"}
        before = [p["agent"] for p in plan]
        plan = [p for p in plan if p["agent"] in allow]
        removed = set(before) - set(p["agent"] for p in plan)
        if removed:
            yield {"type": "agent_step", "phase": "plan_filter",
                   "note": f"已按 team_members 筛选：剔除 {sorted(removed)}（剩余 {len(plan)} 个子任务）"}
        if not plan:
            plan = [{"agent": "deep_researcher", "task":
                     f"围绕「{question}」直接沉淀到证据图：每条关键数字作为 evidence，"
                     f"每条可证伪推断作为 claim，最后 export"}]
    plan = [p for p in plan if p["agent"] != "deep_researcher"] + [p for p in plan if p["agent"] == "deep_researcher"]
    plan = plan[:4]
    plan_public = [{**p, "agent_name": AGENTS[p["agent"]]["name"]} for p in plan]
    yield {"type": "agent_step", "phase": "plan", "note": f"拆解为 {len(plan)} 个子任务",
           "plan": plan_public}
    state["tool_trace"].append({"type": "plan", "plan": plan_public})

    # -------------------------------------------------------- 2) serial fan
    findings: dict[str, str] = {}
    research_context = ResearchContext()
    for p in plan:
        async for ev in _run_expert_serial(
            p["agent"], p["task"], question, artifact_store,
            prior_findings=findings if p["agent"] == "deep_researcher" else None,
            prior_tool_trace=state["tool_trace"] if p["agent"] == "deep_researcher" else None,
            research_context=research_context,
        ):
            # 提取 agent_findings 写入 state + findings；其余原样 yield
            if ev.get("type") == "agent_findings":
                aid = ev["agent"]
                findings[aid] = ev.get("findings", "")
                if ev.get("tool_trace"):
                    state["tool_trace"].extend(ev["tool_trace"])
                # 不把 agent_findings 推给前端（前端用 agent_step agent_done 已经知道）
                continue
            yield ev

    # ---------------------------------------------------------- 3) synthesize
    digest = "\n\n".join(
        f"【{AGENTS[aid]['name']}({aid}) 发现】\n{txt or '（无有效产出）'}"
        for aid, txt in findings.items()
    )
    synth_messages = [{"role": "system", "content": system_prompt("router")}]
    synth_messages.extend(history)
    synth_messages.append({
        "role": "user",
        "content": (
            f"【用户问题】{question}\n\n"
            f"【专家团队发现】\n{digest}\n\n"
            "请综合以上专家发现，给出结构化的最终回答（先结论后依据，标注来源与推断；"
            "如关键数据缺失可再调工具补充，但不要重复专家已查过的数据）。"
        ),
    })
    async def team_skill_executor(name: str, args: dict) -> dict:
        from ..llm import execute_skill
        return await research_context.execute(execute_skill, name, args)

    async for ev in run_agent("router", synth_messages, agent_def=get_agent("router"),
                              state=state, artifact_store=artifact_store,
                              skill_executor=team_skill_executor, max_rounds=3):
        yield ev

    state["tool_trace"].append({"type": "research_context", **research_context.stats()})

    # ------------------------------------------------------------- 4) verify
    draft = state["content"].strip()
    if draft:
        try:
            evidence = _evidence_digest(state["tool_trace"])
            verdict_json = await complete_json(
                system_prompt("verifier"),
                f"【分析草稿】\n{draft[:4000]}\n\n【证据摘要（工具调用记录）】\n{evidence}",
                max_tokens=3000,
            )
        except Exception:  # noqa: BLE001
            verdict_json = None
        verdict = "pass"
        issues: list[str] = []
        corrected = ""
        if verdict_json:
            verdict = str(verdict_json.get("verdict") or "pass")
            issues = [str(i) for i in (verdict_json.get("issues") or [])][:5]
            corrected = str(verdict_json.get("corrected") or "")
        note = "；".join(issues)[:300] if issues else "未发现事实性错误"
        yield {"type": "agent_step", "phase": "verified", "agent": "verifier",
               "note": f"verdict={verdict} · {note}"}
        state["tool_trace"].append({"type": "verify", "verdict": verdict,
                                    "issues": issues, "corrected": corrected[:1000]})
        if issues:
            fix_messages = [
                {"role": "system", "content": system_prompt("router")},
                {"role": "user", "content": (
                    f"【你的草稿】\n{draft[:3000]}\n\n"
                    f"【复核员意见】\n问题：{note}\n修正建议：{corrected[:1500]}\n\n"
                    "请直接输出修正后的关键内容（先一句话承认并更正问题，再给出修正后的关键段落）。"
                    "不要重复外层已注入的「## 复核修正」标题；开头不要以 # 标题开头，"
                    "直接以陈述句或「经核实…」之类的过渡句起笔即可。")},
            ]
            fix_state: dict[str, Any] = {"content": "", "tool_trace": state["tool_trace"]}
            header = "\n\n## 复核修正\n"
            state["content"] += header
            yield {"type": "token", "agent": "router", "delta": header}
            async for ev in run_agent("router", fix_messages,
                                      agent_def={**get_agent("router"), "skills": []},
                                      state=fix_state, artifact_store=artifact_store,
                                      max_rounds=1, emit_thinking=False):
                if ev.get("type") == "token":
                    delta = ev["delta"]
                    # 兜底：若 LLM 仍以 ## 复核修正 开头，剥掉首个重复标题
                    if not fix_state["content"] and delta.lstrip().startswith("#"):
                        lines = delta.lstrip().split("\n", 1)
                        first = lines[0].strip().lower()
                        if "复核修正" in first or first.startswith("#"):
                            delta = lines[1] if len(lines) > 1 else ""
                            if delta:
                                delta = "\n" + delta
                    state["content"] += delta
                yield ev

    # -------------------------------------------------- 5) extract hypotheses
    import time as _t
    final_answer = state["content"].strip()
    if final_answer:
        try:
            extracted = await complete_json(
                system_prompt("router") + "\n\n" + HYPOTHESIS_EXTRACT_INSTRUCTION,
                f"用户原始问题：{question}\n\n【研究结论】\n{final_answer[:3500]}",
                max_tokens=2000,
            )
        except Exception:  # noqa: BLE001
            extracted = None
        items: list[dict] = []
        if extracted:
            for j, it in enumerate((extracted.get("items") or [])[:5]):
                h = str(it.get("hypothesis") or "").strip()
                if not h:
                    continue
                items.append({
                    "id": f"h{int(_t.time() * 1000) % 1_000_000}_{j}",
                    "hypothesis": h[:300],
                    "category": str(it.get("category") or "").strip()[:30],
                    "probability": str(it.get("probability") or "").strip()[:20],
                    "scope": str(it.get("scope") or "").strip()[:80],
                    "horizon": str(it.get("horizon") or "").strip()[:50],
                    "check": str(it.get("check") or "").strip()[:200],
                })
        if items:
            yield {"type": "logic_items", "items": items}
            state["tool_trace"].append({"type": "logic_items", "count": len(items),
                                        "items": items})

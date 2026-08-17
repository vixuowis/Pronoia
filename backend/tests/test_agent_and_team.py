import unittest
from types import SimpleNamespace
from unittest.mock import patch

import backend.app.agents.team as team_mod
import backend.app.llm as llm_mod
from backend.app.agents.research_context import ResearchContext
from backend.app.llm import run_agent
from backend.app.skills.registry import ensure_skills_loaded, tools_for_agent


class TestAgentAndTeam(unittest.IsolatedAsyncioTestCase):
    def test_agent_tools_visibility_filters_internal(self):
        ensure_skills_loaded()
        tools = tools_for_agent("router")
        names = [t["function"]["name"] for t in tools]
        self.assertIn("announcement_onepager", names)
        self.assertIn("evidence_ledger", names)
        self.assertIn("search_stock", names)
        self.assertIn("get_current_date", names)
        self.assertNotIn("get_stock_news", names)

    async def test_team_run_team_filters_plan_by_team_members(self):
        async def fake_complete_json(system, user, *, max_tokens=2000):
            return {
                "tasks": [
                    {"agent": "market_analyst", "task": "t1"},
                    {"agent": "fundamentals_analyst", "task": "t2"},
                    {"agent": "deep_researcher", "task": "t3"},
                ]
            }

        async def fake_run_expert_serial(agent_id, task, question, artifact_store, **kwargs):
            yield {"type": "agent_step", "phase": "agent_done", "agent": agent_id, "note": "done"}
            yield {"type": "agent_findings", "agent": agent_id, "findings": f"{agent_id}:{task}", "tool_trace": []}

        async def fake_run_agent(agent_id, messages, *, agent_def, state, artifact_store,
                                 skill_executor=None, max_rounds=3, emit_thinking=True):
            state["content"] += "final"
            yield {"type": "token", "agent": agent_id, "delta": "final"}

        async def fake_artifact_store(kind, title, payload):
            return {"id": "a1", "kind": kind, "title": title, "payload": payload}

        with (
            patch.object(team_mod, "complete_json", fake_complete_json),
            patch.object(team_mod, "_run_expert_serial", fake_run_expert_serial),
            patch.object(team_mod, "run_agent", fake_run_agent),
        ):
            state = {"content": "", "tool_trace": []}
            evs = []
            async for ev in team_mod.run_team(
                "q",
                history=[],
                state=state,
                artifact_store=fake_artifact_store,
                team_members=["market_analyst"],
            ):
                evs.append(ev)

        plan_ev = next(e for e in evs if e.get("type") == "agent_step" and e.get("phase") == "plan")
        plan_agents = [p["agent"] for p in plan_ev["plan"]]
        self.assertIn("market_analyst", plan_agents)
        self.assertIn("deep_researcher", plan_agents)
        self.assertNotIn("fundamentals_analyst", plan_agents)
        self.assertEqual(plan_agents[-1], "deep_researcher")
        self.assertTrue(state["content"].endswith("final"))

    async def test_team_context_reuses_result_and_suppresses_duplicate_artifact(self):
        """The same tool result is shown to both agents but stored once."""
        def chunk(*, tool_call=None, content=None, finish_reason=None):
            delta = SimpleNamespace(content=content, reasoning_content=None,
                                    tool_calls=tool_call)
            return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])

        def tool_stream(call_id):
            async def gen():
                function = SimpleNamespace(name="shared_skill", arguments='{"symbol":"000001"}')
                tool_call = SimpleNamespace(index=0, id=call_id, function=function)
                yield chunk(tool_call=[tool_call], finish_reason="tool_calls")
            return gen()

        def final_stream():
            async def gen():
                yield chunk(content="完成", finish_reason="stop")
            return gen()

        class FakeCompletions:
            def __init__(self):
                self.n = 0

            async def create(self, **kwargs):
                self.n += 1
                return tool_stream(f"call-{self.n}") if self.n % 2 else final_stream()

        completions = FakeCompletions()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        executions = 0
        artifacts = []

        async def raw_executor(name, args):
            nonlocal executions
            executions += 1
            return {"ok": True, "data": [{"symbol": args["symbol"]}],
                    "meta": {"source": "test", "rows": 1},
                    "artifact": {"kind": "table", "title": "共享行情", "payload": {"rows": 1}}}

        async def artifact_store(kind, title, payload):
            artifacts.append((kind, title, payload))
            return {"id": f"a{len(artifacts)}"}

        context = ResearchContext()

        async def context_executor(name, args):
            return await context.execute(raw_executor, name, args)

        async def one_agent(agent_id):
            state = {"content": "", "tool_trace": [], "rounds": 0}
            events = []
            async for event in run_agent(
                agent_id, [{"role": "user", "content": "test"}],
                agent_def={"skills": []}, state=state, artifact_store=artifact_store,
                skill_executor=context_executor, max_rounds=2,
            ):
                events.append(event)
            return state, events

        with (
            patch.object(llm_mod, "get_client", return_value=fake_client),
            patch.object(llm_mod, "ensure_skills_loaded"),
            patch.object(llm_mod, "tools_for_agent", return_value=[]),
        ):
            first_state, first_events = await one_agent("first")
            second_state, second_events = await one_agent("second")

        self.assertEqual(executions, 1)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(context.stats(), {"calls": 2, "unique_calls": 1, "reuses": 1})
        self.assertFalse(first_state["tool_trace"][0]["reused"])
        self.assertTrue(second_state["tool_trace"][0]["reused"])
        self.assertEqual(len([e for e in first_events + second_events if e["type"] == "artifact"]), 1)

import unittest
from unittest.mock import patch

import backend.app.agents.team as team_mod
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

        async def fake_run_agent(agent_id, messages, *, agent_def, state, artifact_store, max_rounds=3, emit_thinking=True):
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

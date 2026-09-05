import asyncio
import unittest
from unittest.mock import patch

import backend.app.llm as llm_mod
from backend.app.skills.registry import REGISTRY, SkillDef


class TestSkillTimeouts(unittest.IsolatedAsyncioTestCase):
    def test_timeout_policy_keeps_parent_budget_larger(self):
        with (
            patch.object(llm_mod.config, "SKILL_TIMEOUT", 60.0),
            patch.object(llm_mod.config, "SKILL_SUB_TIMEOUT", 30.0),
            patch.object(llm_mod.config, "SKILL_SLOW_SUB_TIMEOUT", 45.0),
            patch.object(llm_mod.config, "SKILL_COMPOSITE_SUB_TIMEOUT", 50.0),
        ):
            self.assertEqual(llm_mod._skill_timeout("market_research", "skill", 0), 60.0)
            self.assertEqual(llm_mod._skill_timeout("market_research", "skill", 1), 50.0)
            self.assertEqual(llm_mod._skill_timeout("event_study", "atomic", 1), 45.0)
            self.assertEqual(llm_mod._skill_timeout("get_stock_daily", "atomic", 1), 30.0)

    async def test_nested_atomic_timeout_returns_before_parent_deadline(self):
        async def child_handler():
            await asyncio.sleep(0.05)
            return {"ok": True}

        async def parent_handler():
            return await llm_mod.execute_skill("_test_timeout_child", {})

        previous_parent = REGISTRY.get("_test_timeout_parent")
        previous_child = REGISTRY.get("_test_timeout_child")
        REGISTRY["_test_timeout_parent"] = SkillDef(
            name="_test_timeout_parent", description="test", parameters={"type": "object", "properties": {}},
            handler=parent_handler, category="skill", internal=True,
        )
        REGISTRY["_test_timeout_child"] = SkillDef(
            name="_test_timeout_child", description="test", parameters={"type": "object", "properties": {}},
            handler=child_handler, category="atomic", internal=True,
        )
        try:
            with (
                patch.object(llm_mod.config, "SKILL_TIMEOUT", 0.20),
                patch.object(llm_mod.config, "SKILL_SUB_TIMEOUT", 0.01),
                patch.object(llm_mod.config, "SKILL_SLOW_SUB_TIMEOUT", 0.05),
                patch.object(llm_mod.config, "SKILL_COMPOSITE_SUB_TIMEOUT", 0.10),
            ):
                result = await llm_mod.execute_skill("_test_timeout_parent", {})
        finally:
            if previous_parent is None:
                REGISTRY.pop("_test_timeout_parent", None)
            else:
                REGISTRY["_test_timeout_parent"] = previous_parent
            if previous_child is None:
                REGISTRY.pop("_test_timeout_child", None)
            else:
                REGISTRY["_test_timeout_child"] = previous_child

        self.assertFalse(result["ok"])
        self.assertIn("子技能", result["error"])
        self.assertIn(">0.01s", result["error"])

import unittest

from backend.app.agents.roster import AGENTS
from backend.app.skills.registry import REGISTRY, ensure_skills_loaded, tools_for_agent


class TestRegistryContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_skills_loaded()

    def test_registry_has_entries(self):
        self.assertGreater(len(REGISTRY), 0)

    def test_every_tool_has_schema_and_handler(self):
        bad = []
        for name, sd in REGISTRY.items():
            if not name or not isinstance(name, str):
                bad.append(("name", name))
                continue
            if not callable(sd.handler):
                bad.append((name, "handler-not-callable"))
            if not sd.description or not isinstance(sd.description, str):
                bad.append((name, "missing-description"))
            if not isinstance(sd.parameters, dict):
                bad.append((name, "parameters-not-dict"))
            else:
                if sd.parameters.get("type") != "object":
                    bad.append((name, "parameters-not-object"))
        self.assertEqual(bad, [])

    def test_agent_skill_lists_are_valid_and_public(self):
        bad = []
        for agent_id, a in AGENTS.items():
            for skill_name in a.get("skills", []) or []:
                sd = REGISTRY.get(skill_name)
                if sd is None:
                    bad.append((agent_id, skill_name, "missing"))
                    continue
                if sd.internal:
                    bad.append((agent_id, skill_name, "internal"))
        self.assertEqual(bad, [])

    def test_tools_for_agent_filters_internal(self):
        tools = tools_for_agent("router")
        visible = {t["function"]["name"] for t in tools}
        internal_leaks = []
        for name, sd in REGISTRY.items():
            if sd.internal and name in visible:
                internal_leaks.append(name)
        self.assertEqual(internal_leaks, [])

"""Run-scoped shared results for team research.

This is deliberately separate from the process-wide TTL cache.  It only lives
for one team run and lets later agents reuse a successful *identical* skill
call made by an earlier agent.  Reused results retain their data for the LLM,
but are marked so the caller can avoid writing duplicate artifacts.
"""
from __future__ import annotations

import copy
import json
from typing import Awaitable, Callable


SkillExecutor = Callable[[str, dict], Awaitable[dict]]


def _key(name: str, args: dict) -> str:
    """A deterministic key that tolerates ordinary JSON tool arguments."""
    return json.dumps({"skill": name, "args": args}, ensure_ascii=False,
                      sort_keys=True, default=str, separators=(",", ":"))


class ResearchContext:
    """Successful team-run skill results, keyed by skill name and arguments."""

    def __init__(self) -> None:
        self._results: dict[str, dict] = {}
        self.calls = 0
        self.reuses = 0

    async def execute(self, executor: SkillExecutor, name: str, args: dict) -> dict:
        """Execute once or return an isolated, explicitly marked copy.

        Errors are intentionally not cached: a transient upstream failure should
        not prevent a later agent from retrying with the same request.
        """
        self.calls += 1
        key = _key(name, args)
        cached = self._results.get(key)
        if cached is not None:
            self.reuses += 1
            result = copy.deepcopy(cached)
            result["_team_shared"] = True
            return result

        result = await executor(name, args)
        if result.get("ok"):
            self._results[key] = copy.deepcopy(result)
        return result

    def stats(self) -> dict[str, int]:
        return {"calls": self.calls, "unique_calls": len(self._results), "reuses": self.reuses}

"""Run-scoped shared results for team research.

This is deliberately separate from the process-wide TTL cache.  It only lives
for one team run and lets later agents reuse a successful *identical* skill
call made by an earlier agent.  Reused results retain their data for the LLM,
but are marked so the caller can avoid writing duplicate artifacts.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from typing import Awaitable, Callable


SkillExecutor = Callable[[str, dict], Awaitable[dict]]


def _normalize_news_intel_args(args: dict) -> dict:
    """Normalize equivalent public ``news_intel`` calls for team sharing.

    This is limited to the run-scoped key: the original arguments still reach
    the skill handler, which remains responsible for validation and output.
    """
    normalized = dict(args or {})
    raw_symbol = str(normalized.get("symbol") or "").strip()
    digits = "".join(re.findall(r"\d", raw_symbol))
    if digits:
        # Match news_intel's own A-share alias resolution (e.g. sh600031).
        normalized["symbol"] = digits[-6:]
    elif not raw_symbol:
        normalized.pop("symbol", None)
    else:
        # Ticker case alone should not block reuse; invalid inputs stay unique.
        normalized["symbol"] = raw_symbol.upper()

    raw_kind = normalized.get("kind")
    if raw_kind is None:
        normalized["kind"] = ["announcement", "news"] if digits else ["global"]
    elif isinstance(raw_kind, list):
        # news_intel checks membership only, so kind behaves as a set.
        normalized["kind"] = sorted({str(item) for item in raw_kind})

    if "limit" not in normalized:
        normalized["limit"] = 8
    return normalized


def _normalized_args(name: str, args: dict) -> dict:
    if name == "news_intel":
        return _normalize_news_intel_args(args)
    if name == "market_research":
        normalized = dict(args or {})
        raw_symbol = str(normalized.get("symbol") or "").strip()
        digits = "".join(re.findall(r"\d", raw_symbol))
        normalized["symbol"] = digits[-6:] if digits else raw_symbol.upper()
        normalized["lookback_days"] = int(normalized.get("lookback_days") or 60)
        raw_focus = normalized.get("focus")
        normalized["focus"] = sorted({str(item) for item in raw_focus}) if isinstance(raw_focus, list) else ["flow", "price", "sector"]
        return normalized
    if name == "evidence_ledger":
        normalized = dict(args or {})
        raw_symbol = str(normalized.get("symbol") or "").strip()
        digits = "".join(re.findall(r"\d", raw_symbol))
        if raw_symbol:
            normalized["symbol"] = digits[-6:] if digits else raw_symbol.upper()
        else:
            normalized.pop("symbol", None)
        keyword = str(normalized.get("keyword") or "").strip()
        if keyword:
            normalized["keyword"] = keyword
        else:
            normalized.pop("keyword", None)
        normalized["lookback_days"] = int(normalized.get("lookback_days") or 60)
        normalized["limit"] = int(normalized.get("limit") or 20)
        return normalized
    return dict(args or {})


def _key(name: str, args: dict) -> str:
    """A deterministic key that tolerates ordinary JSON tool arguments."""
    return json.dumps({"skill": name, "args": _normalized_args(name, args)}, ensure_ascii=False,
                      sort_keys=True, default=str, separators=(",", ":"))


def _positive_int(value: object, default: int) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default


def _slice_artifacts(result: dict, limit: int, *, row_field: str) -> None:
    """Trim visual payloads too, although shared artifacts are not persisted."""
    artifacts = result.get("artifacts") or ([] if not result.get("artifact") else [result["artifact"]])
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        payload = artifact.get("payload")
        if not isinstance(payload, dict):
            continue
        if isinstance(payload.get(row_field), list):
            payload[row_field] = payload[row_field][:limit]
        if row_field == "rows" and isinstance(payload.get("dates"), list):
            payload["dates"] = payload["dates"][-limit:]
            for key in ("ohlc", "volumes"):
                if isinstance(payload.get(key), list):
                    payload[key] = payload[key][-limit:]


def _slice_news_intel(result: dict, requested: dict) -> dict:
    sliced = copy.deepcopy(result)
    limit = _positive_int(requested.get("limit"), 8)
    payload = sliced.get("data")
    if isinstance(payload, dict):
        payload["kind"] = list(requested["kind"])
        source_limits = {
            "llm_web_latest": min(limit, 8),
            "get_stock_news": min(limit, 10),
            "get_global_news": min(limit * 2, 20),
            "get_announcements": min(limit, 30),
            "get_us_stock_news": limit,
            "get_us_stock_sec_filings": limit,
        }
        successful_sources = [
            str(item.get("skill") or "") for item in payload.get("sub_results") or []
            if isinstance(item, dict) and item.get("ok")
        ]
        for idx, values in enumerate(payload.get("data_points") or []):
            if isinstance(values, list):
                source = successful_sources[idx] if idx < len(successful_sources) else ""
                payload["data_points"][idx] = values[:source_limits.get(source, limit)]
        # The user-facing previews are intentionally only diagnostic, but keep
        # their source list coherent when the result came from a single source.
        payload["slice_limit"] = limit
    _slice_artifacts(sliced, limit, row_field="items")
    return sliced


def _price_metrics(rows: list[dict]) -> dict:
    closes: list[float] = []
    for row in rows:
        try:
            closes.append(float(row.get("close")))
        except (AttributeError, TypeError, ValueError):
            continue
    if not closes:
        return {}
    metrics: dict[str, object] = {
        "available_trading_days": len(closes),
        "latest_date": rows[-1].get("date") if rows else None,
        "latest_close": closes[-1],
    }
    for window in (20, 60, 120):
        if len(closes) >= window:
            metrics[f"ma{window}"] = round(sum(closes[-window:]) / window, 4)
    return metrics


def _slice_market_price(result: dict, requested: dict) -> dict | None:
    """Cut an A-share price-only market_research result to a narrower window."""
    sliced = copy.deepcopy(result)
    payload = sliced.get("data")
    if not isinstance(payload, dict) or payload.get("market") != "A股":
        return None
    points = payload.get("data_points")
    if not isinstance(points, list) or len(points) != 1 or not isinstance(points[0], list):
        return None
    lookback = _positive_int(requested.get("lookback_days"), 60)
    # market_research uses this same calendar conversion before calling K-line.
    calendar_days = max(lookback * 2 + 30, lookback)
    cutoff = (datetime.now() - timedelta(days=calendar_days)).strftime("%Y-%m-%d")
    rows = [row for row in points[0] if isinstance(row, dict) and str(row.get("date") or "")[:10] >= cutoff]
    if not rows:
        return None
    payload["lookback_days"] = lookback
    payload["data_points"] = [rows]
    payload["price_metrics"] = _price_metrics(rows)
    payload["slice_lookback_days"] = lookback
    _slice_artifacts(sliced, len(rows), row_field="rows")
    return sliced


def _slice_evidence_ledger(result: dict, requested: dict) -> dict:
    sliced = copy.deepcopy(result)
    limit = _positive_int(requested.get("limit"), 20)
    payload = sliced.get("data")
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        payload["rows"] = payload["rows"][:limit]
        payload["slice_limit"] = limit
    _slice_artifacts(sliced, limit, row_field="rows")
    meta = sliced.get("meta")
    if isinstance(meta, dict) and isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        meta["rows"] = len(payload["rows"])
    return sliced


class ResearchContext:
    """Successful team-run results, with exact and conservative range reuse."""

    def __init__(self) -> None:
        self._results: dict[str, dict] = {}
        self._wide_results: list[tuple[str, dict, dict]] = []
        self.calls = 0
        self.reuses = 0
        self.slices = 0

    def _slice_from_wider_result(self, name: str, args: dict) -> dict | None:
        requested = _normalized_args(name, args)
        for cached_name, cached_args, cached_result in reversed(self._wide_results):
            if cached_name != name:
                continue
            if name == "news_intel":
                # A single LLM-search result is not reliably classifiable as a
                # news-only or announcement-only subset.  Limit-only slicing
                # is safe when the requested channels are identical.
                if (cached_args.get("symbol") == requested.get("symbol")
                        and cached_args.get("kind") == requested.get("kind")
                        and cached_args.get("limit", 8) >= requested.get("limit", 8)):
                    return _slice_news_intel(cached_result, requested)
            elif name == "market_research":
                # Only price-only A-share requests have a strict date-range
                # containment relationship.  Snapshot fields are excluded.
                if (cached_args.get("symbol") == requested.get("symbol")
                        and cached_args.get("focus") == requested.get("focus") == ["price"]
                        and cached_args.get("lookback_days", 60) >= requested.get("lookback_days", 60)):
                    return _slice_market_price(cached_result, requested)
            elif name == "evidence_ledger":
                # The rows are already sorted descending by the skill.  Only
                # a smaller result limit changes their requested semantics.
                same_scope = all(cached_args.get(key) == requested.get(key)
                                 for key in ("symbol", "keyword", "lookback_days"))
                if same_scope and cached_args.get("limit", 20) >= requested.get("limit", 20):
                    return _slice_evidence_ledger(cached_result, requested)
        return None

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

        sliced = self._slice_from_wider_result(name, args)
        if sliced is not None:
            self.reuses += 1
            self.slices += 1
            sliced["_team_shared"] = True
            sliced["_team_slice"] = True
            return sliced

        result = await executor(name, args)
        if result.get("ok"):
            self._results[key] = copy.deepcopy(result)
            if name in {"news_intel", "market_research", "evidence_ledger"}:
                self._wide_results.append((name, _normalized_args(name, args), copy.deepcopy(result)))
        return result

    def stats(self) -> dict[str, int]:
        return {"calls": self.calls, "unique_calls": len(self._results),
                "reuses": self.reuses, "slices": self.slices}

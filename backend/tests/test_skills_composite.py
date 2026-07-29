import unittest
from unittest.mock import patch

import backend.app.skills.skill as composite


def _ok(data, *, artifact=None, artifacts=None):
    out = {"ok": True, "data": data, "meta": {"source": "test", "rows": 1}}
    if artifacts is not None:
        out["artifacts"] = artifacts
    if artifact is not None:
        out["artifact"] = artifact
    return out


def _err(msg):
    return {"ok": False, "error": msg}


class TestCompositeSkills(unittest.IsolatedAsyncioTestCase):
    async def test_evidence_ledger_aggregates_rows(self):
        calls = []

        async def fake_execute_skill(name, args):
            calls.append((name, args))
            if name == "stock_overview":
                return _ok({"resolved_symbol": "600000", "market": "A股"})
            if name == "market_research":
                return _ok({"price_metrics": {"latest_close": 10.0, "ma20": 9.5}})
            if name == "llm_web_latest":
                return _ok([
                    {"title": "新闻A", "date": "2026-01-02 10:00:00", "source": "llm.web", "url": "u1", "kind": "news"},
                    {"title": "公告B", "date": "2026-01-01 09:00:00", "source": "llm.web", "url": "u2", "kind": "announcement"},
                ])
            if name == "get_stock_news":
                return _ok([
                    {"title": "新闻A", "date": "2026-01-02 10:00:00", "source": "akshare.stock_news_em", "url": "u1"},
                    {"title": "新闻A", "date": "2026-01-02 10:00:00", "source": "akshare.stock_news_em", "url": "u1"},
                ])
            if name == "get_announcements":
                return _ok([
                    {"title": "公告B", "date": "2026-01-01 09:00:00", "source": "akshare.stock_notice_report", "url": "u2"},
                ])
            if name == "dedupe_event_candidates":
                items = args["items"]
                return _ok(items[:2])
            if name == "score_evidence_items":
                items = []
                for it in args["items"]:
                    it2 = dict(it)
                    it2["label"] = "fact"
                    items.append(it2)
                return _ok(items)
            if name == "build_event_timeline":
                return _ok(sorted(args["items"], key=lambda x: x.get("date") or "", reverse=True))
            return _err(f"unexpected: {name}")

        with patch.object(composite, "execute_skill", fake_execute_skill):
            r = await composite.evidence_ledger(symbol=None, keyword="浦发银行", lookback_days=60, limit=20)

        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["price_metrics"]["latest_close"], 10.0)
        self.assertEqual(len(r["data"]["rows"]), 2)
        self.assertTrue(r.get("artifacts"))
        self.assertTrue(any(a.get("kind") == "table" for a in r["artifacts"]))
        self.assertTrue(any(c[0] == "dedupe_event_candidates" for c in calls))
        self.assertTrue(any(c[0] == "llm_web_latest" for c in calls))

    async def test_announcement_onepager_requires_input(self):
        r = await composite.announcement_onepager()
        self.assertFalse(r["ok"])

    async def test_announcement_onepager_timeline(self):
        async def fake_execute_skill(name, args):
            if name == "llm_web_latest":
                return _ok([
                    {"title": "公告B", "date": "2026-01-03 09:00:00", "source": "llm.web", "url": "u2", "kind": "announcement"},
                    {"title": "新闻A", "date": "2026-01-02 10:00:00", "source": "llm.web", "url": "u1", "kind": "news"},
                ])
            if name == "get_announcements":
                return _ok([
                    {"title": "公告B", "date": "2026-01-03 09:00:00", "source": "akshare.stock_notice_report", "url": "u2"},
                ])
            if name == "get_stock_news":
                return _ok([
                    {"title": "新闻A", "date": "2026-01-02 10:00:00", "source": "akshare.stock_news_em", "url": "u1"},
                ])
            if name == "dedupe_event_candidates":
                return _ok(args["items"])
            if name == "score_evidence_items":
                items = []
                for it in args["items"]:
                    it2 = dict(it)
                    it2["label"] = "fact"
                    items.append(it2)
                return _ok(items)
            if name == "build_event_timeline":
                return _ok(sorted(args["items"], key=lambda x: x.get("date") or "", reverse=True))
            return _err(f"unexpected: {name}")

        with patch.object(composite, "execute_skill", fake_execute_skill):
            r = await composite.announcement_onepager(symbol="600000", limit=12)

        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["symbol"], "600000")
        self.assertEqual(len(r["data"]["timeline"]), 2)
        self.assertTrue(r.get("artifacts"))

    async def test_news_intel_prefers_llm_web_latest(self):
        async def fake_execute_skill(name, args):
            if name == "llm_web_latest":
                return _ok([
                    {"title": "新闻A", "date": "2026-01-03 09:00:00", "source": "llm.web", "url": "u1", "kind": "news"},
                ])
            return _err(f"unexpected: {name}")

        with patch.object(composite, "execute_skill", fake_execute_skill):
            r = await composite.news_intel(symbol="600000", kind=["news"], limit=8)

        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["composed"], ["llm_web_latest"])
        self.assertIn("LLM 联网搜索优先命中", r.get("note", ""))

    async def test_announcement_onepager_falls_back_when_llm_empty(self):
        calls = []

        async def fake_execute_skill(name, args):
            calls.append(name)
            if name == "llm_web_latest":
                return _ok([])
            if name == "get_announcements":
                return _ok([
                    {"title": "公告B", "date": "2026-01-03 09:00:00", "source": "akshare.stock_notice_report", "url": "u2"},
                ])
            if name == "get_stock_news":
                return _ok([
                    {"title": "新闻A", "date": "2026-01-02 10:00:00", "source": "akshare.stock_news_em", "url": "u1"},
                ])
            if name == "dedupe_event_candidates":
                return _ok(args["items"])
            if name == "score_evidence_items":
                items = []
                for it in args["items"]:
                    it2 = dict(it)
                    it2["label"] = "fact"
                    items.append(it2)
                return _ok(items)
            if name == "build_event_timeline":
                return _ok(sorted(args["items"], key=lambda x: x.get("date") or "", reverse=True))
            return _err(f"unexpected: {name}")

        with patch.object(composite, "execute_skill", fake_execute_skill):
            r = await composite.announcement_onepager(symbol="600000", limit=12)

        self.assertTrue(r["ok"])
        self.assertIn("llm_web_latest", calls)
        self.assertIn("get_announcements", calls)
        self.assertIn("get_stock_news", calls)

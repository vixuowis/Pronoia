import unittest

from backend.app.skills.research_methods import (
    build_event_timeline,
    dedupe_event_candidates,
    score_evidence_items,
)


class TestResearchMethodsTools(unittest.TestCase):
    def test_dedupe_event_candidates_by_date_and_title(self):
        items = [
            {"date": "2026-01-01 10:00:00", "title": "A 股 开盘", "source": "x", "url": "u1"},
            {"date": "2026-01-01 12:00:00", "title": "A股开盘", "source": "y", "url": "u2"},
            {"date": "2026-01-02 10:00:00", "title": "A股开盘", "source": "z", "url": "u3"},
        ]
        r = dedupe_event_candidates(items)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["data"]), 2)

    def test_build_event_timeline_sorts_desc(self):
        items = [
            {"date": "2026-01-01 10:00:00", "title": "t1", "source": "s1"},
            {"date": "2026-01-03", "title": "t3", "source": "s3"},
            {"date": "2026/01/02", "title": "t2", "source": "s2"},
        ]
        r = build_event_timeline(items)
        self.assertTrue(r["ok"])
        rows = r["data"]
        self.assertEqual([row["title"] for row in rows], ["t3", "t2", "t1"])

    def test_score_evidence_items_sets_default_label(self):
        items = [
            {"title": "公告", "source": "akshare.stock_notice_report"},
            {"title": "新闻", "source": "akshare.stock_news_em"},
            {"title": "其他", "source": "unknown"},
        ]
        r = score_evidence_items(items)
        self.assertTrue(r["ok"])
        labels = [x["label"] for x in r["data"]]
        self.assertEqual(labels[0], "fact")
        self.assertEqual(labels[1], "fact")
        self.assertEqual(labels[2], "context")

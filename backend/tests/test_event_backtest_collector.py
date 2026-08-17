from __future__ import annotations

import unittest
from unittest.mock import patch

from app.event_backtest.collector import collect_cn_announcement_seeds, collect_macro_calendar_seeds, collect_us_sec_seeds


class EventBacktestCollectorTests(unittest.TestCase):
    def test_collect_cn_announcement_seeds_filters_and_normalizes(self):
        fake = {
            "ok": True,
            "data": [
                {
                    "title": "关于重大资产重组的公告",
                    "date": "2025-07-01",
                    "url": "https://example.com/cn1",
                    "snippet": "600519 贵州茅台 · 临时公告",
                },
                {
                    "title": "日常公告",
                    "date": "2025-07-01",
                    "url": "https://example.com/cn2",
                    "snippet": "600000 测试股份 · 其他",
                },
            ],
        }
        with patch("app.event_backtest.collector.get_announcements", return_value=fake):
            rows = collect_cn_announcement_seeds(dates=["20250701"], keywords=["重组"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].market, "CN")
        self.assertEqual(rows[0].symbol, "600519")
        self.assertEqual(rows[0].event_type_l2, "并购/分拆/再融资")

    def test_collect_us_sec_seeds_filters_and_normalizes(self):
        fake = {
            "ok": True,
            "data": {
                "rows": [
                    {
                        "date": "2025-07-02",
                        "type": "8-K",
                        "title": "Company announces acquisition of target",
                        "edgar_url": "https://sec.gov/1",
                    },
                    {
                        "date": "2025-07-02",
                        "type": "8-K",
                        "title": "Other event",
                        "edgar_url": "https://sec.gov/2",
                    },
                ]
            },
        }
        with patch("app.event_backtest.collector.get_us_stock_sec_filings", return_value=fake):
            rows = collect_us_sec_seeds(symbols=["NVDA"], count_per_symbol=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].market, "US")
        self.assertEqual(rows[0].symbol, "NVDA")
        self.assertEqual(rows[0].event_type_l2, "并购/分拆/再融资")

    def test_collect_macro_calendar_seeds_maps_to_indices(self):
        import pandas as pd

        df = pd.DataFrame(
            [
                {"地区": "美国", "事件": "CPI", "日期": "2025-07-10", "时间": "20:30", "公布": "3.1", "预期": "3.0", "前值": "3.2"},
                {"地区": "中国", "事件": "PMI", "日期": "2025-07-01", "时间": "09:30", "公布": "49.8", "预期": "50.2", "前值": "50.0"},
            ]
        )
        with patch("app.event_backtest.collector.ak.news_economic_baidu", return_value=df):
            rows = collect_macro_calendar_seeds(limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].market, "US")
        self.assertEqual(rows[0].symbol, "SPY")
        self.assertEqual(rows[0].event_type_l2, "通胀数据意外")
        self.assertEqual(rows[1].market, "CN")
        self.assertEqual(rows[1].symbol, "sh000300")
        self.assertEqual(rows[1].event_type_l2, "增长/就业数据意外")


if __name__ == "__main__":
    unittest.main()

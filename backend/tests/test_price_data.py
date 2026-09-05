import unittest
from unittest.mock import patch

import pandas as pd

from backend.app.skills.price_data import fetch_price_frame, resolve_security_ref


class TestSecurityResolution(unittest.TestCase):
    def test_resolves_stock_etf_index_and_us_without_network(self):
        stock = resolve_security_ref("600000")
        etf = resolve_security_ref("SH513080")
        index = resolve_security_ref("sh000300")
        us = resolve_security_ref("XLRE", "US")

        self.assertEqual((stock.symbol, stock.kind), ("sh600000", "stock"))
        self.assertEqual((etf.symbol, etf.kind), ("sh513080", "etf"))
        self.assertEqual((index.symbol, index.kind), ("sh000300", "index"))
        self.assertEqual((us.symbol, us.market), ("XLRE", "US"))

    def test_etf_uses_etf_history_before_other_cn_routes(self):
        etf_df = pd.DataFrame({
            "日期": ["2026-01-02", "2026-01-05"],
            "开盘": [1.0, 1.1], "收盘": [1.1, 1.2],
            "最高": [1.2, 1.3], "最低": [0.9, 1.0], "成交量": [10, 20],
        })
        with patch("backend.app.skills.price_data._fetch_tencent_kline", side_effect=TimeoutError), \
             patch("backend.app.skills.price_data.ak.fund_etf_hist_em", return_value=etf_df) as etf_call, \
             patch("backend.app.skills.price_data.ak.stock_zh_index_daily") as index_call:
            fetched = fetch_price_frame("513080", "20260101", "20260131")

        self.assertEqual(fetched.provider, "akshare.fund_etf_hist_em")
        self.assertEqual(fetched.security.kind, "etf")
        self.assertEqual(len(fetched.frame), 2)
        etf_call.assert_called_once()
        index_call.assert_not_called()

    def test_us_falls_back_to_akshare_when_yfinance_is_empty(self):
        us_df = pd.DataFrame({
            "date": ["2026-01-02"], "open": [10], "close": [11],
            "high": [12], "low": [9], "volume": [100],
        })
        with patch("backend.app.skills.price_data._fetch_yahoo_chart", side_effect=TimeoutError), \
             patch("backend.app.skills.price_data.yf.download", return_value=pd.DataFrame()), \
             patch("backend.app.skills.price_data.ak.stock_us_daily", return_value=us_df) as ak_call:
            fetched = fetch_price_frame("MDT", "20260101", "20260131", market="US")

        self.assertEqual(fetched.provider, "akshare.stock_us_daily")
        ak_call.assert_called_once()

    def test_cn_prefers_bounded_tencent_route(self):
        cn_df = pd.DataFrame({
            "date": ["2026-01-02"], "open": [10], "close": [11],
            "high": [12], "low": [9], "volume": [100],
        })
        with patch("backend.app.skills.price_data._fetch_tencent_kline", return_value=cn_df) as tx_call, \
             patch("backend.app.skills.price_data.ak.stock_zh_a_daily") as sina_call:
            fetched = fetch_price_frame("600000", "20260101", "20260131")

        self.assertEqual(fetched.provider, "tencent.kline")
        tx_call.assert_called_once()
        sina_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()

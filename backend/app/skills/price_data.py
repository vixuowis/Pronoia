"""Shared security classification and historical-price provider routing.

This module is intentionally independent from the skill registry.  Both the
interactive research skills and the event backtest labeller use it, avoiding
the two subtly different ETF/index routing implementations that previously
existed in those paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import re
import time
from typing import Literal

import akshare as ak
import pandas as pd
import requests
import yfinance as yf


Market = Literal["CN", "US"]
SecurityKind = Literal["stock", "etf", "index"]

_US_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
_CN_EXPLICIT_RE = re.compile(r"^(sh|sz|bj)(\d{6})$", re.IGNORECASE)
_CN_SUFFIX_RE = re.compile(r"^(\d{6})\.(ss|sz|bj)$", re.IGNORECASE)

# Common exchange indexes.  A bare 000xxx is otherwise usually a Shenzhen
# stock, so it must not be treated as an index solely from its prefix.
_SH_INDEX_CODES = {
    "000001", "000009", "000010", "000016", "000300", "000688",
    "000852", "000905",
}
_SZ_INDEX_CODES = {"399001", "399005", "399006", "399300", "399905", "399986"}
_ETF_PREFIXES_SH = ("50", "51", "52", "56", "58")
_ETF_PREFIXES_SZ = ("15",)


@dataclass(frozen=True)
class SecurityRef:
    market: Market
    symbol: str
    code: str
    kind: SecurityKind
    exchange: str

    def as_dict(self) -> dict[str, str]:
        return {
            "market": self.market,
            "symbol": self.symbol,
            "code": self.code,
            "kind": self.kind,
            "exchange": self.exchange,
        }


@dataclass(frozen=True)
class PriceFrame:
    security: SecurityRef
    provider: str
    frame: pd.DataFrame
    attempts: tuple[str, ...]


class PriceFetchError(ValueError):
    def __init__(self, security: SecurityRef, attempts: list[str]):
        self.security = security
        self.attempts = tuple(attempts)
        detail = "; ".join(attempts) if attempts else "no provider attempted"
        super().__init__(f"{security.symbol} 行情获取失败: {detail}")


def _market_hint(value: str | None) -> Market | None:
    hint = str(value or "").strip().lower()
    if hint in {"cn", "a", "a股", "china"}:
        return "CN"
    if hint in {"us", "美股", "usa"}:
        return "US"
    return None


def _cn_ref(prefix: str, code: str) -> SecurityRef:
    prefix = prefix.lower()
    if code.startswith(_ETF_PREFIXES_SH):
        prefix, kind = "sh", "etf"
    elif code.startswith(_ETF_PREFIXES_SZ):
        prefix, kind = "sz", "etf"
    elif code in _SZ_INDEX_CODES or code.startswith(("399",)):
        prefix, kind = "sz", "index"
    elif code in _SH_INDEX_CODES or code.startswith(("880", "881")):
        prefix, kind = "sh", "index"
    else:
        kind = "stock"
    exchange = {"sh": "SSE", "sz": "SZSE", "bj": "BSE"}[prefix]
    return SecurityRef("CN", f"{prefix}{code}", code, kind, exchange)


def resolve_security_ref(symbol: str, market: str | None = None) -> SecurityRef:
    """Resolve an explicit symbol without making any network request."""
    raw = str(symbol or "").strip()
    if not raw:
        raise ValueError("symbol 不能为空")
    hint = _market_hint(market)

    explicit = _CN_EXPLICIT_RE.fullmatch(raw)
    if explicit:
        return _cn_ref(explicit.group(1), explicit.group(2))
    suffixed = _CN_SUFFIX_RE.fullmatch(raw)
    if suffixed:
        suffix = suffixed.group(2).lower()
        return _cn_ref("sh" if suffix == "ss" else suffix, suffixed.group(1))
    if re.fullmatch(r"\d{6}", raw):
        code = raw
        if code.startswith(("92",)) or code[0] in {"4", "8"}:
            prefix = "bj"
        elif code.startswith(_ETF_PREFIXES_SH) or code[0] in {"6", "9"}:
            prefix = "sh"
        elif code.startswith(_ETF_PREFIXES_SZ) or code[0] in {"0", "1", "2", "3"}:
            prefix = "sz"
        else:
            prefix = "sh"
        return _cn_ref(prefix, code)
    if hint != "CN" and _US_SYMBOL_RE.fullmatch(raw):
        ticker = raw.upper()
        return SecurityRef("US", ticker, ticker, "stock", "US")
    raise ValueError(f"无法识别证券代码: {symbol}")


def _date8(value: str | None, default: date) -> str:
    if not value:
        return default.strftime("%Y%m%d")
    match = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", str(value).strip())
    if not match:
        raise ValueError(f"无法识别日期: {value}")
    return "".join(match.groups())


def _standardize(df: pd.DataFrame, start8: str, end8: str) -> pd.DataFrame:
    if df is None or len(df) == 0:
        raise ValueError("empty response")
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance returns (field, ticker) for download(), even for one ticker
        df = df.copy()
        df.columns = [str(col[0]) for col in df.columns]
    if not isinstance(df.index, pd.RangeIndex):
        index_name = str(df.index.name or "").lower()
        if index_name in {"date", "datetime"} or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
    aliases = {
        "date": "date", "datetime": "date", "日期": "date",
        "open": "open", "开盘": "open",
        "close": "close", "收盘": "close", "adj close": "close",
        "high": "high", "最高": "high",
        "low": "low", "最低": "low",
        "volume": "volume", "成交量": "volume",
    }
    rename = {col: aliases.get(str(col).strip().lower(), aliases.get(str(col).strip(), str(col))) for col in df.columns}
    out = df.rename(columns=rename).copy()
    if "date" not in out.columns or "close" not in out.columns:
        raise ValueError(f"unexpected columns: {list(df.columns)}")
    # Duplicate columns can arise when both Close and Adj Close are present.
    out = out.loc[:, ~out.columns.duplicated(keep="first")]
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    start_iso = f"{start8[:4]}-{start8[4:6]}-{start8[6:]}"
    end_iso = f"{end8[:4]}-{end8[4:6]}-{end8[6:]}"
    out = out[(out["date"] >= start_iso) & (out["date"] <= end_iso)]
    for column in ("open", "high", "low"):
        if column not in out.columns:
            out[column] = out["close"]
    if "volume" not in out.columns:
        out["volume"] = 0
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date")
    out = out.drop_duplicates(subset=["date"], keep="last")
    if len(out) == 0:
        raise ValueError("no rows in requested date range")
    return out[["date", "open", "close", "high", "low", "volume"]].reset_index(drop=True)


def _fetch_tencent_kline(
    security: SecurityRef, start8: str, end8: str, adjust: str,
) -> pd.DataFrame:
    """Fetch one CN symbol without Tencent's unbounded start-year probe."""
    adjust = adjust if adjust in {"qfq", "hfq"} else ""
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    params = {
        "_var": f"kline_day{adjust}",
        "param": (
            f"{security.symbol},day,"
            f"{start8[:4]}-{start8[4:6]}-{start8[6:]},"
            f"{end8[:4]}-{end8[4:6]}-{end8[6:]},640,{adjust}"
        ),
        "r": "0.8205512681390605",
    }
    response = requests.get(url, params=params, timeout=(3.05, 8))
    response.raise_for_status()
    body = response.text
    payload = response.json() if body.lstrip().startswith("{") else json.loads(body[body.find("=") + 1 :])
    symbol_data = (payload.get("data") or {}).get(security.symbol) or {}
    preferred_key = f"{adjust}day" if adjust else "day"
    rows = symbol_data.get(preferred_key) or symbol_data.get("day") or symbol_data.get("qfqday") or symbol_data.get("hfqday") or []
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [row[:6] for row in rows],
        columns=["date", "open", "close", "high", "low", "volume"],
    )


def _fetch_yahoo_chart(security: SecurityRef, start8: str, end8: str) -> pd.DataFrame:
    """Fetch one US ticker from Yahoo's chart endpoint with a hard socket timeout."""
    start_day = date(int(start8[:4]), int(start8[4:6]), int(start8[6:]))
    end_day = date(int(end8[:4]), int(end8[4:6]), int(end8[6:])) + timedelta(days=1)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{security.symbol}"
    response = requests.get(
        url,
        params={
            "period1": int(time.mktime(start_day.timetuple())),
            "period2": int(time.mktime(end_day.timetuple())),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=(3.05, 8),
    )
    response.raise_for_status()
    result = ((response.json().get("chart") or {}).get("result") or [])
    if not result:
        return pd.DataFrame()
    item = result[0]
    timestamps = item.get("timestamp") or []
    quote_rows = ((item.get("indicators") or {}).get("quote") or [{}])[0]
    if not timestamps:
        return pd.DataFrame()
    size = len(timestamps)
    values = {
        name: list(quote_rows.get(name) or [None] * size)
        for name in ("open", "close", "high", "low", "volume")
    }
    return pd.DataFrame({
        "date": pd.to_datetime(timestamps, unit="s", utc=True).strftime("%Y-%m-%d"),
        **{name: (series + [None] * size)[:size] for name, series in values.items()},
    })


def fetch_price_frame(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    market: str | None = None,
    adjust: str = "qfq",
) -> PriceFrame:
    """Fetch one historical OHLCV series through a market-aware fallback chain."""
    security = resolve_security_ref(symbol, market)
    end8 = _date8(end_date, date.today())
    start8 = _date8(start_date, date.today() - timedelta(days=365))
    adjust = adjust if adjust in {"qfq", "hfq"} else ""
    attempts: list[str] = []

    def attempt(provider: str, loader) -> PriceFrame | None:
        try:
            frame = _standardize(loader(), start8, end8)
            return PriceFrame(security, provider, frame, tuple(attempts + [provider]))
        except Exception as exc:  # noqa: BLE001 - provider waterfall must continue
            attempts.append(f"{provider}({type(exc).__name__}: {exc})")
            return None

    if security.market == "US":
        result = attempt(
            "yahoo.chart",
            lambda: _fetch_yahoo_chart(security, start8, end8),
        )
        if result:
            return result
        start_iso = f"{start8[:4]}-{start8[4:6]}-{start8[6:]}"
        end_inclusive = date(int(end8[:4]), int(end8[4:6]), int(end8[6:])) + timedelta(days=1)
        result = attempt(
            "yfinance.download",
            lambda: yf.download(
                security.symbol,
                start=start_iso,
                end=end_inclusive.isoformat(),
                progress=False,
                auto_adjust=False,
                threads=False,
                timeout=10,
            ),
        )
        if result:
            return result
        result = attempt(
            "akshare.stock_us_daily",
            lambda: ak.stock_us_daily(symbol=security.symbol, adjust=adjust or "qfq"),
        )
        if result:
            return result
        raise PriceFetchError(security, attempts)

    # One bounded Tencent request works for A shares, ETFs and the common CN
    # indexes.  It avoids AkShare's unbounded get_tx_start_year/Sina probes.
    result = attempt(
        "tencent.kline",
        lambda: _fetch_tencent_kline(security, start8, end8, adjust),
    )
    if result:
        return result

    if security.kind == "etf":
        result = attempt(
            "akshare.fund_etf_hist_em",
            lambda: ak.fund_etf_hist_em(
                symbol=security.code,
                period="daily",
                start_date=start8,
                end_date=end8,
                adjust=adjust,
            ),
        )
        if result:
            return result
        result = attempt(
            "akshare.stock_zh_index_daily",
            lambda: ak.stock_zh_index_daily(symbol=security.symbol),
        )
        if result:
            return result

    if security.kind == "index":
        result = attempt(
            "akshare.stock_zh_index_daily",
            lambda: ak.stock_zh_index_daily(symbol=security.symbol),
        )
        if result:
            return result

    if security.kind in {"stock", "etf"}:
        result = attempt(
            "akshare.stock_zh_a_daily",
            lambda: ak.stock_zh_a_daily(
                symbol=security.symbol,
                start_date=start8,
                end_date=end8,
                adjust=adjust,
            ),
        )
        if result:
            return result
        result = attempt(
            "akshare.stock_zh_a_hist_tx",
            lambda: ak.stock_zh_a_hist_tx(
                symbol=security.symbol,
                start_date=start8,
                end_date=end8,
                adjust=adjust,
                timeout=8,
            ),
        )
        if result:
            return result
    raise PriceFetchError(security, attempts)

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

try:
    import akshare as ak  # type: ignore
except Exception:
    ak = None  # optional for US-only run


SECTOR_ETF_CN = {
    "技术硬件与设备": "512480",  # 半导体ETF (国证)
    "半导体与半导体生产设备": "512480",
    "资本货物": "512580",  # 环保ETF，不精确；资本货物暂无单一指数，用 HS300 兜底
    "汽车与汽车零部件": "516110",  # 汽车ETF
    "材料": "512400",  # 有色金属ETF
    "食品饮料与烟草": "512690",  # 酒ETF
    "食品、饮料与烟草": "512690",
    "媒体": "512980",  # 传媒ETF
    "运输": "512760",  # 芯片ETF兜底；运输用515790 光伏/电新？不对，保持 510300 兜底
    "商业和专业服务": "510300",
    "银行": "512800",  # 银行ETF
    "多元金融": "512800",
    "保险": "512800",
    "软件与服务": "515030",  # 新能源车ETF？软件应是 515230 软件ETF
    "制药、生物科技与生命科学": "512290",  # 生物医药ETF
    "医疗保健设备与服务": "512290",
    "能源": "159945",  # 能源ETF（广发深证）
    "公用事业": "159945",
    "房地产": "512200",  # 房地产ETF
    "消费服务": "159928",  # 消费ETF
    "零售业": "159928",
    "耐用消费品与服装": "159928",
    "家庭与个人用品": "159928",
    "电信服务": "515050",  # 5G ETF
    "技术硬件设备": "512480",
}

BENCHMARK_CN_DEFAULT = "sh000300"
BENCHMARK_US_DEFAULT = "SPY"

DATE_FMTS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d")


# -------------------- AKSHARE (CN 行情) --------------------
def _ak_cn_hist(symbol: str, start_date: str, end_date: str, *, retries: int = 4, sleep_s: float = 0.9):
    """
    CN 行情：akshare.stock_zh_a_daily (Sina 源，不走 push2his)
    symbol 为 6 位 A 股代码。自动补 sh/sz 前缀（6/9/5 开头 → sh；0/3/1/2 → sz）
    返回 Series: index=date, value=close
    重试 4 次 + sleep 0.9s
    """
    if ak is None:
        return None
    code = str(symbol or "").strip()
    if not (len(code) == 6 and code.isdigit()):
        return None
    first = code[0]
    if first in {"6", "9", "5"}:
        prefixed = f"sh{code}"
    elif first in {"0", "3", "1", "2"}:
        prefixed = f"sz{code}"
    else:
        prefixed = f"sh{code}"
    sd_d = dt.date.fromisoformat(start_date)
    ed_d = dt.date.fromisoformat(end_date)
    last_err = None
    for attempt in range(1, int(retries) + 1):
        try:
            time.sleep(sleep_s + 0.4 * (attempt - 1))
            # 主方案：stock_zh_a_daily (Sina, 前复权) —— 与 event_study_skill 对齐
            df = ak.stock_zh_a_daily(symbol=prefixed, adjust="qfq")
            ok_df = df is not None and len(df) > 0 and "date" in df.columns and "close" in df.columns
            # 备用：stock_zh_a_hist_tx (Tencent)
            if not ok_df and hasattr(ak, "stock_zh_a_hist_tx"):
                try:
                    sd_s = start_date.replace("-", "")
                    ed_s = end_date.replace("-", "")
                    df = ak.stock_zh_a_hist_tx(symbol=prefixed, start_date=sd_s, end_date=ed_s, adjust="qfq")
                    ok_df = df is not None and len(df) > 0 and "date" in df.columns and "close" in df.columns
                except Exception as e2:
                    last_err = e2
            if not ok_df:
                last_err = ValueError(f"empty cn resp len={0 if df is None else len(df)}")
                continue
            df["date"] = pd.to_datetime(df["date"]).dt.date
            s = df.set_index("date")["close"].sort_index().astype(float)
            s = s[~s.index.duplicated()]
            s = s[(s.index >= sd_d) & (s.index <= ed_d)]
            time.sleep(sleep_s * 0.5)
            return s
        except Exception as e:
            last_err = e
            msg = str(e)
            if "ProxyError" in msg or "RemoteDisconnected" in msg or "Connection aborted" in msg or "429" in msg or "Too Many" in msg:
                time.sleep(sleep_s * (1 + attempt))
                continue
            if attempt >= int(retries):
                print(f"[WARN] ak cn {symbol} ({prefixed}) err (attempt={attempt}): {type(e).__name__}: {e}")
            time.sleep(sleep_s)
    if last_err is not None:
        print(f"[WARN] ak cn {symbol} all attempts fail: {type(last_err).__name__}: {last_err}")
    return None


def _ak_cn_index_hist(benchmark_code: str, start_date: str, end_date: str, *, retries: int = 4, sleep_s: float = 1.0):
    """
    CN 指数：ak.stock_zh_index_daily(symbol="sh000300")；
    CN ETF：优先 fund_etf_hist_em，失败 fallback stock_zh_a_hist (走个股接口也能拉 ETF)。
    返回 Series date→close
    """
    if ak is None:
        return None
    code = str(benchmark_code or "").strip().lower()
    if not code:
        return None
    sd = start_date
    ed = end_date
    last_err = None
    # 先拆分: sh/sz + 6 root
    prefix = None; root = None
    if len(code) == 8 and code[:2] in {"sh", "sz"} and code[2:].isdigit():
        prefix = code[:2]; root = code[2:]
    if len(code) == 6 and code.isdigit():
        root = code
        prefix = "sz" if code.startswith(("15", "399")) else "sh"

    # ---- ETF 判定 ----
    def _is_etf(r):
        return r is not None and r[:2] in {"51", "56", "58", "15"}

    # ---- ETF 路径：优先 akshare fund_etf_hist_em，再 fallback _ak_cn_hist ----
    if _is_etf(root):
        # fund_etf_hist_em: symbol = 6位纯数字, 如 "510300"
        for attempt in range(1, int(retries) + 1):
            try:
                time.sleep(sleep_s + 0.4 * (attempt - 1))
                df = ak.fund_etf_hist_em(symbol=root, period="daily",
                                         start_date=sd.replace("-",""), end_date=ed.replace("-",""),
                                         adjust="qfq")
                if df is not None and len(df) > 0 and "收盘" in df.columns and "日期" in df.columns:
                    df["date"] = pd.to_datetime(df["日期"]).dt.date
                    s = df.set_index("date")["收盘"].sort_index().astype(float)
                    sd_d = dt.date.fromisoformat(sd); ed_d = dt.date.fromisoformat(ed)
                    s = s[(s.index >= sd_d) & (s.index <= ed_d)]
                    if len(s) > 0:
                        time.sleep(sleep_s * 0.5)
                        return s
                # fund_etf_hist_em 空 → fallback stock_zh_index_daily
                if prefix and root:
                    try:
                        df2 = ak.stock_zh_index_daily(symbol=f"{prefix}{root}")
                        if df2 is not None and len(df2) > 0 and "date" in df2.columns and "close" in df2.columns:
                            df2["date"] = pd.to_datetime(df2["date"]).dt.date
                            s2 = df2.set_index("date")["close"].sort_index().astype(float)
                            sd_d = dt.date.fromisoformat(sd); ed_d = dt.date.fromisoformat(ed)
                            s2 = s2[(s2.index >= sd_d) & (s2.index <= ed_d)]
                            if len(s2) > 0:
                                time.sleep(sleep_s * 0.5)
                                return s2
                    except Exception:
                        pass
                # 最后兜底走 _ak_cn_hist（个股接口，很多 ETF 也能查到）
                s3 = _ak_cn_hist(root, sd, ed, retries=1, sleep_s=0.2)
                if s3 is not None and len(s3) > 0:
                    return s3
                last_err = ValueError("etf all routes empty")
            except Exception as e:
                last_err = e
                msg = str(e)
                if "RemoteDisconnected" in msg or "Connection aborted" in msg or "429" in msg:
                    time.sleep(sleep_s * (1 + attempt)); continue
                if attempt >= int(retries):
                    print(f"[WARN] ak etf {code} err (attempt={attempt}): {type(e).__name__}: {e}")
                time.sleep(sleep_s)
        # 还是失败 → 再走一次 stock_zh_index_daily 兜底
        if prefix and root:
            s_idx = _ak_cn_index_hist_noetf(f"{prefix}{root}", sd, ed, retries=max(2, retries - 1), sleep_s=sleep_s)
            if s_idx is not None and len(s_idx) > 0:
                return s_idx
        if last_err is not None:
            print(f"[WARN] ak etf {code} all fail: {type(last_err).__name__}: {last_err}")
        return None

    # ---- 纯指数路径 (sh000300 / sz399006 / etc) ----
    if prefix and root:
        return _ak_cn_index_hist_noetf(f"{prefix}{root}", sd, ed, retries=retries, sleep_s=sleep_s)
    # 6 位纯数字兜底 → 当个股 ETF 走 _ak_cn_hist
    if len(code) == 6 and code.isdigit():
        return _ak_cn_hist(code, sd, ed, retries=retries, sleep_s=sleep_s)
    return None


def _ak_cn_index_hist_noetf(code: str, start_date: str, end_date: str, *, retries: int = 4, sleep_s: float = 1.0):
    """纯 index 接口：stock_zh_index_daily(symbol=sh000300 / sz399006)"""
    if ak is None:
        return None
    code = code.lower()
    sd, ed = start_date, end_date
    last_err = None
    if len(code) == 8 and code[:2] in {"sh", "sz"} and code[2:].isdigit():
        for attempt in range(1, int(retries) + 1):
            try:
                time.sleep(sleep_s + 0.4 * (attempt - 1))
                df = ak.stock_zh_index_daily(symbol=code)
                if df is None or len(df) == 0 or "date" not in df.columns:
                    last_err = ValueError("empty index resp"); continue
                df["date"] = pd.to_datetime(df["date"]).dt.date
                s = df.set_index("date")["close"].sort_index().astype(float)
                sd_d = dt.date.fromisoformat(sd); ed_d = dt.date.fromisoformat(ed)
                s = s[(s.index >= sd_d) & (s.index <= ed_d)]
                time.sleep(sleep_s * 0.6)
                return s
            except Exception as e:
                last_err = e
                msg = str(e)
                if "RemoteDisconnected" in msg or "Connection aborted" in msg or "429" in msg:
                    time.sleep(sleep_s * (1 + attempt)); continue
                if attempt >= int(retries):
                    print(f"[WARN] ak index {code} err (attempt={attempt}): {type(e).__name__}: {e}")
                time.sleep(sleep_s)
        if last_err is not None:
            print(f"[WARN] ak index {code} all fail: {type(last_err).__name__}: {last_err}")
    return None


def _ak_us_hist(symbol: str, start_date: str, end_date: str, *, retries: int = 4, sleep_s: float = 0.9):
    """
    US 行情：akshare.stock_us_daily
    symbol 为纯代码 (SPY/QQQ/AAPL 等)。返回 Series index=date, value=close
    重试 4 次 + sleep 0.9s
    """
    if ak is None:
        return None
    code = str(symbol or "").strip().upper()
    if not code:
        return None
    sd_d = dt.date.fromisoformat(start_date)
    ed_d = dt.date.fromisoformat(end_date)
    last_err = None
    for attempt in range(1, int(retries) + 1):
        try:
            time.sleep(sleep_s + 0.5 * (attempt - 1))
            df = ak.stock_us_daily(symbol=code, adjust="qfq")
            if df is None or len(df) == 0 or "date" not in df.columns or "close" not in df.columns:
                last_err = ValueError(f"empty us resp len={0 if df is None else len(df)}")
                continue
            df["date"] = pd.to_datetime(df["date"]).dt.date
            s = df.set_index("date")["close"].sort_index().astype(float)
            s = s[~s.index.duplicated()]
            s = s[(s.index >= sd_d) & (s.index <= ed_d)]
            time.sleep(sleep_s * 0.6)
            return s
        except Exception as e:
            last_err = e
            msg = str(e)
            if "ProxyError" in msg or "RemoteDisconnected" in msg or "Connection aborted" in msg or "429" in msg or "Too Many" in msg:
                time.sleep(sleep_s * (1 + attempt))
                continue
            if attempt >= int(retries):
                print(f"[WARN] ak us {symbol} err (attempt={attempt}): {type(e).__name__}: {e}")
            time.sleep(sleep_s)
    if last_err is not None:
        print(f"[WARN] ak us {symbol} all attempts fail: {type(last_err).__name__}: {last_err}")
    return None


def _parse_date(s) -> Optional[dt.date]:
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return None
    if isinstance(s, (dt.date, dt.datetime)):
        return s.date() if hasattr(s, "date") else s
    s = str(s).strip()
    if not s:
        return None
    for fmt in DATE_FMTS:
        try:
            return dt.datetime.strptime(s[: len(fmt) + 6], fmt).date()
        except Exception:
            continue
    try:
        return dt.datetime.fromisoformat(s).date()
    except Exception:
        return None


def _yf_ticker_for(symbol: str, market: str, benchmark: Optional[str]) -> str:
    """
    为 labeller 内部的「分类 + akshare 下载」统一返回 canonical ticker 格式：
      - CN 个股（60/68/000/002/300/920 等 6 位数字前缀）→ 保留 .SS/.SZ 后缀（走 Phase2 个股接口）
      - CN 指数 / ETF → 一律 小写 sh/sz + 6 位数字（走 Phase3 CN-index 接口），包括：
          * 输入本身带 SH/SZ 字母前缀
          * 6 位 ETF 数字前缀（51/56/58/15 开头）
          * 6 位指数代码（000/399/88 开头）
      - US → 原样大写
    """
    symbol = str(symbol or "").strip()
    if market == "CN":
        # 先剥字母前缀：SH510300 / sz399006 → (prefix, 6-digit root)
        s_low = symbol.lower()
        if s_low[:2] in {"sh", "sz"} and len(s_low) >= 8 and s_low[2:8].isdigit():
            return s_low[:8]  # sh510300 / sz399006
        if len(symbol) == 6 and symbol.isdigit():
            root = symbol
            # ---- 上证/深证 指数白名单 ----
            CN_INDEX_CODES = {
                "000001", "000016", "000300", "000905", "000852", "000688", "000010", "000009",
                "000015", "000017", "000018", "000019", "000020", "000021", "000022",
                "000023", "000024", "000025", "000026", "000027", "000028", "000029",
                "000030", "000031", "000032", "000033", "000034", "000035", "000036",
                "000037", "000038", "000039", "000040", "000041", "000042", "000043",
                "000044", "000045", "000046", "000047", "000048", "000049", "000050",
                "880001", "880472", "880813", "880434",
            }
            SZ_INDEX_CODES = {
                "399001", "399005", "399006", "399300", "399905", "399986", "399673", "399016",
            }
            # 6 位 ETF → 归一化成 sh/sz + 6 位
            if root.startswith(("51", "56", "58")):  # 沪市 ETF
                return f"sh{root}"
            if root.startswith(("15",)):             # 深市 ETF
                return f"sz{root}"
            if root in SZ_INDEX_CODES or root.startswith(("399",)):  # 深证指数
                return f"sz{root}"
            if root in CN_INDEX_CODES or root.startswith(("880", "881")):  # 上证指数
                return f"sh{root}"
            # 个股分支
            if root.startswith(("688", "600", "601", "603", "605", "900", "920")):
                return f"{root}.SS"
            if root.startswith(("002", "003", "001", "200", "300", "301", "000")):
                # 000 开头除了上面白名单指数，其他都是深市 A 股
                return f"{root}.SZ"
            # 未知 6 位默认走 CN-index 兜底
            return f"sh{root}"
        # 6/9 开头的个股（原始 6 位未带前缀常见形式）
        if symbol.isdigit() and len(symbol) >= 6:
            first = symbol[0]
            if first in {"6", "9", "5"}:
                return f"{symbol[:6]}.SS"
            if first in {"0", "3", "1", "2"}:
                return f"{symbol[:6]}.SZ"
        # benchmark fallback 兜底
        bm = str(benchmark or "").strip().lower()
        if bm in {"sh000300"}:
            return "sh000300"
        # 剩余完全未知 → 套 SS（当作个股处理），但保证不会变成 SH510300.SS 这种 10 字符
        stripped = symbol.replace("SH", "").replace("SZ", "").replace("sh", "").replace("sz", "")
        if len(stripped) >= 6 and stripped[:6].isdigit():
            # 用剥后的前 6 位走 SS/SZ 判定
            first = stripped[0]
            if first in {"6", "9", "5"}:
                return f"{stripped[:6]}.SS"
            if first in {"0", "3", "1", "2"}:
                return f"{stripped[:6]}.SZ"
            return f"sh{stripped[:6]}"
        return f"{symbol}.SS"
    if market == "US":
        return symbol.upper()
    return symbol.upper()


def _yf_benchmark_for(benchmark: Optional[str], market: str) -> str:
    bm = str(benchmark or "").strip().lower()
    if market == "CN":
        # 先处理 akshare 指数直连形式：sh/sz + 6 位代码（不再强制转 ETF 代理，ETF 代理实际常缺数据）
        if len(bm) == 8 and bm[:2] in {"sh", "sz"} and bm[2:].isdigit():
            return benchmark  # 原样：sh000300 / sz399006 等 → cn_index_map 处理 → _ak_cn_index_hist 通
        if bm in {"sh000300", "sz399300", "399300"}:
            return "sh000300"  # 沪深300 指数代码（ak.stock_zh_index_daily），不绕 ETF 510300.SS
        # 形如 sz399001 / sh000001 等老指数代码无 sh/sz 前缀的：如果是 6 位纯数字 → 如果是 000/399 开头指数补 sz，000001 可 sh；默认返回已知格式；未知 6 位纯数字：先走 CN 指数分支再兜底
        if len(bm) == 6 and bm.isdigit():
            # 399xxx 深证指数；000xxx 上证指数；000300 特殊=沪深300
            if bm.startswith("399"):
                return f"sz{bm}"
            if bm.startswith("000") or bm.startswith("688"):
                return f"sh{bm}"
            # 其他 6 位 → 可能是 ETF 代码（51xxxx / 15xxxx / 56xxxx）；当 CN-asset 走 _ak_cn_hist
            return bm.upper()
        # 还没命中 → 默认沪深300指数 sh000300
        return "sh000300"
    # US
    if bm in {"spy", "qqq", "dji", "iwm"}:
        return benchmark.upper()
    return "SPY"


@dataclass
class RawEvent:
    event_id: str
    market: str
    symbol: str
    event_date: dt.date
    event_type_l2: str = ""
    benchmark: Optional[str] = None
    event_time_raw: str = ""


def load_events(path) -> list[RawEvent]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            d = json.loads(s)
            ed = _parse_date(d.get("event_time"))
            if ed is None:
                continue
            rows.append(
                RawEvent(
                    event_id=str(d.get("event_id") or ""),
                    market=str(d.get("market") or ""),
                    symbol=str(d.get("symbol") or ""),
                    event_date=ed,
                    event_type_l2=str(d.get("event_type_l2") or ""),
                    benchmark=d.get("benchmark"),
                    event_time_raw=str(d.get("event_time") or ""),
                )
            )
    return rows


def _fetch_yf_batch(tickers: Iterable[str], start: dt.date, end: dt.date) -> dict[str, pd.Series]:
    """
    yfinance download for many tickers; return {ticker: close_series (date indexed)}
    新增：如果 batch YFRateLimitError，就拆成逐只下载（每只 sleep 1s）
    """
    ticks = sorted({t for t in tickers if t})
    if not ticks:
        return {}
    # yfinance end is exclusive, pad 2 days to ensure coverage
    end_pad = end + dt.timedelta(days=3)
    out: dict[str, pd.Series] = {}
    try:
        df = yf.download(
            tickers=ticks,
            start=start.isoformat(),
            end=end_pad.isoformat(),
            auto_adjust=False,
            progress=False,
            group_by="Ticker",
            threads=min(8, max(1, len(ticks) // 4)),
        )
    except Exception as e:
        print(f"[WARN] yf.download batch err: {type(e).__name__}: {e} -> fallback to per-ticker")
        df = None
    if df is not None:
        if len(ticks) == 1:
            t = ticks[0]
            if isinstance(df, pd.DataFrame) and "Close" in df.columns:
                s = df["Close"]
                s.index = pd.to_datetime(s.index).date
                out[t] = s.astype(float)
        else:
            for t in ticks:
                try:
                    sub = df[t] if t in df.columns.get_level_values(0) else df.xs(t, axis=1, level=0)
                    if isinstance(sub, pd.DataFrame) and "Close" in sub.columns:
                        s = sub["Close"].dropna()
                        s.index = pd.to_datetime(s.index).date
                        if len(s) > 0:
                            out[t] = s.astype(float)
                except Exception:
                    continue
    # 对于 batch 没拿到的 ticker，单独逐只下载（避免 rate-limit 封掉整批）
    missing = [t for t in ticks if t not in out or len(out.get(t, [])) == 0]
    if missing:
        print(f"[INFO] yfinance batch missing {len(missing)} tickers -> per-ticker fallback (sleep 1.6s each)")
        for idx, t in enumerate(missing):
            # 更长 sleep + 最多 3 次指数退避重试
            ok = False
            for attempt in range(1, 4):
                try:
                    d2 = yf.download(
                        tickers=[t],
                        start=start.isoformat(),
                        end=end_pad.isoformat(),
                        auto_adjust=False,
                        progress=False,
                        threads=1,
                    )
                    if isinstance(d2, pd.DataFrame) and "Close" in d2.columns:
                        s = d2["Close"].dropna()
                        if len(s) > 0:
                            s.index = pd.to_datetime(s.index).date
                            out[t] = s.astype(float)
                            ok = True
                    if ok:
                        break
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    print(f"[WARN] yf per-ticker {t} attempt={attempt} err: {msg}")
                    bo = (2.0 ** (attempt - 1)) * 2.1
                    time.sleep(bo)
                    continue
                # 没抛异常但也没拿到数据：再等一次长 sleep
                time.sleep(1.3 + 0.4 * attempt)
            time.sleep(1.6 if ok else 3.4)
    return out


def _announcement_tier(event_time_str: str, market: str) -> str:
    """
    判断公告时段：返回 "pre_open" / "intraday" / "post_close"
    - CN: pre_open < 09:30, intraday = [09:30, 15:00), post_close >= 15:00
    - US: pre_open < 09:30, intraday = [09:30, 16:00), post_close >= 16:00
    - 无时间组件 / 不可解析 -> "intraday"（最安全，不偏移 T0）
    """
    s = str(event_time_str or "").strip()
    if not s:
        return "intraday"
    # 检测是否含时间组件：ISO datetime 用 'T' 分隔；也兼容空格分隔的 "YYYY-MM-DD HH:MM:SS"
    # date-only 如 "2025-01-10" / "20250110" / "2025/01/10" -> 当作无时间组件
    has_time = ("T" in s) or ("t" in s) or (len(s) > 10 and ":" in s[10:])
    if not has_time:
        return "intraday"
    t = None
    try:
        obj = dt.datetime.fromisoformat(s)
        t = obj.time()
    except Exception:
        # 不可解析 -> 当作无时间组件
        return "intraday"
    if t is None:
        return "intraday"
    mkt = (market or "").upper()
    if mkt == "CN":
        open_t = dt.time(9, 30)
        close_t = dt.time(15, 0)
    else:  # US / 未知 -> 用 US 时间
        open_t = dt.time(9, 30)
        close_t = dt.time(16, 0)
    if t < open_t:
        return "pre_open"
    if t >= close_t:
        return "post_close"
    return "intraday"


def _car(closes: pd.Series, event_date: dt.date, window: int,
         event_time_raw: str = "", market: str = "") -> Optional[float]:
    """
    event-t0 = 收盘前发布公告 -> 用 event_date 当天 close 作为基准；
    horizon = T+N 的 close。
    若公告时段为 post_close -> T0 顺延到下一个交易日。
    """
    if closes is None or len(closes) == 0:
        return None
    dates_avail = sorted(closes.index)
    # pick first trading date >= event_date
    t0_candidates = [d for d in dates_avail if d >= event_date]
    if not t0_candidates:
        return None
    t0 = t0_candidates[0]
    t0_idx = dates_avail.index(t0)
    # post_close 公告：市场反应发生在下一交易日
    if _announcement_tier(event_time_raw, market) == "post_close":
        if t0_idx + 1 >= len(dates_avail):
            return None
        t0 = dates_avail[t0_idx + 1]
        t0_idx = t0_idx + 1
    tN_idx = t0_idx + window
    if tN_idx >= len(dates_avail):
        return None
    p0 = float(closes.loc[t0])
    pN = float(closes.loc[dates_avail[tN_idx]])
    if not p0 or not math.isfinite(p0) or not math.isfinite(pN):
        return None
    return (pN / p0) - 1.0


def _market_model_car(stock_closes: pd.Series, index_closes: pd.Series,
                      event_date: dt.date, window: int,
                      event_time_raw: str = "", market: str = ""
                      ) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    市场模型 CAR（OLS 估计 α/β，替代 β≡1 的简单减法）：
    - T0 同 _car 的 post_close 偏移规则
    - 估计窗口: [T0-120, T0-21] 交易日（100 个）
    - 事件窗口: [T0, T0+window]，AR_t = r_stock_t - (α̂ + β̂ * r_index_t)
    - CAR = Σ AR_t（共 window+1 项）
    - σ(AR) 取自估计窗口残差
    - t_stat = CAR / (σ_AR * sqrt(window+1))
    - p_value = 2 * (1 - Φ(|t_stat|))，Φ 用 math.erf 近似
    - 估计窗口数据 < 30 -> 退回端点法 CAR = (pN/p0 - 1) - (bmN/bm0 - 1)，t_stat=p_value=None
    - 数据缺失 -> 返回 (None, None, None)
    """
    empty: tuple[Optional[float], Optional[float], Optional[float]] = (None, None, None)
    if stock_closes is None or index_closes is None or len(stock_closes) == 0 or len(index_closes) == 0:
        return empty

    tier = _announcement_tier(event_time_raw, market)
    dates_avail = sorted(stock_closes.index)
    t0_candidates = [d for d in dates_avail if d >= event_date]
    if not t0_candidates:
        return empty
    t0 = t0_candidates[0]
    t0_idx = dates_avail.index(t0)
    if tier == "post_close":
        if t0_idx + 1 >= len(dates_avail):
            return empty
        t0 = dates_avail[t0_idx + 1]
        t0_idx = t0_idx + 1
    tN_idx = t0_idx + window
    if tN_idx >= len(dates_avail):
        return empty

    def _fallback_endpoint() -> tuple[Optional[float], Optional[float], Optional[float]]:
        r_a = _car(stock_closes, event_date, window, event_time_raw, market)
        r_b = _car(index_closes, event_date, window, event_time_raw, market)
        if r_a is None or r_b is None:
            return empty
        return (r_a - r_b, None, None)

    # 估计窗口 [t0_idx-120, t0_idx-21] 闭区间（100 个交易日）
    est_lo = t0_idx - 120
    est_hi = t0_idx - 21  # inclusive
    if est_hi < 0:
        return _fallback_endpoint()
    est_lo_c = max(0, est_lo)
    if est_hi < est_lo_c:
        return _fallback_endpoint()
    est_dates = dates_avail[est_lo_c : est_hi + 1]
    if len(est_dates) < 30:
        return _fallback_endpoint()

    # 对齐 stock / index 收盘价
    stock_est = stock_closes.reindex(est_dates).dropna()
    index_est = index_closes.reindex(est_dates).dropna()
    common = stock_est.index.intersection(index_est.index)
    if len(common) < 30:
        return _fallback_endpoint()
    stock_est = stock_est.loc[common]
    index_est = index_est.loc[common]
    r_stock_est = stock_est.pct_change().dropna()
    r_index_est = index_est.pct_change().dropna()
    common2 = r_stock_est.index.intersection(r_index_est.index)
    if len(common2) < 30:
        return _fallback_endpoint()
    r_stock_arr = r_stock_est.loc[common2].to_numpy(dtype=float)
    r_index_arr = r_index_est.loc[common2].to_numpy(dtype=float)

    # OLS: r_stock = α + β * r_index (numpy.polyfit degree=1)
    try:
        beta, alpha = np.polyfit(r_index_arr, r_stock_arr, 1)
    except Exception:
        return _fallback_endpoint()
    if not (math.isfinite(float(alpha)) and math.isfinite(float(beta))):
        return _fallback_endpoint()
    pred = alpha + beta * r_index_arr
    resid = r_stock_arr - pred
    if len(resid) < 2:
        return _fallback_endpoint()
    sigma_ar = float(np.std(resid, ddof=1))
    if not math.isfinite(sigma_ar) or sigma_ar <= 0.0:
        return _fallback_endpoint()

    # 事件窗口 [T0, T0+window] -> 需要 window+1 个 AR -> 收盘价 T0-1 ~ T0+window（共 window+2 个）
    if t0_idx - 1 < 0:
        return _fallback_endpoint()
    ev_price_dates = dates_avail[t0_idx - 1 : tN_idx + 1]
    if len(ev_price_dates) < window + 2:
        return _fallback_endpoint()
    stock_ev = stock_closes.reindex(ev_price_dates).dropna()
    index_ev = index_closes.reindex(ev_price_dates).dropna()
    common_ev = stock_ev.index.intersection(index_ev.index)
    if len(common_ev) < window + 2:
        return _fallback_endpoint()
    stock_ev = stock_ev.loc[common_ev]
    index_ev = index_ev.loc[common_ev]
    r_stock_ev = stock_ev.pct_change().dropna().to_numpy(dtype=float)  # window+1 returns
    r_index_ev = index_ev.pct_change().dropna().to_numpy(dtype=float)
    if len(r_stock_ev) != window + 1 or len(r_index_ev) != window + 1:
        return _fallback_endpoint()
    ar_ev = r_stock_ev - (alpha + beta * r_index_ev)
    car = float(np.sum(ar_ev))
    denom = sigma_ar * math.sqrt(window + 1)
    if not math.isfinite(denom) or denom <= 0:
        return car, None, None
    t_stat = car / denom
    # p_value = 2 * (1 - Φ(|t|))，Φ 用 math.erf 近似
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))
    if p_value < 0.0:
        p_value = 0.0
    elif p_value > 1.0:
        p_value = 1.0
    return car, float(t_stat), float(p_value)


def _compute_cars_for_events(
    events: list[RawEvent],
) -> dict[tuple, dict]:
    """
    returns: {(event_id, market, symbol): {
        "t1": float|None, "t3": float|None, "t5": float|None,
        "bm_t1": ..., "bm_t3": ..., "bm_t5": ...,
        "car_t1": ..., "car_t3": ..., "car_t5": ...,
        "asset_ticker": str, "benchmark_ticker": str,
    }}
    """
    asset_tickers = {}
    bm_tickers = {}
    for e in events:
        asset_tickers[(e.event_id, e.market, e.symbol)] = _yf_ticker_for(e.symbol, e.market, e.benchmark)
        bm_tickers[(e.event_id, e.market, e.symbol)] = _yf_benchmark_for(e.benchmark, e.market)

    all_tickers = set(asset_tickers.values()) | set(bm_tickers.values())
    # expand download window: 200 calendar days before earliest event (estimation window needs ~120 trading days),
    # latest event_date + 150 days for up to T+60 horizon (≈84 trading days ≈ 120 calendar days)
    if not events:
        return {}
    earliest = min(e.event_date for e in events) - dt.timedelta(days=200)
    latest = max(e.event_date for e in events) + dt.timedelta(days=150)
    sd_iso = earliest.isoformat()
    ed_iso = latest.isoformat()

    print(f"[INFO] Close universe: {len(all_tickers)} tickers; window {sd_iso} ~ {ed_iso}")
    closes_by_ticker: dict[str, pd.Series] = {}

    # ===== 分类 =====
    # US 资产（非 .SS/.SZ 的非 9 位格式，例如 SPY, QQQ, AAPL, NFLX, AMZN）
    us_map: dict[str, str] = {}
    # CN 个股（600519.SS / 000001.SZ → 6 位纯数字 root，给 stock_zh_a_hist）
    cn_asset_map: dict[str, str] = {}
    # CN 指数 / ETF（sh000300 / sz399006 / 6 位纯数字 ETF，给 stock_zh_index_daily 或 ETF hist）
    cn_index_map: dict[str, str] = {}

    for t in all_tickers:
        tl = t.lower()
        # ---- CN 指数/ETF 的显式形式（先判，避免 SH510300.SS 被兜底到 US）----
        # 情形 A: sh510300 / sz399006 标准 8 字符
        if len(tl) == 8 and tl[:2] in {"sh", "sz"} and tl[2:].isdigit():
            cn_index_map[t] = tl
            continue
        # 情形 B: SH510300.SS / sh510300.sz → 剥前缀剥后缀拿 6 位 root，若 ETF/指数前缀走 CN-index
        stripped_suf = tl
        if stripped_suf.endswith(".ss"):
            stripped_suf = stripped_suf[:-3]
        elif stripped_suf.endswith(".sz"):
            stripped_suf = stripped_suf[:-3]
        # 剥完后如果是 sh/sz+6数字 → 直接当指数
        if len(stripped_suf) == 8 and stripped_suf[:2] in {"sh", "sz"} and stripped_suf[2:].isdigit():
            cn_index_map[t] = stripped_suf
            continue
        # ---- CN 个股标准形式：600519.SS / 000001.SZ （root 6 位纯数 + .SS/.SZ，root 非 ETF 前缀）----
        if (t.endswith(".SS") or t.endswith(".SZ")) and len(t) == 9 and t[:6].isdigit():
            root = t[:6]
            # 如果 root 是 ETF 前缀（51/56/58 沪ETF；15 深ETF；399 深指数；88x 指数），改走 CN-index
            if root.startswith(("51", "56", "58", "15")) or root.startswith(("399", "880", "881")):
                prefix = "sh" if root[0] in {"5", "8"} else "sz"
                if root.startswith("15") or root.startswith("399"):
                    prefix = "sz"
                cn_index_map[t] = f"{prefix}{root}"
                continue
            cn_asset_map[t] = root
            continue
        # ---- 6 位纯数字 → 当指数/ETF 处理
        if len(t) == 6 and t.isdigit():
            cn_index_map[t] = t
            continue
        # ---- 其他非 .SS/.SZ 格式 → US
        us_map[t] = t

    n_tot = len(all_tickers)
    print(f"[INFO] 分类结果: US={len(us_map)} CN-asset={len(cn_asset_map)} CN-index={len(cn_index_map)}  total={len(us_map)+len(cn_asset_map)+len(cn_index_map)}")

    # ===== Phase 1: akshare US =====
    if us_map:
        n_ok = 0
        n_tot_us = len(us_map)
        for idx, (canonical, sym) in enumerate(us_map.items(), 1):
            s = _ak_us_hist(sym, sd_iso, ed_iso)
            if s is not None and len(s) > 0:
                closes_by_ticker[canonical] = s
                n_ok += 1
            if idx % 10 == 0 or idx == n_tot_us:
                print(f"[PROG] Phase1-US {idx}/{n_tot_us}  ok={n_ok}  cum={len(closes_by_ticker)}/{n_tot}")
        print(f"[INFO] Phase1 akshare US: ok={n_ok}/{n_tot_us}   (total cum {len(closes_by_ticker)}/{n_tot})")

    # ===== Phase 2: akshare CN 个股 =====
    if cn_asset_map:
        n_ok = 0
        n_tot_cn = len(cn_asset_map)
        for idx, (canonical, sym) in enumerate(cn_asset_map.items(), 1):
            s = _ak_cn_hist(sym, sd_iso, ed_iso)
            if s is not None and len(s) > 0:
                closes_by_ticker[canonical] = s
                n_ok += 1
            if idx % 20 == 0 or idx == n_tot_cn:
                print(f"[PROG] Phase2-CN-asset {idx}/{n_tot_cn}  ok={n_ok}  cum={len(closes_by_ticker)}/{n_tot}")
        print(f"[INFO] Phase2 akshare CN-asset: ok={n_ok}/{n_tot_cn}   (total cum {len(closes_by_ticker)}/{n_tot})")

    # ===== Phase 3: akshare CN 指数/ETF =====
    if cn_index_map:
        n_ok = 0
        n_tot_ci = len(cn_index_map)
        for idx, (canonical, sym) in enumerate(cn_index_map.items(), 1):
            s = _ak_cn_index_hist(sym, sd_iso, ed_iso)
            if s is not None and len(s) > 0:
                closes_by_ticker[canonical] = s
                n_ok += 1
            if idx % 10 == 0 or idx == n_tot_ci:
                print(f"[PROG] Phase3-CN-index {idx}/{n_tot_ci}  ok={n_ok}  cum={len(closes_by_ticker)}/{n_tot}")
        print(f"[INFO] Phase3 akshare CN-index: ok={n_ok}/{n_tot_ci}   (total cum {len(closes_by_ticker)}/{n_tot})")

    print(f"[INFO] Final close coverage (akshare-only): {len(closes_by_ticker)}/{n_tot} tickers")

    out: dict[tuple, dict] = {}
    no_asset = 0
    no_bm = 0
    HORIZONS: list[tuple[int, str]] = [(1, "t1"), (3, "t3"), (5, "t5"), (7, "t7"), (15, "t15"), (30, "t30"), (60, "t60")]
    for e in events:
        key = (e.event_id, e.market, e.symbol)
        at = asset_tickers[key]
        bt = bm_tickers[key]
        a_close = closes_by_ticker.get(at)
        b_close = closes_by_ticker.get(bt)
        rec: dict = {
            "asset_ticker": at, "benchmark_ticker": bt,
        }
        # initialize horizons
        for _, kn in HORIZONS:
            rec[kn] = None
            rec[f"bm_{kn}"] = None
            rec[f"car_{kn}"] = None
            rec[f"car_{kn}_tstat"] = None
            rec[f"car_{kn}_pvalue"] = None
        if a_close is None:
            no_asset += 1
        if b_close is None:
            no_bm += 1
        for w, key_name in HORIZONS:
            r_a = _car(a_close, e.event_date, w, e.event_time_raw, e.market) if a_close is not None else None
            r_b = _car(b_close, e.event_date, w, e.event_time_raw, e.market) if b_close is not None else None
            rec[key_name] = r_a
            rec[f"bm_{key_name}"] = r_b
            if a_close is not None and b_close is not None:
                car, t_stat, p_value = _market_model_car(
                    a_close, b_close, e.event_date, w, e.event_time_raw, e.market
                )
                rec[f"car_{key_name}"] = car
                rec[f"car_{key_name}_tstat"] = t_stat
                rec[f"car_{key_name}_pvalue"] = p_value
        out[key] = rec
    if no_asset or no_bm:
        print(f"[WARN] Missing closes: asset={no_asset}, benchmark={no_bm}")
    return out


def _label_from_car(car: Optional[float], epsilon: float) -> str:
    if car is None or not math.isfinite(car):
        return ""
    if car > epsilon:
        return "up"
    if car < -epsilon:
        return "down"
    return "neutral"


def write_labels(events: list[RawEvent], cars: dict, out_path, epsilon: float = 0.005):
    HORIZONS_DIR: list[str] = ["t1", "t3", "t5", "t7", "t15", "t30", "t60"]
    # horizons used for "direction evidence" aggregations (exclude t1 which is too noisy)
    AGG_H: list[str] = ["t3", "t7", "t15", "t30", "t60"]

    def _sign(x: Optional[float]) -> int:
        if x is None or not math.isfinite(x): return 0
        if x > epsilon: return 1
        if x < -epsilon: return -1
        return 0

    def _mean_nonnull(vals: list[Optional[float]]) -> Optional[float]:
        xs = [v for v in vals if v is not None and math.isfinite(v)]
        if not xs: return None
        return float(sum(xs) / len(xs))

    def _weighted_mean_nonnull(vals: list[tuple[Optional[float], float]]) -> Optional[float]:
        total = 0.0; weight = 0.0
        for v, w in vals:
            if v is not None and math.isfinite(v):
                total += v * w; weight += w
        if weight <= 0: return None
        return total / weight

    rows = []
    for e in events:
        key = (e.event_id, e.market, e.symbol)
        c = cars.get(key) or {}
        p_t3 = c.get("car_t3_pvalue")
        sig_t3 = bool(p_t3 is not None and p_t3 < 0.10)

        row: dict = {
            "event_id": e.event_id,
            "market": e.market,
            "symbol": e.symbol,
            "event_time": e.event_date.isoformat(),
            "event_type_l2": e.event_type_l2,
        }
        # ---- horizon fields (ret / bm_ret / car / car_pvalue for each) ----
        for kn in HORIZONS_DIR:
            row[f"ret_{kn}"] = c.get(kn)
            row[f"bm_ret_{kn}"] = c.get(f"bm_{kn}")
            row[f"car_{kn}"] = c.get(f"car_{kn}")
            row[f"car_{kn}_pvalue"] = c.get(f"car_{kn}_pvalue")
        row["sig_t3"] = sig_t3

        # ---- individual horizon labels (compatibility) ----
        for kn in HORIZONS_DIR:
            row[f"label_{kn}"] = _label_from_car(c.get(f"car_{kn}"), epsilon)

        # ---- aggregations: avgCARs across non-t1 horizons ----
        # short (t3,t7), mid (t3,t7,t15), long (t15,t30,t60), all (t3,t7,t15,t30,t60)
        cars_short = [c.get(f"car_{h}") for h in ["t3", "t7"]]
        cars_mid = [c.get(f"car_{h}") for h in ["t3", "t7", "t15"]]
        cars_long = [c.get(f"car_{h}") for h in ["t15", "t30", "t60"]]
        cars_all = [c.get(f"car_{h}") for h in AGG_H]

        row["car_avg_short"] = _mean_nonnull(cars_short)
        row["car_avg_mid"] = _mean_nonnull(cars_mid)
        row["car_avg_long"] = _mean_nonnull(cars_long)
        # all-horizon weighted avg: nearer horizons get slightly more weight (we care most
        # about short-term reaction, but want long-term direction consistency to smooth noise)
        row["car_avg_all"] = _weighted_mean_nonnull(list(zip(
            cars_all,
            [0.35, 0.28, 0.20, 0.12, 0.05],  # weights sum=1.0; t3=0.35 t7=0.28 t15=0.20 t30=0.12 t60=0.05
        )))

        # how many of the 5 AGG horizons actually have valid CAR
        n_valid = sum(1 for v in cars_all if v is not None and math.isfinite(v))
        row["n_horizons_valid"] = n_valid

        # direction consensus signals (among AGG_H with valid sign)
        signs = [s for s in [_sign(c.get(f"car_{h}")) for h in AGG_H] if s != 0]
        row["n_horizons_signed"] = len(signs)
        if signs:
            up_cnt = sum(1 for s in signs if s > 0)
            down_cnt = sum(1 for s in signs if s < 0)
            maj = max(up_cnt, down_cnt)
            row["consensus_up_frac"] = (up_cnt / len(signs)) if signs else None
            row["consensus_down_frac"] = (down_cnt / len(signs)) if signs else None
            # max direction agreement: 1.0 = all same sign
            row["consensus_maj_frac"] = (maj / len(signs)) if signs else None
            # -1..+1 net: up_frac - down_frac; used as stable direction evidence
            row["consensus_net"] = ((up_cnt - down_cnt) / len(signs)) if signs else None
        else:
            row["consensus_up_frac"] = None
            row["consensus_down_frac"] = None
            row["consensus_maj_frac"] = None
            row["consensus_net"] = None

        # avg-based labels (the new "Oracle direction" for scoring / training)
        row["label_avg_short"] = _label_from_car(row["car_avg_short"], epsilon)
        row["label_avg_mid"] = _label_from_car(row["car_avg_mid"], epsilon)
        row["label_avg_long"] = _label_from_car(row["car_avg_long"], epsilon)
        row["label_avg_all"] = _label_from_car(row["car_avg_all"], epsilon)
        # label by strict consensus (>=66% horizons agree in same direction; else neutral)
        if signs and (row.get("consensus_maj_frac") or 0.0) >= 0.66 and row.get("consensus_net") is not None:
            net = row["consensus_net"]
            if net > 0: row["label_consensus66"] = "up"
            elif net < 0: row["label_consensus66"] = "down"
            else: row["label_consensus66"] = "neutral"
        else:
            row["label_consensus66"] = "neutral"

        rows.append(row)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(f"[INFO] labels written -> {out_path} ({len(rows)} rows)")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True, help="events_phase1.jsonl")
    ap.add_argument("--out", required=True, help="labels.jsonl")
    ap.add_argument("--epsilon", type=float, default=0.005, help="neutral threshold for label (default 0.5%)")
    args = ap.parse_args()

    events = load_events(args.events)
    print(f"[INFO] loaded {len(events)} events from {args.events}")
    if not events:
        raise SystemExit("no events")
    cars = _compute_cars_for_events(events)
    _rows = write_labels(events, cars, args.out, epsilon=float(args.epsilon))
    # summary stats
    mkt = Counter(e.market for e in events)
    def _lc(name): return Counter(r[name] for r in _rows if r.get(name))
    print(f"[INFO] market: {dict(mkt)}")
    for ln in ["label_t3", "label_t7", "label_t15", "label_t30", "label_t60",
               "label_avg_short", "label_avg_mid", "label_avg_long", "label_avg_all", "label_consensus66"]:
        dist = dict(_lc(ln))
        if dist: print(f"[INFO] {ln} distribution (eps={args.epsilon}): {dist}")
    # horizon coverage
    for h in ["t3", "t7", "t15", "t30", "t60"]:
        nv = sum(1 for r in _rows if r.get(f"car_{h}") is not None)
        print(f"[INFO] car_{h} coverage: {nv}/{len(_rows)} ({nv*100//len(_rows) if _rows else 0}%)")
    n_valid_stats = Counter(r["n_horizons_valid"] for r in _rows)
    print(f"[INFO] n_horizons_valid distribution: {dict(sorted(n_valid_stats.items()))}")
    # avgCAR stats
    for name in ["car_avg_short", "car_avg_mid", "car_avg_long", "car_avg_all"]:
        vs = [r[name] for r in _rows if r.get(name) is not None]
        if vs:
            arr = np.array(vs, dtype=float) * 10000  # → bps
            print(f"[INFO] {name} (bps): n={len(arr)} mean={arr.mean():+.1f} med={np.median(arr):+.1f} std={arr.std():.0f} p5={np.percentile(arr,5):.0f} p95={np.percentile(arr,95):.0f}")
    # cross-label agreement: label_t3 vs label_avg_all
    agree = sum(1 for r in _rows if r.get("label_t3") and r.get("label_avg_all") and r["label_t3"] == r["label_avg_all"])
    total_both = sum(1 for r in _rows if r.get("label_t3") and r.get("label_avg_all"))
    if total_both:
        print(f"[INFO] label_t3 <-> label_avg_all 方向一致性: {agree}/{total_both} = {agree*100//total_both}%")
    print("DONE_LABELS")


if __name__ == "__main__":
    main()

"""News & disclosure skills: get_stock_news / get_global_news / get_announcements.

Whitelisted sources only (design.md §2):
  akshare.stock_news_em / akshare.stock_info_global_em (+ news_economic_baidu fallback)
  / akshare.stock_notice_report
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import akshare as ak

from . import cache
from .market import norm_date
from .registry import err, meta, ok, skill


def _clip(s, n=150):
    s = "" if s is None else str(s).replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


@skill(
    "get_stock_news",
    "获取个股最近新闻（东方财富），含发布时间/标题/内容摘要/链接。symbol 为6位代码。",
    {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "6位股票代码，如 600519"},
            "limit": {"type": "integer", "description": "条数，≤10，默认 8"},
        },
        "required": ["symbol"],
    },
    internal=True,
)
@cache.cached("news")
def get_stock_news(symbol: str, limit: int = 8) -> dict:
    try:
        code = "".join(ch for ch in str(symbol) if ch.isdigit())[-6:]
        if len(code) != 6:
            return err(f"无法识别股票代码: {symbol}")
        limit = max(1, min(int(limit or 8), 10))
        df = ak.stock_news_em(symbol=code)
        if df is None or len(df) == 0:
            return ok([], meta("akshare.stock_news_em", 0)) | {"note": f"{code} 近期无新闻"}
        df = df.head(limit)
        items = []
        for _, r in df.iterrows():
            items.append({
                "title": _clip(r.get("新闻标题"), 120),
                "date": str(r.get("发布时间") or "")[:19],
                "source": f"akshare.stock_news_em · {r.get('文章来源') or ''}".strip(),
                "url": r.get("新闻链接") or None,
                "snippet": _clip(r.get("新闻内容"), 200),
            })
        artifact = {
            "kind": "evidence",
            "title": f"{code} 个股新闻（{len(items)} 条）",
            "payload": {"items": items},
        }
        return ok(items, meta("akshare.stock_news_em", len(items)), artifact=artifact)
    except Exception as e:  # noqa: BLE001
        return err(f"个股新闻获取失败: {type(e).__name__}: {e}")


@skill(
    "get_global_news",
    "获取全局财经快讯/要闻（不限个股），适合宏观与市场热点扫描。",
    {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "条数，≤20，默认 15"}},
        "required": [],
    },
    internal=True,
)
@cache.cached("news")
def get_global_news(limit: int = 15) -> dict:
    limit = max(1, min(int(limit or 15), 20))
    try:
        # 首选：东财全球快讯（含链接）
        try:
            df = ak.stock_info_global_em()
            if df is None or len(df) == 0:
                raise ValueError("空数据")
            df = df.head(limit)
            items = [{
                "title": _clip(r.get("标题"), 120),
                "date": str(r.get("发布时间") or "")[:19],
                "source": "akshare.stock_info_global_em",
                "url": r.get("链接") or None,
                "snippet": _clip(r.get("摘要"), 200),
            } for _, r in df.iterrows()]
            return ok(
                items,
                meta("akshare.stock_info_global_em", len(items)),
                artifact={"kind": "evidence", "title": f"全球财经快讯（{len(items)} 条）",
                          "payload": {"items": items}},
            )
        except Exception:
            # fallback：百度财经经济日历
            df = ak.news_economic_baidu()
            if df is None or len(df) == 0:
                return err("全局新闻为空")
            df = df.tail(limit).iloc[::-1]
            items = [{
                "title": _clip(f"【{r.get('地区') or ''}】{r.get('事件') or ''}", 120),
                "date": f"{r.get('日期') or ''} {r.get('时间') or ''}".strip(),
                "source": "akshare.news_economic_baidu",
                "url": None,
                "snippet": _clip(f"公布:{r.get('公布')} 预期:{r.get('预期')} 前值:{r.get('前值')}", 200),
            } for _, r in df.iterrows()]
            return ok(
                items,
                meta("akshare.news_economic_baidu", len(items)),
                artifact={"kind": "evidence", "title": f"全球经济日历（{len(items)} 条）",
                          "payload": {"items": items}},
            )
    except Exception as e:  # noqa: BLE001
        return err(f"全局新闻获取失败: {type(e).__name__}: {e}")


@skill(
    "get_announcements",
    "检索指定日期的A股公告（巨潮/东财公告库），可按代码或标题关键词过滤。date 为 YYYYMMDD，默认今天。",
    {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYYMMDD 或 YYYY-MM-DD，默认今天"},
            "keyword": {"type": "string", "description": "可选，按股票代码/名称/公告标题过滤"},
            "limit": {"type": "integer", "description": "最多返回条数（1-100），默认 30"},
        },
        "required": [],
    },
    internal=True,
)
def get_announcements(date: Optional[str] = None, keyword: Optional[str] = None,
                      limit: int = 30) -> dict:
    try:
        d8 = norm_date(date, _dt.date.today())
        df = ak.stock_notice_report(symbol="全部", date=d8)
        if df is None or len(df) == 0:
            return ok([], meta("akshare.stock_notice_report", 0)) | {
                "note": f"{d8} 无公告数据（非交易日或公告库未更新），可换日期重试"
            }
        if keyword:
            kw = str(keyword).strip()
            mask = (
                df["代码"].astype(str).str.contains(kw, na=False)
                | df["名称"].astype(str).str.contains(kw, na=False)
                | df["公告标题"].astype(str).str.contains(kw, na=False)
            )
            df = df[mask]
        df = df.head(max(1, min(int(limit or 30), 100)))
        items = [{
            "title": _clip(r.get("公告标题"), 120),
            "date": str(r.get("公告日期") or d8)[:10],
            "source": "akshare.stock_notice_report",
            "url": r.get("网址") or None,
            "snippet": _clip(f"{r.get('代码')} {r.get('名称')} · {r.get('公告类型')}", 200),
        } for _, r in df.iterrows()]
        title = f"{d8} 公告检索" + (f"（关键词:{keyword}）" if keyword else "")
        if not items:
            return ok([], meta("akshare.stock_notice_report", 0)) | {"note": "该日无匹配公告"}
        return ok(
            items,
            meta("akshare.stock_notice_report", len(items)),
            artifact={"kind": "evidence", "title": f"{title}（{len(items)} 条）",
                      "payload": {"items": items}},
        )
    except Exception as e:  # noqa: BLE001
        return err(f"公告检索失败: {type(e).__name__}: {e}")

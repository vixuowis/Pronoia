#!/usr/bin/env python3
"""patch_leakfix4.py — evidence_ledger strict as-of 修复。

泄漏路径：llm_web_latest（最新网络新闻）/ get_us_stock_news / get_us_stock_sec_filings /
get_stock_news / get_announcements 全部返回「当前」新闻（含事件后的未来资讯）。
修复：strict 模式跳过全部新闻源，最终 rows 按日期 <= 事件日过滤兜底。"""
import sys

SKILL = "/root/Pronoia/backend/app/skills/skill.py"
LLM = "/root/Pronoia/backend/app/llm.py"

def patch(path, replacements):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    for i, (old, new) in enumerate(replacements):
        if old not in src:
            print(f"[FAIL] {path} 片段#{i} 未找到:\n{old[:150]}"); sys.exit(1)
        if src.count(old) != 1:
            print(f"[FAIL] {path} 片段#{i} 非唯一({src.count(old)})"); sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[OK] {path}: {len(replacements)} 处")

patch(SKILL, [
    # 1. 签名
    (
        'async def evidence_ledger(symbol: str | None = None,\n'
        '                          keyword: str | None = None,\n'
        '                          lookback_days: int = 60,\n'
        '                          limit: int = 20) -> dict:',
        'async def evidence_ledger(symbol: str | None = None,\n'
        '                          keyword: str | None = None,\n'
        '                          lookback_days: int = 60,\n'
        '                          limit: int = 20,\n'
        '                          as_of_date: "str | None" = None) -> dict:',
    ),
    # 2. llm_web_latest 跳过
    (
        '    if query_target:\n'
        '        llm_first = await execute_skill("llm_web_latest", {\n'
        '            "query": f"{query_target} 最新公告 新闻 事件",\n'
        '            "limit": max(6, min(int(limit or 20), 20)),\n'
        '        })\n'
        '        if isinstance(llm_first, dict) and llm_first.get("ok") and isinstance(llm_first.get("data"), list) and llm_first["data"]:\n'
        '            items.extend(llm_first["data"])\n'
        '            artifacts.extend(_collect_artifacts([llm_first]))',
        '    if query_target and not as_of_date:\n'
        '        # strict as-of 跳过：llm_web_latest 返回「当前」网络新闻（含事件后未来资讯）\n'
        '        llm_first = await execute_skill("llm_web_latest", {\n'
        '            "query": f"{query_target} 最新公告 新闻 事件",\n'
        '            "limit": max(6, min(int(limit or 20), 20)),\n'
        '        })\n'
        '        if isinstance(llm_first, dict) and llm_first.get("ok") and isinstance(llm_first.get("data"), list) and llm_first["data"]:\n'
        '            items.extend(llm_first["data"])\n'
        '            artifacts.extend(_collect_artifacts([llm_first]))',
    ),
    # 3. US 新闻跳过
    (
        '    if resolved_symbol:\n'
        '        if not items:\n'
        '            if us:\n'
        '                n1 = await execute_skill("get_us_stock_news", {"symbol": resolved_symbol.upper(), "count": max(6, limit)})',
        '    if resolved_symbol and not as_of_date:\n'
        '        # strict as-of 跳过：个股新闻/公告/SEC filing 均为「当前」快照\n'
        '        if not items:\n'
        '            if us:\n'
        '                n1 = await execute_skill("get_us_stock_news", {"symbol": resolved_symbol.upper(), "count": max(6, limit)})',
    ),
    # 4. 最终 rows 按日期兜底过滤
    (
        '    rows = timeline.get("data") or []\n'
        '    price_metrics = (mr.get("data") or {}).get("price_metrics") if isinstance(mr, dict) and mr.get("ok") else {}',
        '    rows = timeline.get("data") or []\n'
        '    _iso = _asof_iso(as_of_date)\n'
        '    if _iso:\n'
        '        # 兜底：任何来源的时间线条目，日期 > 事件日即丢弃\n'
        '        rows = [r for r in rows\n'
        '                if not (isinstance(r, dict)\n'
        '                        and (_d := _norm_date_cell(str(r.get("date") or "")[:10].replace("-", "")))\n'
        '                        and _d > _iso)]\n'
        '    price_metrics = (mr.get("data") or {}).get("price_metrics") if isinstance(mr, dict) and mr.get("ok") else {}',
    ),
])

patch(LLM, [(
    '    if _asof and name in ("market_research", "post_market_outlook",\n'
    '                          "stock_overview", "news_intel",\n'
    '                          "financial_research", "holder_research", "macro_intel"):',
    '    if _asof and name in ("market_research", "post_market_outlook",\n'
    '                          "stock_overview", "news_intel",\n'
    '                          "financial_research", "holder_research", "macro_intel",\n'
    '                          "evidence_ledger"):',
)])

print("patch_leakfix4 完成")

#!/usr/bin/env python3
"""patch_leakfix2b.py — 修复片段#4（类型注解）后重放 skill.py 全部片段 + llm.py。
market.py 已由 patch_leakfix2.py 完成，helper 已追加，此处不重复。"""
import sys

def patch(path, replacements):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    for i, (old, new) in enumerate(replacements):
        if old not in src:
            print(f"[FAIL] {path} 片段#{i} 未找到:\n{old[:200]}"); sys.exit(1)
        if src.count(old) != 1:
            print(f"[FAIL] {path} 片段#{i} 非唯一({src.count(old)})"); sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[OK] {path}: {len(replacements)} 处")

SKILL = "/root/Pronoia/backend/app/skills/skill.py"
LLM = "/root/Pronoia/backend/app/llm.py"

patch(SKILL, [
    # 0. market_research：strict 只保留 price
    (
        '    focus = focus or ["price", "sector", "flow"]',
        '    focus = focus or ["price", "sector", "flow"]\n'
        '    # strict as-of：sector/flow/lhb 均为「当前」快照（未来信息），只保留 price\n'
        '    if as_of_date:\n'
        '        focus = ["price"]',
    ),
    # 1. market_research：US strict 跳过 spot
    (
        '        if us:\n'
        '            # 美股追加：实时行情（spot）+ 公司简介（info），填补 ak share 无 US 行业/资金流的口子\n'
        '            tasks.append(("get_us_stock_spot", {"symbol": sym}))\n'
        '            tasks.append(("get_us_stock_info", {"symbol": sym}))',
        '        if us and not as_of_date:\n'
        '            # 美股追加：实时行情（spot）+ 公司简介（info）\n'
        '            # strict as-of 跳过：spot 为「现在」的价格，对历史事件是未来函数\n'
        '            tasks.append(("get_us_stock_spot", {"symbol": sym}))\n'
        '            tasks.append(("get_us_stock_info", {"symbol": sym}))',
    ),
    # 2. market_research：结果过滤
    (
        '    results = await _gather_sub(tasks)\n'
        '    summary = _summarize_subs(results)\n'
        '    summary["composed"] = [n for n, _ in tasks]\n'
        '    price_metrics: dict[str, Any] = {}',
        '    results = await _gather_sub(tasks)\n'
        '    if as_of_date:\n'
        '        results = [_asof_filter_result(r, as_of_date) for r in results]\n'
        '    summary = _summarize_subs(results)\n'
        '    summary["composed"] = [n for n, _ in tasks]\n'
        '    price_metrics: dict[str, Any] = {}',
    ),
    # 3. financial_research 签名
    (
        'async def financial_research(symbol: str, period: str = "annual") -> dict:',
        'async def financial_research(symbol: str, period: str = "annual",\n'
        '                             as_of_date: "str | None" = None) -> dict:',
    ),
    # 4. financial_research US tasks（带类型注解，已修正）
    (
        '        tasks: list[tuple[str, dict]] = [\n'
        '            ("get_us_stock_finance",   {"symbol": sym, "report_type": "资产负债表", "indicator": "年报"}),\n'
        '            ("get_us_stock_indicator", {"symbol": sym, "indicator": "年报"}),\n'
        '            ("get_us_stock_calendar",  {"symbol": sym}),\n'
        '            ("get_us_stock_info",      {"symbol": sym}),\n'
        '            ("get_us_stock_analyst",   {"symbol": sym}),\n'
        '        ]',
        '        tasks: list[tuple[str, dict]] = [\n'
        '            ("get_us_stock_finance",   {"symbol": sym, "report_type": "资产负债表", "indicator": "年报"}),\n'
        '            ("get_us_stock_indicator", {"symbol": sym, "indicator": "年报"}),\n'
        '            ("get_us_stock_info",      {"symbol": sym}),\n'
        '        ]\n'
        '        if not as_of_date:\n'
        '            # strict as-of 跳过：calendar（未来财报日历）/ analyst（当前机构评级）\n'
        '            tasks += [\n'
        '                ("get_us_stock_calendar",  {"symbol": sym}),\n'
        '                ("get_us_stock_analyst",   {"symbol": sym}),\n'
        '            ]',
    ),
    # 5. financial_research A股 tasks + 结果过滤
    (
        '        tasks = [\n'
        '            ("get_financial_abstract", {"symbol": sym}),\n'
        '            ("get_financial_indicator", {"symbol": sym}),\n'
        '            ("get_income_statement", {"symbol": sym, "periods": 8 if period == "annual" else 12}),\n'
        '            ("get_profit_forecast", {"symbol": sym}),\n'
        '        ]\n'
        '        market_label = "A股"\n'
        '    results = await _gather_sub(tasks)\n'
        '    summary = _summarize_subs(results)',
        '        # strict as-of：财务摘要/机构盈利预测是「当前」快照（未来信息），跳过\n'
        '        _fin_tasks = [\n'
        '            ("get_financial_indicator", {"symbol": sym}),\n'
        '            ("get_income_statement", {"symbol": sym, "periods": 8 if period == "annual" else 12}),\n'
        '        ]\n'
        '        if not as_of_date:\n'
        '            _fin_tasks = [\n'
        '                ("get_financial_abstract", {"symbol": sym}),\n'
        '                *_fin_tasks,\n'
        '                ("get_profit_forecast", {"symbol": sym}),\n'
        '            ]\n'
        '        tasks = _fin_tasks\n'
        '        market_label = "A股"\n'
        '    results = await _gather_sub(tasks)\n'
        '    if as_of_date:\n'
        '        results = [_asof_filter_result(r, as_of_date) for r in results]\n'
        '    summary = _summarize_subs(results)',
    ),
    # 6. holder_research 签名
    (
        'async def holder_research(symbol: str) -> dict:',
        'async def holder_research(symbol: str, as_of_date: "str | None" = None) -> dict:',
    ),
    # 7. holder_research US strict
    (
        '    if is_us_symbol(raw):\n'
        '        # 美股：major_holders / institutional_holders / mutualfund_holders / insider_transactions\n'
        '        sym = raw.upper()',
        '    if is_us_symbol(raw):\n'
        '        # strict as-of：美股持仓为「当前」快照（未来信息），禁用\n'
        '        if as_of_date:\n'
        '            return err(f"strict as-of 模式（事件日 {as_of_date}）禁用美股股东持仓查询：当前快照含事件后信息")\n'
        '        # 美股：major_holders / institutional_holders / mutualfund_holders / insider_transactions\n'
        '        sym = raw.upper()',
    ),
    # 8. holder_research A股 + 结果过滤
    (
        '        tasks = [\n'
        '            ("get_holder_change", {"symbol": sym}),\n'
        '            ("get_restricted_release_summary", {"symbol": sym}),\n'
        '        ]\n'
        '        market_label = "A股"\n'
        '    results = await _gather_sub(tasks)',
        '        tasks = [\n'
        '            ("get_holder_change", {"symbol": sym}),\n'
        '            ("get_restricted_release_summary", {"symbol": sym}),\n'
        '        ]\n'
        '        market_label = "A股"\n'
        '    results = await _gather_sub(tasks)\n'
        '    if as_of_date:\n'
        '        results = [_asof_filter_result(r, as_of_date) for r in results]',
    ),
    # 9. macro_intel strict 禁用
    (
        'async def macro_intel(topic: str | None = None) -> dict:',
        'async def macro_intel(topic: str | None = None, as_of_date: "str | None" = None) -> dict:\n'
        '    if as_of_date:\n'
        '        return err(f"strict as-of 模式（事件日 {as_of_date}）禁用 macro_intel：宏观数据为当前快照，含事件后信息")',
    ),
    # 10. stock_overview strict
    (
        '    if market == "US":\n'
        '        tasks = [\n'
        '            ("get_us_stock_spot",     {"symbol": code}),\n'
        '            ("get_us_stock_info",     {"symbol": code}),\n'
        '            ("get_us_stock_finance",  {"symbol": code, "report_type": "资产负债表", "indicator": "年报"}),\n'
        '            ("get_us_stock_indicator", {"symbol": code, "indicator": "年报"}),\n'
        '            ("get_us_stock_calendar", {"symbol": code}),\n'
        '            ("get_stock_daily",       {"symbol": code, "start_date": start, "end_date": end, "adjust": "qfq"}),\n'
        '        ]\n'
        '    else:\n'
        '        tasks = [\n'
        '            ("get_financial_abstract", {"symbol": code}),\n'
        '            ("get_stock_daily", {"symbol": code, "start_date": start, "end_date": end, "adjust": "qfq"}),\n'
        '        ]\n'
        '    results = await _gather_sub(tasks)',
        '    if market == "US":\n'
        '        # strict as-of：spot（现价）/ calendar（未来日历）为未来信息，跳过\n'
        '        tasks = [\n'
        '            ("get_us_stock_info",     {"symbol": code}),\n'
        '            ("get_us_stock_finance",  {"symbol": code, "report_type": "资产负债表", "indicator": "年报"}),\n'
        '            ("get_us_stock_indicator", {"symbol": code, "indicator": "年报"}),\n'
        '            ("get_stock_daily",       {"symbol": code, "start_date": start, "end_date": end, "adjust": "qfq"}),\n'
        '        ]\n'
        '        if not as_of_date:\n'
        '            tasks = [\n'
        '                ("get_us_stock_spot",     {"symbol": code}),\n'
        '                *tasks,\n'
        '                ("get_us_stock_calendar", {"symbol": code}),\n'
        '            ]\n'
        '    else:\n'
        '        # strict as-of：财务摘要为「最新报告期」快照（未来信息），跳过\n'
        '        tasks = [\n'
        '            ("get_stock_daily", {"symbol": code, "start_date": start, "end_date": end, "adjust": "qfq"}),\n'
        '        ]\n'
        '        if not as_of_date:\n'
        '            tasks.append(("get_financial_abstract", {"symbol": code}))\n'
        '    results = await _gather_sub(tasks)\n'
        '    if as_of_date:\n'
        '        results = [_asof_filter_result(r, as_of_date) for r in results]',
    ),
])

patch(LLM, [(
    '    if _asof and name in ("market_research", "post_market_outlook",\n'
    '                          "stock_overview", "news_intel"):',
    '    if _asof and name in ("market_research", "post_market_outlook",\n'
    '                          "stock_overview", "news_intel",\n'
    '                          "financial_research", "holder_research", "macro_intel"):',
)])

print("v2 全部补丁应用完成")

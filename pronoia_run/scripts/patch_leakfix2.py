#!/usr/bin/env python3
"""patch_leakfix2.py — 第二轮泄漏修复。

P0 market.py  get_us_stock_daily：全量拉取后按 start/end_date 过滤再 tail(250)
P1 skill.py   financial_research / holder_research / macro_intel 接受 as_of_date；
              strict 模式过滤事件后表行 + 跳过当前快照子技能；
              market_research / stock_overview 增强过滤
P1 llm.py     注入列表扩充
helper        _asof_filter_result 追加到 skill.py 末尾（运行时解析，安全）
"""
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

MARKET = "/root/Pronoia/backend/app/skills/market.py"
SKILL = "/root/Pronoia/backend/app/skills/skill.py"
LLM = "/root/Pronoia/backend/app/llm.py"

# ================= market.py =================
patch(MARKET, [(
    '        df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)\n'
    '        truncated = False\n'
    '        if len(df) > 250:',
    '        df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)\n'
    '        # P0 as-of 过滤：接口返回全历史，按调用方窗口裁剪后再取尾部，\n'
    '        # 否则严格 as-of 回测会把「今天」的行情喂给历史事件（未来函数泄漏）。\n'
    '        _sd = str(start_date or "").replace("-", "")[:8]\n'
    '        _ed = str(end_date or "").replace("-", "")[:8]\n'
    '        if _sd and len(_sd) == 8:\n'
    '            df = df[df["date"] >= f"{_sd[:4]}-{_sd[4:6]}-{_sd[6:8]}"].reset_index(drop=True)\n'
    '        if _ed and len(_ed) == 8:\n'
    '            df = df[df["date"] <= f"{_ed[:4]}-{_ed[4:6]}-{_ed[6:8]}"].reset_index(drop=True)\n'
    '        truncated = False\n'
    '        if len(df) > 250:',
)])

# ================= skill.py =================
ASOF_HELPER = '''

# ============================================================== strict as-of 过滤
def _asof_iso(as_of_date) -> "str | None":
    if not as_of_date:
        return None
    s = str(as_of_date)[:10]
    try:
        from datetime import datetime as _dt
        _dt.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _looks_like_date(cell) -> bool:
    if not isinstance(cell, str) or len(cell) < 10:
        return False
    try:
        from datetime import datetime as _dt
        _dt.strptime(cell[:10], "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _asof_filter_artifact(art: dict, asof_iso: str) -> dict:
    """裁剪单个 artifact 到 as-of 日：table 按日期列过滤行；kline/line 按日期轴过滤。"""
    if not isinstance(art, dict):
        return art
    payload = art.get("payload")
    if not isinstance(payload, dict):
        return art
    kind = str(art.get("kind") or "")
    if kind == "table":
        cols = payload.get("columns") or []
        rows = payload.get("rows")
        if not isinstance(rows, list) or not rows:
            return art
        date_idx = None
        for i, c in enumerate(cols):
            cl = str(c).lower()
            if any(k in cl for k in ("日期", "date", "时间", "报告期")):
                date_idx = i
                break
        if date_idx is None:
            return art  # 无日期列（静态表），原样保留
        kept = [r for r in rows
                if not (isinstance(r, list) and len(r) > date_idx and _looks_like_date(r[date_idx])
                        and str(r[date_idx])[:10] > asof_iso)]
        payload["rows"] = kept
        note = str(payload.get("note") or "")
        payload["note"] = (note + " | " if note else "") + f"strict as-of：已过滤 {asof_iso} 之后的行"
        return art
    if kind in ("kline", "line"):
        dates = payload.get("dates") or payload.get("x")
        if not isinstance(dates, list) or not dates:
            return art
        idx = [i for i, d in enumerate(dates)
               if not (isinstance(d, str) and len(d) >= 10 and d[:10] > asof_iso)]
        for key in ("dates", "x"):
            if isinstance(payload.get(key), list):
                payload[key] = [payload[key][i] for i in idx]
        for key in ("ohlc", "volumes", "series"):
            seq = payload.get(key)
            if isinstance(seq, list):
                if seq and isinstance(seq[0], dict) and isinstance(seq[0].get("data"), list):
                    for s in seq:
                        if len(s.get("data") or []) == len(dates):
                            s["data"] = [s["data"][i] for i in idx]
                elif len(seq) == len(dates):
                    payload[key] = [seq[i] for i in idx]
        return art
    return art


def _asof_filter_result(result: dict, as_of_date) -> dict:
    """递归裁剪 result 内所有 artifacts 到 as-of 日（深拷贝，不改原对象）。"""
    iso = _asof_iso(as_of_date)
    if not iso or not isinstance(result, dict):
        return result
    import copy as _copy
    out = _copy.deepcopy(result)
    arts = out.get("artifacts")
    if isinstance(arts, list):
        out["artifacts"] = [_asof_filter_artifact(a, iso) if isinstance(a, dict) else a for a in arts]
    if isinstance(out.get("artifact"), dict):
        out["artifact"] = _asof_filter_artifact(out["artifact"], iso)
    return out
'''

with open(SKILL, encoding="utf-8") as f:
    src = f.read()
src = src.rstrip("\n") + "\n" + ASOF_HELPER
with open(SKILL, "w", encoding="utf-8") as f:
    f.write(src)
print("[OK] skill.py: helper 已追加到文件末尾")

patch(SKILL, [
    # ---------- market_research：strict 只保留 price；跳过 US spot ----------
    (
        '    focus = focus or ["price", "sector", "flow"]',
        '    focus = focus or ["price", "sector", "flow"]\n'
        '    # strict as-of：sector/flow/lhb 均为「当前」快照（未来信息），只保留 price\n'
        '    if as_of_date:\n'
        '        focus = ["price"]',
    ),
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
    # ---------- financial_research：签名 + strict ----------
    (
        'async def financial_research(symbol: str, period: str = "annual") -> dict:',
        'async def financial_research(symbol: str, period: str = "annual",\n'
        '                             as_of_date: "str | None" = None) -> dict:',
    ),
    (
        '        tasks = [\n'
        '            ("get_us_stock_finance",   {"symbol": sym, "report_type": "资产负债表", "indicator": "年报"}),\n'
        '            ("get_us_stock_indicator", {"symbol": sym, "indicator": "年报"}),\n'
        '            ("get_us_stock_calendar",  {"symbol": sym}),\n'
        '            ("get_us_stock_info",      {"symbol": sym}),\n'
        '            ("get_us_stock_analyst",   {"symbol": sym}),\n'
        '        ]',
        '        tasks = [\n'
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
    # ---------- holder_research：签名 + US strict + 行过滤 ----------
    (
        'async def holder_research(symbol: str) -> dict:',
        'async def holder_research(symbol: str, as_of_date: "str | None" = None) -> dict:',
    ),
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
    # ---------- macro_intel：strict 禁用 ----------
    (
        'async def macro_intel(topic: str | None = None) -> dict:',
        'async def macro_intel(topic: str | None = None, as_of_date: "str | None" = None) -> dict:\n'
        '    if as_of_date:\n'
        '        return err(f"strict as-of 模式（事件日 {as_of_date}）禁用 macro_intel：宏观数据为当前快照，含事件后信息")',
    ),
    # ---------- stock_overview：strict 跳过 spot/calendar/abstract + 行过滤 ----------
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

# ================= llm.py =================
patch(LLM, [(
    '    if _asof and name in ("market_research", "post_market_outlook",\n'
    '                          "stock_overview", "news_intel"):',
    '    if _asof and name in ("market_research", "post_market_outlook",\n'
    '                          "stock_overview", "news_intel",\n'
    '                          "financial_research", "holder_research", "macro_intel"):',
)])

print("全部补丁应用完成")

#!/usr/bin/env python3
"""patch_leakfix2.py — 第二轮泄漏修复：美股K线日期过滤 + 财务/股东/宏观 strict as-of 过滤。

P0 market.py  get_us_stock_daily：全量拉取后按 start/end_date 过滤，再 tail(250)
P1 skill.py   financial_research / holder_research / market_research / stock_overview /
              post_market_outlook 接受 as_of_date：过滤事件后的表行/跳过当前快照子技能
              macro_intel strict 模式禁用
P1 llm.py     注入列表扩充
"""
import sys


def patch(path, replacements):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    for i, (old, new) in enumerate(replacements):
        if old not in src:
            print(f"[FAIL] {path} 片段#{i} 未找到"); sys.exit(1)
        if src.count(old) != 1:
            print(f"[FAIL] {path} 片段#{i} 非唯一({src.count(old)})"); sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[OK] {path}: {len(replacements)} 处")


MARKET = "/root/Pronoia/backend/app/skills/market.py"
SKILL = "/root/Pronoia/backend/app/skills/skill.py"
LLM = "/root/Pronoia/backend/app/llm.py"

# ================= market.py: 美股K线日期过滤 =================
market_patches = [
    (
        "        df = df.dropna(subset=[\"close\"]).sort_values(\"date\").reset_index(drop=True)\n"
        "        truncated = False\n"
        "        if len(df) > 250:",
        "        df = df.dropna(subset=[\"close\"]).sort_values(\"date\"]).reset_index(drop=True)\n"
        "        # P0 as-of 过滤：接口返回全历史，这里按调用方传入的窗口裁剪后再取尾部，\n"
        "        # 否则严格 as-of 回测会把「今天」的行情喂给历史事件（未来函数泄漏）。\n"
        "        _sd = str(start_date or \"\").replace(\"-\", \"\")[:8]\n"
        "        _ed = str(end_date or \"\").replace(\"-\", \"\")[:8]\n"
        "        if _sd and len(_sd) == 8:\n"
        "            _sd_iso = f\"{_sd[:4]}-{_sd[4:6]}-{_sd[6:8]}\"\n"
        "            df = df[df[\"date\"] >= _sd_iso].reset_index(drop=True)\n"
        "        if _ed and len(_ed) == 8:\n"
        "            _ed_iso = f\"{_ed[:4]}-{_ed[4:6]}-{_ed[6:8]}\"\n"
        "            df = df[df[\"date\"] <= _ed_iso].reset_index(drop=True)\n"
        "        truncated = False\n"
        "        if len(df) > 250:",
    ),
]

# ================= skill.py: strict as-of 过滤 =================
ASOF_HELPER = '''

# ============================================================== strict as-of 过滤
def _asof_iso(as_of_date) -> str | None:
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
    """把单个 artifact 裁剪到 as-of 日：table 按日期列过滤行；kline/line 按日期轴过滤。"""
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
        # 找日期列（表头含 日期/date/时间/报告期）
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
        payload.setdefault("note", "")
        payload["note"] = (str(payload["note"]) + f" | strict as-of：已过滤 {asof_iso} 之后的行").strip(" |")
        return art
    if kind in ("kline", "line"):
        dates = payload.get("dates") or payload.get("x")
        if not isinstance(dates, list) or not dates:
            return art
        idx = [i for i, d in enumerate(dates) if not (isinstance(d, str) and d[:10] > asof_iso)]
        for key in ("dates", "x"):
            if isinstance(payload.get(key), list):
                payload[key] = [payload[key][i] for i in idx]
        for key in ("ohlc", "volumes", "series"):
            seq = payload.get(key)
            if isinstance(seq, list):
                if seq and isinstance(seq[0], dict) and "data" in seq[0]:
                    for s in seq:
                        if isinstance(s.get("data"), list):
                            s["data"] = [s["data"][i] for i in idx] if len(s["data"]) == len(dates) else s["data"]
                else:
                    payload[key] = [seq[i] for i in idx] if len(seq) == len(dates) else seq
        return art
    return art


def _asof_filter_result(result: dict, as_of_date) -> dict:
    """递归裁剪 result 内所有 artifacts 到 as-of 日（不修改原始对象）。"""
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

skill_patches = [
    # ---------- 注入 as-of 过滤 helper ----------
    (
        "# ============================================================== stock_overview",
        ASOF_HELPER + "\n# ============================================================== stock_overview",
    ),
    # ---------- market_research：strict 模式只保留 price ----------
    (
        "    focus = focus or [\"price\", \"sector\", \"flow\"]",
        "    focus = focus or [\"price\", \"sector\", \"flow\"]\n"
        "    # strict as-of：sector/flow/lhb 都是「当前」快照（未来信息），只保留 price\n"
        "    if as_of_date:\n"
        "        focus = [\"price\"]",
    ),
    (
        "        tasks.append((\"get_stock_daily\", {\"symbol\": sym, \"start_date\": start, \"end_date\": end, \"adjust\": \"qfq\"}))\n"
        "        if us:\n"
        "            # 美股追加：实时行情（spot）+ 公司简介（info），填补 ak share 无 US 行业/资金流的口子",
        "        tasks.append((\"get_stock_daily\", {\"symbol\": sym, \"start_date\": start, \"end_date\": end, \"adjust\": \"qfq\"}))\n"
        "        if us and not as_of_date:\n"
        "            # 美股追加：实时行情（spot）+ 公司简介（info）\n"
        "            # strict as-of 下跳过：spot 是「现在」的价格（对未来事件是未来函数）",
    ),
    # ---------- market_research 结果过滤 ----------
    (
        "    results = await _gather_sub(tasks)\n"
        "    summary = _summarize_subs(results)\n"
        "    summary[\"composed\"] = [n for n, _ in tasks]\n"
        "\n"
        "    out: dict = {\"symbol\": sym, \"lookback_days\": lookback_days, \"focus\": focus_eff,",
        "    results = await _gather_sub(tasks)\n"
        "    if as_of_date:\n"
        "        results = [_asof_filter_result(r, as_of_date) for r in results]\n"
        "    summary = _summarize_subs(results)\n"
        "    summary[\"composed\"] = [n for n, _ in tasks]\n"
        "\n"
        "    out: dict = {\"symbol\": sym, \"lookback_days\": lookback_days, \"focus\": focus_eff,",
    ),
    # ---------- post_market_outlook：strict 只保留 K 线，结果过滤 ----------
    (
        "    tasks: list[tuple[str, dict]] = [\n"
        "        (\"get_stock_daily\", {\"symbol\": sym, \"start_date\": start, \"end_date\": end, \"adjust\": \"qfq\"}),\n"
        "        (\"get_industry_fund_flow\", {\"sort_by\": \"净额\", \"limit\": 20}),\n"
        "        (\"get_individual_fund_flow_rank\", {\"limit\": 10}),\n"
        "        (\"list_industry_boards\", {\"symbol\": sym}) if not us else (\"get_global_news\", {\"limit\": 8}),\n"
        "    ]",
        "    # strict as-of：资金流/板块/新闻都是当前快照，只保留 K 线\n"
        "    if as_of_date:\n"
        "        tasks = [(\"get_stock_daily\", {\"symbol\": sym, \"start_date\": start, \"end_date\": end, \"adjust\": \"qfq\"})]\n"
        "    else:\n"
        "        tasks = [\n"
        "            (\"get_stock_daily\", {\"symbol\": sym, \"start_date\": start, \"end_date\": end, \"adjust\": \"qfq\"}),\n"
        "            (\"get_industry_fund_flow\", {\"sort_by\": \"净额\", \"limit\": 20}),\n"
        "            (\"get_individual_fund_flow_rank\", {\"limit\": 10}),\n"
        "            (\"list_industry_boards\", {\"symbol\": sym}) if not us else (\"get_global_news\", {\"limit\": 8}),\n"
        "        ]",
    ),
    (
        "    results = await _gather_sub(tasks)\n"
        "    summary = _summarize_subs(results)\n"
        "    summary[\"composed\"] = [n for n, _ in tasks]\n"
        "    # 摘要：抽取 K线末尾 5 根的 OHLC + 涨跌幅 + 资金净额 + 板块名",
        "    results = await _gather_sub(tasks)\n"
        "    if as_of_date:\n"
        "        results = [_asof_filter_result(r, as_of_date) for r in results]\n"
        "    summary = _summarize_subs(results)\n"
        "    summary[\"composed\"] = [n for n, _ in tasks]\n"
        "    # 摘要：抽取 K线末尾 5 根的 OHLC + 涨跌幅 + 资金净额 + 板块名",
    ),
    # ---------- financial_research：strict 跳过当前快照 + 行过滤 ----------
    (
        "async def financial_research(symbol: str, period: str = \"annual\") -> dict:",
        "async def financial_research(symbol: str, period: str = \"annual\",\n"
        "                             as_of_date: str | None = None) -> dict:",
    ),
    (
        "        tasks = [\n"
        "            (\"get_financial_abstract\", {\"symbol\": sym}),\n"
        "            (\"get_financial_indicator\", {\"symbol\": sym}),\n"
        "            (\"get_income_statement\", {\"symbol\": sym, \"periods\": 8 if period == \"annual\" else 12}),\n"
        "            (\"get_profit_forecast\", {\"symbol\": sym}),\n"
        "        ]",
        "        # strict as-of：机构盈利预测是「当前」共识（未来信息），跳过\n"
        "        _fin_tasks = [\n"
        "            (\"get_financial_abstract\", {\"symbol\": sym}),\n"
        "            (\"get_financial_indicator\", {\"symbol\": sym}),\n"
        "            (\"get_income_statement\", {\"symbol\": sym, \"periods\": 8 if period == \"annual\" else 12}),\n"
        "        ]\n"
        "        if not as_of_date:\n"
        "            _fin_tasks.append((\"get_profit_forecast\", {\"symbol\": sym}))\n"
        "        tasks = _fin_tasks",
    ),
    (
        "        tasks = [\n"
        "
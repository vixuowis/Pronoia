#!/usr/bin/env python3
"""patch_asof_kline.py — 修复 K 线未来函数泄漏。

根因：market_research / post_market_outlook / stock_overview 用 datetime.now()
回溯 K 线窗口，team 回测场景下把「今天（事件后数月）」的行情喂进了模型上下文。

修复：
1. llm.py      新增 AS_OF_DATE ContextVar；execute_skill 对时间敏感技能注入 as_of_date
2. skill.py    三个技能接受 as_of_date，取数窗口钳制到事件日；news_intel 严格模式下禁用
3. engine.py   run_team_full_one_event 开头 set AS_OF_DATE = event_time
"""
import sys

FILES = {
    "llm.py": "/root/Pronoia/backend/app/llm.py",
    "skill.py": "/root/Pronoia/backend/app/skills/skill.py",
    "engine.py": "/root/Pronoia/backend/app/event_backtest/engine.py",
}


def patch(path: str, replacements: list[tuple[str, str]]) -> None:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    for i, (old, new) in enumerate(replacements):
        if old not in src:
            print(f"[FAIL] {path} 片段#{i} 未找到")
            sys.exit(1)
        if src.count(old) != 1:
            print(f"[FAIL] {path} 片段#{i} 非唯一({src.count(old)}处)")
            sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[OK] {path}: {len(replacements)} 处补丁")


# ---------- 1) llm.py ----------
llm_patches = [
    # 1a. import
    (
        "from openai import AsyncOpenAI",
        "from contextvars import ContextVar\n\nfrom openai import AsyncOpenAI",
    ),
    # 1b. ContextVar 定义
    (
        'ArtifactStore = Callable[[str, str, Any], Awaitable[dict]]',
        'ArtifactStore = Callable[[str, str, Any], Awaitable[dict]]\n'
        '\n'
        '# P0 未来函数防护（K线/资讯窗口 clamp）：engine.run_team_full_one_event 把当前\n'
        '# 事件的 event_time 写入该 ContextVar；execute_skill 对时间敏感技能自动注入\n'
        '# as_of_date，技能内部把取数窗口钳制到事件日（见 skill.py），杜绝未来数据泄漏。\n'
        'AS_OF_DATE: ContextVar = ContextVar("as_of_date", default=None)',
    ),
    # 1c. execute_skill 注入
    (
        "        elif name == \"event_study\":\n"
        "            args[\"as_of\"] = True\n"
        "            # event_study 是 internal skill，也强制 as_of（即使 skill.py 的 wrapper 没拦住）",
        "        elif name == \"event_study\":\n"
        "            args[\"as_of\"] = True\n"
        "            # event_study 是 internal skill，也强制 as_of（即使 skill.py 的 wrapper 没拦住）\n"
        "    # P0 K线/资讯窗口 clamp：事件时间存在时，对时间敏感技能注入 as_of_date\n"
        "    _asof = AS_OF_DATE.get()\n"
        "    if _asof and name in (\"market_research\", \"post_market_outlook\",\n"
        "                          \"stock_overview\", \"news_intel\"):\n"
        "        args = dict(args or {})\n"
        "        args.setdefault(\"as_of_date\", _asof)",
    ),
]

# ---------- 2) skill.py ----------
skill_patches = [
    # 2a. market_research 签名
    (
        "async def market_research(symbol: str, lookback_days: int = 60,\n"
        "                          focus: list[str] | None = None) -> dict:",
        "async def market_research(symbol: str, lookback_days: int = 60,\n"
        "                          focus: list[str] | None = None,\n"
        "                          as_of_date: str | None = None) -> dict:",
    ),
    # 2b. market_research 日期窗口
    (
        "    from datetime import datetime, timedelta\n"
        "    calendar_lookback = lookback_days if us else max(lookback_days * 2 + 30, lookback_days)\n"
        "    end = datetime.now().strftime(\"%Y%m%d\")\n"
        "    start = (datetime.now() - timedelta(days=calendar_lookback)).strftime(\"%Y%m%d\")",
        "    from datetime import datetime, timedelta\n"
        "    calendar_lookback = lookback_days if us else max(lookback_days * 2 + 30, lookback_days)\n"
        "    # as_of_date（严格 as-of 回测）：end 钳制到事件日、窗口往回推，禁止未来 K 线\n"
        "    if as_of_date:\n"
        "        try:\n"
        "            _end_dt = datetime.strptime(str(as_of_date)[:10], \"%Y-%m-%d\")\n"
        "        except ValueError:\n"
        "            _end_dt = None\n"
        "    else:\n"
        "        _end_dt = None\n"
        "    _anchor = _end_dt or datetime.now()\n"
        "    end = _anchor.strftime(\"%Y%m%d\")\n"
        "    start = (_anchor - timedelta(days=calendar_lookback)).strftime(\"%Y%m%d\")",
    ),
    # 2c. post_market_outlook 签名
    (
        "async def post_market_outlook(symbol: str, lookback_days: int = 30) -> dict:",
        "async def post_market_outlook(symbol: str, lookback_days: int = 30,\n"
        "                              as_of_date: str | None = None) -> dict:",
    ),
    # 2d. post_market_outlook 日期窗口
    (
        "    from datetime import datetime, timedelta\n"
        "    end = datetime.now().strftime(\"%Y%m%d\")\n"
        "    start = (datetime.now() - timedelta(days=lookback_days)).strftime(\"%Y%m%d\")\n"
        "    tasks: list[tuple[str, dict]] = [\n"
        "        (\"get_stock_daily\", {\"symbol\": sym, \"start_date\": start, \"end_date\": end, \"adjust\": \"qfq\"}),",
        "    from datetime import datetime, timedelta\n"
        "    # as_of_date：end 钳制到事件日（严格 as-of 回测，禁止未来 K 线）\n"
        "    if as_of_date:\n"
        "        try:\n"
        "            _end_dt = datetime.strptime(str(as_of_date)[:10], \"%Y-%m-%d\")\n"
        "        except ValueError:\n"
        "            _end_dt = None\n"
        "    else:\n"
        "        _end_dt = None\n"
        "    _anchor = _end_dt or datetime.now()\n"
        "    end = _anchor.strftime(\"%Y%m%d\")\n"
        "    start = (_anchor - timedelta(days=lookback_days)).strftime(\"%Y%m%d\")\n"
        "    tasks: list[tuple[str, dict]] = [\n"
        "        (\"get_stock_daily\", {\"symbol\": sym, \"start_date\": start, \"end_date\": end, \"adjust\": \"qfq\"}),",
    ),
    # 2e. stock_overview 签名
    (
        "async def stock_overview(keyword: str) -> dict:",
        "async def stock_overview(keyword: str, as_of_date: str | None = None) -> dict:",
    ),
    # 2f. stock_overview 日期窗口
    (
        "    from datetime import datetime, timedelta\n"
        "    end = datetime.now().strftime(\"%Y%m%d\")\n"
        "    start = (datetime.now() - timedelta(days=30)).strftime(\"%Y%m%d\")",
        "    from datetime import datetime, timedelta\n"
        "    # as_of_date：end 钳制到事件日（严格 as-of 回测，禁止未来 K 线）\n"
        "    if as_of_date:\n"
        "        try:\n"
        "            _end_dt = datetime.strptime(str(as_of_date)[:10], \"%Y-%m-%d\")\n"
        "        except ValueError:\n"
        "            _end_dt = None\n"
        "    else:\n"
        "        _end_dt = None\n"
        "    _anchor = _end_dt or datetime.now()\n"
        "    end = _anchor.strftime(\"%Y%m%d\")\n"
        "    start = (_anchor - timedelta(days=30)).strftime(\"%Y%m%d\")",
    ),
    # 2g. news_intel 签名 + 严格模式拦截
    (
        "async def news_intel(symbol: str | None = None,\n"
        "                     kind: list[str] | None = None,\n"
        "                     limit: int = 8) -> dict:\n"
        "    raw_symbol = (symbol or \"\").strip()",
        "async def news_intel(symbol: str | None = None,\n"
        "                     kind: list[str] | None = None,\n"
        "                     limit: int = 8,\n"
        "                     as_of_date: str | None = None) -> dict:\n"
        "    # 严格 as-of 回测：资讯源返回的是「最新」新闻（含事件后内容），直接禁用，\n"
        "    # 事件原文已在 as_of_packet 里，不需要联网补资讯。\n"
        "    if as_of_date:\n"
        "        return err(f\"strict as-of 模式（事件日 {as_of_date}）禁用 news_intel：\"\n"
        "                   f\"最新资讯含事件后内容；事件原文已在 as_of_packet\")\n"
        "    raw_symbol = (symbol or \"\").strip()",
    ),
]

# ---------- 3) engine.py ----------
engine_patches = [
    (
        '    event_time = getattr(event, "event_time", "")',
        '    event_time = getattr(event, "event_time", "")\n'
        '    # P0 as-of clamp：把事件时间下发给技能层（execute_skill 注入 as_of_date），\n'
        '    # market_research / stock_overview 等技能的 K 线窗口钳制到事件日。\n'
        '    # 每次调用都 set 新值，无需 reset（batch worker 串行消费事件）。\n'
        '    from app.llm import AS_OF_DATE as _AS_OF_DATE\n'
        '    _AS_OF_DATE.set(str(event_time)[:10])',
    ),
]


def main() -> None:
    patch(FILES["llm.py"], llm_patches)
    patch(FILES["skill.py"], skill_patches)
    patch(FILES["engine.py"], engine_patches)
    print("ALL PATCHED")


if __name__ == "__main__":
    main()

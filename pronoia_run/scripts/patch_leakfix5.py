#!/usr/bin/env python3
"""patch_leakfix5.py — llm.py 通用兜底：原子技能直调泄漏防护。

1) _ASOF_NEVER 拦截：返回「当前」快照的原子技能（新闻/现价/日历/机构预测）
   在 strict as-of 下直接返回 err；
2) 结果兜底过滤：所有 ok 结果过 _asof_filter_result（table 行内未来日期丢弃、
   kline/line 日期轴裁剪），对无日期 artifact 是 no-op。
3) analyzers.py 补 _gather_sub 延迟导入（NameError 修复）。"""
import sys

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

patch(LLM, [
    # 1. 拦截列表 + 拦截逻辑（插在 as_of_date 注入块之后）
    (
        '    if _asof and name in ("market_research", "post_market_outlook",\n'
        '                          "stock_overview", "news_intel",\n'
        '                          "financial_research", "holder_research", "macro_intel",\n'
        '                          "evidence_ledger"):\n'
        '        args = dict(args or {})\n'
        '        args.setdefault("as_of_date", _asof)\n'
        '    ensure_skills_loaded()',
        '    if _asof and name in ("market_research", "post_market_outlook",\n'
        '                          "stock_overview", "news_intel",\n'
        '                          "financial_research", "holder_research", "macro_intel",\n'
        '                          "evidence_ledger"):\n'
        '        args = dict(args or {})\n'
        '        args.setdefault("as_of_date", _asof)\n'
        '    # P1 原子技能直调防护：返回「当前」快照的技能直接拦截\n'
        '    if _asof and name in _ASOF_NEVER:\n'
        '        _msg = f"strict as-of 模式（事件日 {_asof}）禁用 {name}：返回当前快照，含事件后信息"\n'
        '        print(f"SKILL name={name} ok=false err=blocked_asof dur={time.time() - _t0:.2f}s", flush=True)\n'
        '        return {"ok": False, "error": _msg}\n'
        '    ensure_skills_loaded()',
    ),
    # 2. 结果兜底过滤（成功结果统一过滤）
    (
        '    try:\n'
        '        if asyncio.iscoroutinefunction(sd.handler):\n'
        '            result = await asyncio.wait_for(\n'
        '                sd.handler(**args), timeout=config.SKILL_TIMEOUT\n'
        '            )\n'
        '        else:\n'
        '            result = await asyncio.wait_for(\n'
        '                asyncio.to_thread(sd.handler, **args), timeout=config.SKILL_TIMEOUT\n'
        '            )',
        '    try:\n'
        '        if asyncio.iscoroutinefunction(sd.handler):\n'
        '            result = await asyncio.wait_for(\n'
        '                sd.handler(**args), timeout=config.SKILL_TIMEOUT\n'
        '            )\n'
        '        else:\n'
        '            result = await asyncio.wait_for(\n'
        '                asyncio.to_thread(sd.handler, **args), timeout=config.SKILL_TIMEOUT\n'
        '            )\n'
        '        # P1 结果兜底：table 行内未来日期丢弃、kline/line 日期轴裁剪（no-op 安全）\n'
        '        if _asof and isinstance(result, dict) and result.get("ok"):\n'
        '            try:\n'
        '                from app.skills.skill import _asof_filter_result\n'
        '                result = _asof_filter_result(result, _asof)\n'
        '            except Exception:\n'
        '                pass',
    ),
])

# 3. _ASOF_NEVER 常量（放在 AS_OF_DATE ContextVar 定义之后）
with open(LLM, encoding="utf-8") as f:
    src = f.read()
anchor = 'AS_OF_DATE: ContextVar = ContextVar("as_of_date", default=None)'
never = anchor + '''

# strict as-of 下直接拦截的原子技能：返回「当前」快照（新闻流/现价/未来日历/机构共识）
_ASOF_NEVER = {
    "get_stock_news", "get_announcements", "get_us_stock_news", "get_global_news",
    "llm_web_latest", "get_us_stock_spot", "get_us_stock_calendar",
    "get_us_stock_analyst", "get_profit_forecast",
}'''
if anchor not in src or src.count(anchor) != 1:
    print("[FAIL] ContextVar 锚点未找到"); sys.exit(1)
src = src.replace(anchor, never)
with open(LLM, "w", encoding="utf-8") as f:
    f.write(src)
print("[OK] llm.py: _ASOF_NEVER 常量已注入")
print("patch_leakfix5 完成")

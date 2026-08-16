"""Pronoia CLI entrypoint.

Usage examples:
  python -m app.cli serve
  python -m app.cli health
  python -m app.cli agents
  python -m app.cli case list
  python -m app.cli case create --title "测试案例"
  python -m app.cli chat "分析贵州茅台近一个月走势"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable, Iterator, Optional

import requests
import uvicorn


DEFAULT_API_BASE = "http://127.0.0.1:8000/api"


def normalize_api_base(base: str | None) -> str:
    val = (base or os.getenv("PRONOIA_API_BASE") or DEFAULT_API_BASE).strip()
    if not val:
        val = DEFAULT_API_BASE
    val = val.rstrip("/")
    return val if val.endswith("/api") else f"{val}/api"


def csv_items(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def parse_sse_lines(lines: Iterable[bytes | str]) -> Iterator[dict]:
    for raw in lines:
        if isinstance(raw, bytes):
            line = raw.decode("utf-8", errors="replace").strip()
        else:
            line = raw.strip()
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload:
            continue
        yield json.loads(payload)


def print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def print_kv(title: str, value: str) -> None:
    print(f"{title}: {value}")


def request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    payload: Optional[dict] = None,
    timeout: float = 20.0,
) -> object:
    url = f"{base_url}{path}"
    try:
        resp = requests.request(method, url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise SystemExit(f"请求失败：{e}")
    if not resp.ok:
        detail = resp.text.strip()
        raise SystemExit(f"接口报错：{resp.status_code} {detail}")
    try:
        return resp.json()
    except ValueError:
        raise SystemExit(f"接口未返回 JSON：{resp.text[:400]}")


def cmd_serve(args: argparse.Namespace) -> int:
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    obj = request_json("GET", args.base_url, "/health")
    if args.json:
        print_json(obj)
        return 0
    print_kv("ok", str(obj.get("ok")))
    print_kv("llm", str(obj.get("llm")))
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    rows = request_json("GET", args.base_url, "/agents")
    if args.json:
        print_json(rows)
        return 0
    for row in rows:
        print(f"- {row['id']}: {row['name']}")
        print(f"  {row['description']}")
        print(f"  skills: {', '.join(row.get('skills') or [])}")
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    rows = request_json("GET", args.base_url, "/skills")
    if not args.all:
        rows = [row for row in rows if not row.get("internal")]
    if args.json:
        print_json(rows)
        return 0
    for row in rows:
        suffix = " [internal]" if row.get("internal") else ""
        print(f"- {row['name']}{suffix}")
        print(f"  {row['description']}")
        if args.verbose:
            print(f"  category: {row.get('category')}")
            composes = ", ".join(row.get("composes") or [])
            if composes:
                print(f"  composes: {composes}")
    return 0


def cmd_suggestions(args: argparse.Namespace) -> int:
    obj = request_json("GET", args.base_url, "/suggestions", timeout=args.timeout)
    if args.json:
        print_json(obj)
        return 0
    print(f"source: {obj.get('source')}  fallback: {obj.get('fallback')}")
    for idx, item in enumerate(obj.get("items") or [], start=1):
        line = f"{idx}. [{item['mode']}] {item['text']}"
        if item.get("agent"):
            line += f" @{item['agent']}"
        print(line)
        print(f"   {item.get('desc', '')}")
        print(f"   prompt: {item.get('query') or item['text']}")
    return 0


def cmd_case_list(args: argparse.Namespace) -> int:
    rows = request_json("GET", args.base_url, "/cases")
    if args.json:
        print_json(rows)
        return 0
    for row in rows:
        print(f"- {row['id']}  {row['title']}")
        print(f"  updated: {row.get('updated_at')}  messages: {row.get('message_count', 0)}")
    return 0


def cmd_case_create(args: argparse.Namespace) -> int:
    obj = request_json("POST", args.base_url, "/cases", payload={"title": args.title} if args.title else {})
    if args.json:
        print_json(obj)
        return 0
    print(f"created case: {obj['id']}  {obj['title']}")
    return 0


def cmd_case_show(args: argparse.Namespace) -> int:
    obj = request_json("GET", args.base_url, f"/cases/{args.case_id}")
    if args.json:
        print_json(obj)
        return 0
    case = obj["case"]
    print(f"case: {case['id']}  {case['title']}")
    print(f"messages: {len(obj.get('messages') or [])}  artifacts: {len(obj.get('artifacts') or [])}")
    if args.verbose:
        for msg in obj.get("messages") or []:
            text = (msg.get("content") or "").replace("\n", " ").strip()
            print(f"  - [{msg['role']}] {text[:120]}")
        for art in obj.get("artifacts") or []:
            print(f"  - artifact {art['id']} [{art['kind']}] {art['title']}")
    return 0


def cmd_case_delete(args: argparse.Namespace) -> int:
    obj = request_json("DELETE", args.base_url, f"/cases/{args.case_id}")
    if args.json:
        print_json(obj)
        return 0
    print(f"deleted case: {args.case_id}")
    return 0


def cmd_case_report(args: argparse.Namespace) -> int:
    obj = request_json("POST", args.base_url, f"/cases/{args.case_id}/report", timeout=args.timeout)
    if args.json:
        print_json(obj)
        return 0
    print(f"report artifact: {obj['id']}")
    print(f"title: {obj['title']}")
    print(f"kind: {obj['kind']}")
    return 0


def cmd_cache_stats(args: argparse.Namespace) -> int:
    obj = request_json("GET", args.base_url, "/cache/stats")
    if args.json:
        print_json(obj)
        return 0
    print_json(obj)
    return 0


def cmd_cache_clear(args: argparse.Namespace) -> int:
    obj = request_json("POST", args.base_url, "/cache/clear")
    print_json(obj) if args.json else print(f"cleared: {obj.get('cleared')}")
    return 0


def cmd_cache_toggle(args: argparse.Namespace) -> int:
    val = "true" if args.disabled else "false"
    obj = request_json("POST", args.base_url, f"/cache/toggle?disabled={val}")
    print_json(obj) if args.json else print(f"cache disabled: {obj.get('disabled')}")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    url = f"{args.base_url}/chat"
    payload = {
        "case_id": args.case_id,
        "message": args.message,
        "mode": args.mode,
        "agent": args.agent,
        "team_members": csv_items(args.team_members) or None,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        with requests.post(url, json=payload, stream=True, timeout=(5, args.timeout)) as resp:
            if not resp.ok:
                raise SystemExit(f"接口报错：{resp.status_code} {resp.text[:400]}")
            case_id = None
            message_id = None
            text_open = False
            for event in parse_sse_lines(resp.iter_lines()):
                et = event.get("type")
                if et == "meta":
                    case_id = event.get("case_id") or case_id
                    if args.verbose and case_id:
                        print(f"[case] {case_id}")
                elif et == "thinking" and args.show_thinking:
                    print(f"\n[thinking:{event.get('agent') or 'agent'}] {event.get('delta', '')}", end="", flush=True)
                elif et == "token":
                    if not text_open:
                        text_open = True
                    print(event.get("delta", ""), end="", flush=True)
                elif et == "tool_call" and args.verbose:
                    print(f"\n[tool:start] {event.get('agent') or 'agent'} -> {event.get('skill')} {event.get('args') or {}}")
                elif et == "tool_result" and args.verbose:
                    print(f"\n[tool:done] {event.get('skill') or ''} ok={event.get('ok', True)} {event.get('preview') or ''}")
                elif et == "artifact" and args.verbose:
                    art = event.get("artifact") or {}
                    print(f"\n[artifact] {art.get('id')} [{art.get('kind')}] {art.get('title')}")
                elif et == "agent_step" and args.verbose:
                    print(f"\n[agent:{event.get('phase')}] {event.get('agent') or ''} {event.get('note') or event.get('verdict') or ''}")
                elif et == "case_title" and args.verbose:
                    print(f"\n[title] {event.get('title')}")
                elif et == "done":
                    message_id = event.get("message_id") or message_id
                    case_id = event.get("case_id") or case_id
                elif et == "error":
                    raise SystemExit(f"\n流式报错：{event.get('message')}")
    except requests.RequestException as e:
        raise SystemExit(f"请求失败：{e}")
    if text_open:
        print()
    if case_id:
        print(f"\ncase_id: {case_id}")
    if message_id:
        print(f"message_id: {message_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Pronoia CLI")
    ap.add_argument("--base-url", default=normalize_api_base(None), help="API base URL，默认 http://127.0.0.1:8000/api")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")

    sub = ap.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", aliases=["sv"], help="启动后端服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    health = sub.add_parser("health", aliases=["h"], help="检查系统健康状态")
    health.set_defaults(func=cmd_health)

    agents = sub.add_parser("agents", aliases=["ag"], help="列出 agents")
    agents.set_defaults(func=cmd_agents)

    skills = sub.add_parser("skills", aliases=["sk"], help="列出 skills")
    skills.add_argument("--all", action="store_true", help="包含 internal tools")
    skills.add_argument("--verbose", action="store_true", help="展示更多字段")
    skills.set_defaults(func=cmd_skills)

    suggestions = sub.add_parser("suggestions", aliases=["sg"], help="获取首页推荐")
    suggestions.add_argument("--timeout", type=float, default=8.0)
    suggestions.set_defaults(func=cmd_suggestions)

    chat = sub.add_parser("chat", aliases=["q"], help="发起一次对话")
    chat.add_argument("message", help="问题文本")
    chat.add_argument("--mode", choices=["auto", "agent", "team"], default="auto")
    chat.add_argument("--agent", help="mode=agent 时指定 agent_id")
    chat.add_argument("--case-id", help="复用已有 case")
    chat.add_argument("--team-members", help="逗号分隔的团队专家 id 列表")
    chat.add_argument("--timeout", type=float, default=180.0, help="流式读取超时秒数")
    chat.add_argument("--verbose", action="store_true", help="输出工具/步骤事件")
    chat.add_argument("--show-thinking", action="store_true", help="输出 thinking 片段")
    chat.set_defaults(func=cmd_chat)

    case = sub.add_parser("case", aliases=["c"], help="案例管理")
    case_sub = case.add_subparsers(dest="case_command", required=True)

    case_list = case_sub.add_parser("list", aliases=["ls"], help="列出案例")
    case_list.set_defaults(func=cmd_case_list)

    case_create = case_sub.add_parser("create", aliases=["new"], help="创建案例")
    case_create.add_argument("--title", help="案例标题")
    case_create.set_defaults(func=cmd_case_create)

    case_show = case_sub.add_parser("show", aliases=["get"], help="查看案例")
    case_show.add_argument("case_id")
    case_show.add_argument("--verbose", action="store_true")
    case_show.set_defaults(func=cmd_case_show)

    case_delete = case_sub.add_parser("delete", aliases=["rm"], help="删除案例")
    case_delete.add_argument("case_id")
    case_delete.set_defaults(func=cmd_case_delete)

    case_report = case_sub.add_parser("report", aliases=["rpt"], help="生成研究报告")
    case_report.add_argument("case_id")
    case_report.add_argument("--timeout", type=float, default=180.0)
    case_report.set_defaults(func=cmd_case_report)

    cache = sub.add_parser("cache", aliases=["cc"], help="缓存管理")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)

    cache_stats = cache_sub.add_parser("stats", aliases=["ls"], help="查看缓存统计")
    cache_stats.set_defaults(func=cmd_cache_stats)

    cache_clear = cache_sub.add_parser("clear", aliases=["rm"], help="清空缓存")
    cache_clear.set_defaults(func=cmd_cache_clear)

    cache_toggle = cache_sub.add_parser("toggle", aliases=["tg"], help="切换缓存开关")
    cache_toggle.add_argument("--disabled", action="store_true", help="禁用缓存")
    cache_toggle.set_defaults(func=cmd_cache_toggle)

    def cmd_bt(args: argparse.Namespace) -> int:
        from .event_backtest.cli import build_bt_parser

        bt_parser = build_bt_parser()
        bt_args = bt_parser.parse_args(args.bt_argv)
        return int(bt_args.func(bt_args) or 0)

    bt = sub.add_parser("bt", aliases=["backtest", "b"], help="事件回测（离线）")
    bt.add_argument("bt_argv", nargs=argparse.REMAINDER)
    bt.set_defaults(func=cmd_bt)

    return ap


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.base_url = normalize_api_base(args.base_url)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

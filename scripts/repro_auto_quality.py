#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


CASES = {
    "c04": "检查目标公司最近三年经营现金流、应收、存货、资本化支出和非经常损益，指出盈利质量风险及可能反证。",
    "c06": "截至测试日，判断宁德时代（300750.SZ）的20/60/120日趋势状态；说明前复权/后复权选择、交易日对齐和数据截止时间。",
    "c08": "比较目标行业与沪深300近20/60/120日相对强弱、成交扩散度和领涨集中度，判断趋势健康度。",
    "c10": "构建过去两年某类A股政策事件样本，输出事件时间、受影响标的、基准、T+1/T+5/T+20超额收益，并说明去重规则。",
    "c12": "审计一份事件策略回测是否存在未来函数、幸存者偏差、公告时间错位、重复事件和复权错误，并给出修复顺序。",
    "c14": "用户持有5只A股且单一行业占比过高。分析集中度、相关性和事件暴露，提出分阶段行动方案，但不得直接替用户下单。",
    "c18": "假设一个行情源超时且一个新闻源返回冲突信息：说明降级路径、冲突处理、哪些结论暂停，并保留可审计错误记录。",
    "c16": "分析某项原材料价格变化对A股产业链三层公司的收入、成本、库存和议价权传导，给出方向、时滞与证据等级。",
    "v05": "截至T，列未来90天可验证催化剂；区分已公告事项、市场一致预期和未经证实传闻，并给失效条件。",
    "n02": "输出三档情景、概率、催化剂、风险和可证伪假设，并给出T+5/T+20复盘字段。",
    "q01": "构建过去两年指定政策事件数据集：事件原文、发布时间、交易日映射、涉及标的、基准和T+1/T+5/T+20收益。",
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "case"


def post_chat(base_url: str, message: str, *, mode: str = "auto", agent: str | None = None) -> list[dict]:
    payload = {"message": message, "mode": mode}
    if agent:
        payload["agent"] = agent
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                events.append({"type": "decode_error", "raw": line[6:]})
    return events


def summarize(events: list[dict]) -> dict:
    final_text = "".join(ev.get("delta", "") for ev in events if ev.get("type") == "token")
    tool_calls = [ev for ev in events if ev.get("type") == "tool_call"]
    tool_results = [ev for ev in events if ev.get("type") == "tool_result"]
    artifacts = [ev for ev in events if ev.get("type") == "artifact"]
    errors = [ev for ev in events if ev.get("type") == "error"]
    meta = next((ev for ev in events if ev.get("type") == "meta"), {})
    done = next((ev for ev in reversed(events) if ev.get("type") == "done"), {})
    return {
        "case_id": meta.get("case_id"),
        "mode": meta.get("mode"),
        "agent": meta.get("agent"),
        "tool_call_count": len(tool_calls),
        "tool_result_count": len(tool_results),
        "artifact_count": len(artifacts),
        "error_count": len(errors),
        "message_id": done.get("message_id"),
        "final_text_chars": len(final_text),
        "final_text_preview": final_text[:400],
        "tool_names": [ev.get("skill") for ev in tool_calls],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Pronoia auto-mode low-score cases.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument(
        "--cases",
        nargs="+",
        default=["c06", "c10"],
        help=f"Case ids to replay. Available: {', '.join(sorted(CASES))}",
    )
    parser.add_argument("--mode", default="auto", choices=["auto", "agent", "team"])
    parser.add_argument("--agent", default=None, help="Agent id when mode=agent")
    parser.add_argument("--outdir", default=".dbg/repro-auto-quality", help="Output directory")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for case_id in args.cases:
        prompt = CASES.get(case_id)
        if not prompt:
            print(f"[skip] unknown case: {case_id}", file=sys.stderr)
            failures += 1
            continue
        safe_name = slugify(case_id)
        print(f"[run] {case_id}: {prompt}")
        try:
            events = post_chat(args.base_url, prompt, mode=args.mode, agent=args.agent)
        except urllib.error.URLError as exc:
            print(f"[error] {case_id}: {exc}", file=sys.stderr)
            failures += 1
            continue
        summary = summarize(events)
        (outdir / f"{safe_name}.events.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (outdir / f"{safe_name}.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        final_text = "".join(ev.get("delta", "") for ev in events if ev.get("type") == "token")
        (outdir / f"{safe_name}.answer.md").write_text(final_text, encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

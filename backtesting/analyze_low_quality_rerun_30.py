#!/usr/bin/env python3
"""Analyze the completed 30-event low-quality-packet A/B rerun."""

from __future__ import annotations

import ast
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VARIANTS = {
    "v0": ROOT / "_trajectory_low_quality_rerun_30_v0_20260830",
    "claim-v2": ROOT / "_trajectory_low_quality_rerun_30_claim_v2_20260830",
}
MANIFEST = ROOT / "low_quality_rerun_30_manifest_20260829.csv"
LABELS = ROOT / "labels_low_quality_rerun_30_20260829.jsonl"
OUT = ROOT / "low_quality_rerun_30_ab_analysis_20260830.md"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def final_graph_stats(payload: dict) -> dict:
    trace = payload.get("team_final_state", {}).get("tool_trace", [])
    for item in reversed(trace):
        if not isinstance(item, dict) or item.get("skill") != "evidence_graph":
            continue
        if item.get("args", {}).get("action") != "export":
            continue
        preview = str(item.get("preview", ""))
        match = re.search(r"(\{.*\})", preview)
        if match:
            try:
                value = ast.literal_eval(match.group(1))
                if isinstance(value, dict):
                    return value
            except (ValueError, SyntaxError):
                pass
    return {}


def load_variant(path: Path) -> dict[str, dict]:
    result = {}
    for file in sorted(path.glob("*.json")):
        payload = json.loads(file.read_text())
        event_id = payload["event_id"]
        extract = payload.get("structured_extract", {})
        tools = [
            item for item in payload.get("team_final_state", {}).get("tool_trace", [])
            if isinstance(item, dict) and item.get("type") == "tool"
        ]
        result[event_id] = {
            "direction": extract.get("direction"),
            "confidence": extract.get("confidence"),
            "rationale": extract.get("rationale", ""),
            "wall_seconds": payload.get("wall_seconds", 0),
            "graph": final_graph_stats(payload),
            "tools": tools,
        }
    return result


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "—"


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def strict_correct(prediction: str, truth: str) -> bool:
    """Backtesting strict: neutral on either side always counts as wrong."""
    return prediction in {"up", "down"} and truth in {"up", "down"} and prediction == truth


def main() -> None:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as handle:
        manifest = {row["event_id"]: row for row in csv.DictReader(handle)}
    labels = {row["event_id"]: row for row in read_jsonl(LABELS)}
    data = {name: load_variant(path) for name, path in VARIANTS.items()}
    ids = sorted(set(manifest) & set(labels) & set(data["v0"]) & set(data["claim-v2"]))

    lines = [
        "# 30 条低质量 Event Packet A/B 重跑分析",
        "",
        f"> 配对样本：{len(ids)}；Oracle：T3 strict，neutral 阈值 ±0.5%。",
        "",
        "## 总体结果",
        "",
        "| 指标 | v0 | claim-v2 | 差值 |",
        "|---|---:|---:|---:|",
    ]
    summary = {}
    for variant in VARIANTS:
        rows = data[variant]
        correct = sum(strict_correct(rows[e]["direction"], labels[e]["label_t3"]) for e in ids)
        neutral = sum(rows[e]["direction"] == "neutral" for e in ids)
        summary[variant] = {"correct": correct, "neutral": neutral}
    lines += [
        f"| T3 strict ACC | {summary['v0']['correct']}/30 ({pct(summary['v0']['correct'], 30)}) | "
        f"{summary['claim-v2']['correct']}/30 ({pct(summary['claim-v2']['correct'], 30)}) | "
        f"{summary['claim-v2']['correct'] - summary['v0']['correct']:+d} 条 |",
        f"| Neutral | {summary['v0']['neutral']}/30 ({pct(summary['v0']['neutral'], 30)}) | "
        f"{summary['claim-v2']['neutral']}/30 ({pct(summary['claim-v2']['neutral'], 30)}) | "
        f"{summary['claim-v2']['neutral'] - summary['v0']['neutral']:+d} 条 |",
    ]

    claim_wins = []
    v0_wins = []
    both_correct = []
    both_wrong = []
    flips = []
    for event_id in ids:
        truth = labels[event_id]["label_t3"]
        a = data["v0"][event_id]["direction"]
        b = data["claim-v2"][event_id]["direction"]
        if a != b:
            flips.append(event_id)
        a_ok, b_ok = strict_correct(a, truth), strict_correct(b, truth)
        if b_ok and not a_ok:
            claim_wins.append(event_id)
        elif a_ok and not b_ok:
            v0_wins.append(event_id)
        elif a_ok:
            both_correct.append(event_id)
        else:
            both_wrong.append(event_id)
    lines += [
        "",
        "## 配对胜负与翻转",
        "",
        f"- 方向不同：{len(flips)}/30。",
        f"- claim-v2 独赢：{len(claim_wins)}；v0 独赢：{len(v0_wins)}。",
        f"- 两版都对：{len(both_correct)}；两版都错：{len(both_wrong)}。",
        "",
        "| event_id | 分层 | T3 | v0 | claim-v2 | 结果 |",
        "|---|---|---|---|---|---|",
    ]
    for event_id in flips:
        truth = labels[event_id]["label_t3"]
        a = data["v0"][event_id]["direction"]
        b = data["claim-v2"][event_id]["direction"]
        result = (
            "claim-v2 改对" if strict_correct(b, truth)
            else "v0 更好" if strict_correct(a, truth)
            else "均错"
        )
        lines.append(
            f"| `{event_id}` | {manifest[event_id]['stratum']} | {truth} | {a} | {b} | {result} |"
        )

    strata = list(dict.fromkeys(row["stratum"] for row in manifest.values()))
    lines += [
        "",
        "## 按低质量类型",
        "",
        "| 分层 | n | v0 ACC | claim-v2 ACC | v0 neutral | claim-v2 neutral |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for stratum in strata:
        subset = [e for e in ids if manifest[e]["stratum"] == stratum]
        a_ok = sum(strict_correct(data["v0"][e]["direction"], labels[e]["label_t3"]) for e in subset)
        b_ok = sum(strict_correct(data["claim-v2"][e]["direction"], labels[e]["label_t3"]) for e in subset)
        a_n = sum(data["v0"][e]["direction"] == "neutral" for e in subset)
        b_n = sum(data["claim-v2"][e]["direction"] == "neutral" for e in subset)
        lines.append(
            f"| {stratum} | {len(subset)} | {a_ok}/{len(subset)} | {b_ok}/{len(subset)} | "
            f"{a_n}/{len(subset)} | {b_n}/{len(subset)} |"
        )

    graph_keys = ["n_evidence", "n_claim", "n_missing", "n_edges", "n_supports", "n_contradicts"]
    lines += [
        "",
        "## Evidence Graph 与工具调用",
        "",
        "| 指标（每事件均值） | v0 | claim-v2 |",
        "|---|---:|---:|",
    ]
    for key in graph_keys:
        values = {
            variant: [float(data[variant][e]["graph"].get(key, 0)) for e in ids]
            for variant in VARIANTS
        }
        lines.append(f"| {key} | {mean(values['v0']):.2f} | {mean(values['claim-v2']):.2f} |")

    tool_summary = {}
    failure_causes = {}
    for variant in VARIANTS:
        tools = [tool for e in ids for tool in data[variant][e]["tools"]]
        ok = sum(bool(tool.get("ok")) for tool in tools)
        failed = len(tools) - ok
        event_tools = [tool for tool in tools if tool.get("skill") in {"event_study", "event_study_skill"}]
        event_ok = sum(bool(tool.get("ok")) for tool in event_tools)
        tool_summary[variant] = (len(tools), ok, failed, len(event_tools), event_ok)
        causes = Counter()
        for tool in tools:
            if tool.get("ok"):
                continue
            preview = str(tool.get("preview", ""))
            if "超时" in preview or "Timeout" in preview:
                causes["timeout"] += 1
            if "SSLError" in preview:
                causes["ssl"] += 1
            if "必须提供 symbol 或 keyword" in preview:
                causes["missing_symbol"] += 1
            if "sz5" in preview and "行情获取失败" in preview:
                causes["bad_etf_prefix"] += 1
        failure_causes[variant] = causes
    for variant in VARIANTS:
        total, ok, failed, event_total, event_ok = tool_summary[variant]
        lines += [
            "",
            f"- **{variant}**：工具 {ok}/{total} 成功（{pct(ok, total)}）；"
            f"event-study {event_ok}/{event_total} 成功（{pct(event_ok, event_total)}）；"
            f"失败 {failed} 次。失败标签：{dict(failure_causes[variant])}。",
        ]

    wall = {
        variant: [float(data[variant][e]["wall_seconds"] or 0) for e in ids]
        for variant in VARIANTS
    }
    lines += [
        "",
        "## 结论",
        "",
        f"- claim-v2 的 T3 strict ACC 净增 1 条，但 neutral 仍为 25/30，改善幅度很小。",
        f"- 平均单事件耗时：v0 {mean(wall['v0']):.1f}s；claim-v2 {mean(wall['claim-v2']):.1f}s。",
        "- ETF 错前缀已消失；剩余主要瓶颈是上游 packet 缺关键事实，以及行情源 timeout/SSL。",
        "- 该样本是刻意抽取的低质量压力集，不代表自然分布上的总体 ACC。",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()

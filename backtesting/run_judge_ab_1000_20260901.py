#!/usr/bin/env python3
"""Run a fixed-Evidence-Graph A/B for the legacy and no-confidence-gate judges."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import config  # noqa: E402
from backend.app.llm import get_client  # noqa: E402
from backend.scripts.smoke_deep_researcher_prompt_ab import _direction_context  # noqa: E402


EVENTS = ROOT / "backtesting/events_cn_us_1000_v1.jsonl"
LABELS = ROOT / "backtesting/labels_cn_us_1000_v1.jsonl"
BASE_TRAJECTORY = ROOT / "backtesting/_trajectory_ckpt_tf_cn_us_1000_v1"
ALT_TRAJECTORIES = [
    ROOT / "backtesting/_trajectory_skill_failure_rerun_120_v0_20260830",
    ROOT / "backtesting/_trajectory_low_quality_rerun_30_v0_20260830",
    ROOT / "backtesting/_trajectory_skill_failure_rerun_120_claim_v2_20260830",
    ROOT / "backtesting/_trajectory_low_quality_rerun_30_claim_v2_20260830",
]
OUT_ROOT = ROOT / "backtesting/judge_ab_no_conf_gate_1000_20260901"
VARIANTS = ("legacy_v1", "no_conf_gate")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def last_graph(obj: dict[str, Any]) -> dict[str, Any] | None:
    graphs = [
        row.get("artifact", {}).get("payload")
        for row in obj.get("trajectory_sse_events") or []
        if isinstance(row, dict)
        and row.get("type") == "artifact"
        and isinstance(row.get("artifact"), dict)
        and row["artifact"].get("kind") == "graph"
        and isinstance(row["artifact"].get("payload"), dict)
    ]
    return graphs[-1] if graphs else None


def load_graph(event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    event_id = event["event_id"]
    primary = BASE_TRAJECTORY / f"{event_id}.json"
    obj = json.loads(primary.read_text())
    graph = last_graph(obj)
    if graph is not None:
        return graph, "native_primary"

    for directory in ALT_TRAJECTORIES:
        path = directory / f"{event_id}.json"
        if not path.exists():
            continue
        alt = json.loads(path.read_text())
        graph = last_graph(alt)
        if graph is not None:
            return graph, f"native_rerun:{directory.name}"

    # A small set of historical runs completed without exporting a graph artifact.
    # Keep them in the 1000-row sensitivity analysis with an explicit proxy
    # graph, while excluding them from the native-graph primary result.
    extract = obj.get("structured_extract") or {}
    rationale = str(extract.get("rationale") or "").strip()
    packet = str(obj.get("as_of_packet") or event.get("event_text") or "").strip()
    graph = {
        "nodes": [
            {
                "id": "proxy_claim",
                "kind": "claim",
                "status": "needs_more",
                "title": "历史 trajectory 的结构化证据摘要（代理图谱）",
                "body": rationale or "历史 trajectory 未导出 Evidence Graph。",
            },
            {
                "id": "proxy_packet",
                "kind": "evidence",
                "title": "严格 as-of 事件 packet",
                "body": packet[:5000],
            },
            {
                "id": "proxy_missing",
                "kind": "missing",
                "title": "原始 Evidence Graph artifact 缺失",
                "body": "此条仅用于1000条敏感性分析，不纳入984条原生图主结果。",
            },
        ],
        "edges": [{"src": "proxy_claim", "dst": "proxy_packet", "relation": "supports"}],
        "sufficient": False,
    }
    return graph, "proxy_structured_extract"


def prompt_for(event: dict[str, Any], graph: dict[str, Any], variant: str) -> str:
    packet = {
        key: event.get(key)
        for key in ("market", "symbol", "event_time", "event_type_l2", "title", "event_text", "benchmark")
    }
    confidence_rule = (
        "confidence 小于 0.60 的方向判断会被系统改为 neutral。"
        if variant == "legacy_v1"
        else "confidence 只表示判断的可靠程度，不改变净分确定的方向。"
    )
    return f"""你是严格 as-of 的独立方向裁决器。只允许使用事件 packet 与下方 Evidence Graph；
不得补充事件日之后的知识。预测事件后 T+3 benchmark-relative CAR，方向为 up/down/neutral。

必须沿用 backtesting 评分卡：
1. 从已被 supports/contradicts 连接的 claims 中提取方向信号，强信号 3 分、中等信号 2 分、弱信号 1 分；
2. 净分 = up 分数 - down 分数。净分>0 选 up，净分<0 选 down；只有净分=0、完全没有方向信号，
   或同强度信号精确抵消时才选 neutral；
3. 不要因为信息不完整就自动 neutral。存在至少一条有实质证据支持、未被反驳的方向 claim 时，应给方向并降低置信度；
4. neutral 是少数情形，整体目标约 15~20%，不是默认答案；弱方向的 confidence 应为 0.60~0.65，
   中等方向 0.66~0.75，强方向 0.76~0.85；neutral confidence=0.50；
5. A股减持/稀释/普通并购软先验偏 down，明确优质资产注入、强业绩改善偏 up；
   美股 beat/增长上修偏 up，miss/稀释偏 down。先验只能在图中证据支持时使用。

先综合 supports/contradicts、claim status 与 missing；必须在 rationale 中简述净分依据。
{confidence_rule}
只输出单个 JSON：{{"pred_direction":"up|down|neutral","confidence":0.0,"rationale":"中文理由"}}

EVENT_PACKET:
{json.dumps(packet, ensure_ascii=False)}

EVIDENCE_GRAPH:
{_direction_context(graph)}"""


def parse_response(text: str, variant: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.S)
    obj: dict[str, Any] = {}
    if match:
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    direction = str(obj.get("pred_direction") or "").strip().lower()
    if direction not in {"up", "down", "neutral"}:
        found = re.search(r"\b(up|down|neutral)\b", text, flags=re.I)
        direction = found.group(1).lower() if found else "neutral"
    try:
        confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.5)))
    except (TypeError, ValueError):
        confidence = 0.5
    raw_direction = direction
    gate = variant == "legacy_v1" and confidence < 0.60 and direction != "neutral"
    if gate:
        direction = "neutral"
    return {
        "pred_direction": direction,
        "raw_direction": raw_direction,
        "confidence": round(confidence, 4),
        "confidence_gate_applied": gate,
        "rationale": str(obj.get("rationale") or text)[:1200],
        "raw_response": text[:2200],
    }


def result_valid(path: Path) -> bool:
    try:
        obj = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return not obj.get("error") and obj.get("direction", {}).get("pred_direction") in {"up", "down", "neutral"}


class RateLimiter:
    def __init__(self, interval: float):
        self.interval = interval
        self.lock = asyncio.Lock()
        self.last = 0.0

    async def wait(self) -> None:
        async with self.lock:
            delay = max(0.0, self.interval - (time.monotonic() - self.last))
            if delay:
                await asyncio.sleep(delay)
            self.last = time.monotonic()


async def judge_one(
    event: dict[str, Any],
    label: dict[str, Any],
    graph: dict[str, Any],
    graph_source: str,
    variant: str,
    semaphore: asyncio.Semaphore,
    limiter: RateLimiter,
) -> tuple[str, str, bool]:
    path = OUT_ROOT / variant / f"{event['event_id']}.json"
    if result_valid(path):
        return variant, event["event_id"], True
    path.parent.mkdir(parents=True, exist_ok=True)
    error = ""
    direction: dict[str, Any] = {}
    started = time.monotonic()
    attempts = 0
    for attempt in range(1, 5):
        attempts = attempt
        try:
            async with semaphore:
                await limiter.wait()
                response = await asyncio.wait_for(
                    get_client().chat.completions.create(
                        model=config.LLM_MODEL,
                        messages=[
                            {"role": "system", "content": "你是固定、保守、可复现的金融事件方向裁决器。"},
                            {"role": "user", "content": prompt_for(event, graph, variant)},
                        ],
                        temperature=0,
                        max_tokens=500,
                    ),
                    timeout=60,
                )
            direction = parse_response(response.choices[0].message.content or "", variant)
            error = ""
            break
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            print(f"retry {variant} {event['event_id']} {attempt}/4 {error}", flush=True)
            if attempt < 4:
                await asyncio.sleep(2 ** (attempt - 1))
    payload = {
        "event_id": event["event_id"],
        "market": event.get("market"),
        "event_type_l2": event.get("event_type_l2"),
        "title": event.get("title"),
        "judge_version": variant,
        "graph_source": graph_source,
        "attempts": attempts,
        "wall_seconds": round(time.monotonic() - started, 3),
        "error": error,
        "oracle": {
            key: label.get(key)
            for key in ("label_t3", "car_t3", "label_avg_all", "label_consensus66")
        },
        "direction": direction,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.replace(tmp, path)
    return variant, event["event_id"], not error


def load_results(variant: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in (OUT_ROOT / variant).glob("*.json"):
        obj = json.loads(path.read_text())
        if result_valid(path):
            out[obj["event_id"]] = obj
    return out


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    exact = sum(r["direction"]["pred_direction"] == r["oracle"]["label_t3"] for r in rows)
    strict = sum(
        r["oracle"]["label_t3"] in {"up", "down"}
        and r["direction"]["pred_direction"] == r["oracle"]["label_t3"]
        for r in rows
    )
    directional_oracle = sum(r["oracle"]["label_t3"] in {"up", "down"} for r in rows)
    actions = [r for r in rows if r["direction"]["pred_direction"] in {"up", "down"}]
    action_correct = sum(r["direction"]["pred_direction"] == r["oracle"]["label_t3"] for r in actions)
    false_neutral = sum(
        r["oracle"]["label_t3"] in {"up", "down"}
        and r["direction"]["pred_direction"] == "neutral"
        for r in rows
    )
    reverse = sum(
        r["oracle"]["label_t3"] in {"up", "down"}
        and r["direction"]["pred_direction"] in {"up", "down"}
        and r["direction"]["pred_direction"] != r["oracle"]["label_t3"]
        for r in rows
    )
    return {
        "n": n,
        "exact": exact,
        "strict": strict,
        "directional_oracle": directional_oracle,
        "actions": len(actions),
        "action_correct": action_correct,
        "false_neutral": false_neutral,
        "reverse": reverse,
        "gate_count": sum(bool(r["direction"].get("confidence_gate_applied")) for r in rows),
        "predictions": Counter(r["direction"]["pred_direction"] for r in rows),
    }


def pct(num: int, den: int) -> str:
    return f"{100 * num / den:.2f}%" if den else "—"


def paired_stats(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]], ids: set[str]) -> dict[str, Any]:
    counts = Counter()
    transitions = Counter()
    strict_old_only = strict_new_only = 0
    for event_id in sorted(ids):
        o, n = old[event_id], new[event_id]
        truth = o["oracle"]["label_t3"]
        op = o["direction"]["pred_direction"]
        np = n["direction"]["pred_direction"]
        oc, nc = op == truth, np == truth
        transitions[f"{op}->{np}"] += 1
        counts["changed"] += op != np
        if oc and nc:
            counts["both_correct"] += 1
        elif oc:
            counts["old_only"] += 1
        elif nc:
            counts["new_only"] += 1
        else:
            counts["both_wrong"] += 1
        if truth in {"up", "down"}:
            strict_old_only += oc and not nc
            strict_new_only += nc and not oc
    discordant = strict_old_only + strict_new_only
    # Exact two-sided sign/McNemar test using the binomial distribution.
    if discordant:
        tail = sum(math.comb(discordant, k) for k in range(0, min(strict_old_only, strict_new_only) + 1))
        pvalue = min(1.0, 2.0 * tail / (2 ** discordant))
    else:
        pvalue = 1.0
    return {
        **counts,
        "strict_old_only": strict_old_only,
        "strict_new_only": strict_new_only,
        "strict_mcnemar_p": pvalue,
        "transitions": transitions,
    }


def graph_quality(graphs: dict[str, tuple[dict[str, Any], str]], ids: set[str]) -> dict[str, Any]:
    totals = Counter()
    for event_id in ids:
        graph, source = graphs[event_id]
        nodes, edges = graph.get("nodes") or [], graph.get("edges") or []
        totals["claims"] += sum(n.get("kind") == "claim" for n in nodes)
        totals["evidence"] += sum(n.get("kind") == "evidence" for n in nodes)
        totals["missing"] += sum(n.get("kind") == "missing" for n in nodes)
        totals["edges"] += len(edges)
        totals["zero_claim"] += not any(n.get("kind") == "claim" for n in nodes)
        totals["sufficient"] += bool(graph.get("sufficient"))
        totals["proxy"] += source == "proxy_structured_extract"
    n = len(ids)
    return {**totals, "n": n, "claims_per_graph": totals["claims"] / n, "edges_per_graph": totals["edges"] / n}


def report(events: list[dict[str, Any]], graphs: dict[str, tuple[dict[str, Any], str]]) -> None:
    old, new = load_results("legacy_v1"), load_results("no_conf_gate")
    paired = set(old) & set(new)
    native = {eid for eid in paired if graphs[eid][1] != "proxy_structured_extract"}
    cohorts = [("原生 Evidence Graph（主结果）", native), ("全量（含16条代理图敏感性分析）", paired)]
    lines = [
        "# 新旧裁决器固定 Evidence Graph 全量 A/B（2026-09-01）",
        "",
        "> 两版读取同一事件 packet 与同一 Evidence Graph。旧版提示低 confidence 会被改为 neutral，且保留 `<0.60 → neutral` 后处理；新版将 confidence 与方向解耦。",
        f"> 1000 个历史 trajectory 中，{len(native)} 条可取得原生 graph artifact；{len(paired) - len(native)} 条用同次运行的 structured_extract + as-of packet 构成显式代理图，仅纳入敏感性分析。",
        "",
    ]
    for title, ids in cohorts:
        om = metrics([old[eid] for eid in ids])
        nm = metrics([new[eid] for eid in ids])
        ps = paired_stats(old, new, ids)
        q = graph_quality(graphs, ids)
        lines += [
            f"## {title}",
            "",
            "| 指标 | 旧 legacy_v1 | 新 no-conf-gate | 差值 |",
            "|---|---:|---:|---:|",
            f"| 有效样本 | {om['n']} | {nm['n']} | — |",
            f"| T3 strict ACC | {om['strict']}/{om['n']} ({pct(om['strict'], om['n'])}) | {nm['strict']}/{nm['n']} ({pct(nm['strict'], nm['n'])}) | {(nm['strict']-om['strict'])/om['n']*100:+.2f}pp |",
            f"| T3 三分类 exact | {om['exact']}/{om['n']} ({pct(om['exact'], om['n'])}) | {nm['exact']}/{nm['n']} ({pct(nm['exact'], nm['n'])}) | {(nm['exact']-om['exact'])/om['n']*100:+.2f}pp |",
            f"| 非 neutral Oracle ACC | {pct(om['strict'], om['directional_oracle'])} | {pct(nm['strict'], nm['directional_oracle'])} | — |",
            f"| 方向覆盖率 | {pct(om['actions'], om['n'])} | {pct(nm['actions'], nm['n'])} | — |",
            f"| 出手 precision | {pct(om['action_correct'], om['actions'])} | {pct(nm['action_correct'], nm['actions'])} | — |",
            f"| False neutral | {om['false_neutral']} | {nm['false_neutral']} | {nm['false_neutral']-om['false_neutral']:+d} |",
            f"| 直接反向错误 | {om['reverse']} | {nm['reverse']} | {nm['reverse']-om['reverse']:+d} |",
            f"| confidence 硬闸触发 | {om['gate_count']} | {nm['gate_count']} | — |",
            "",
            f"预测分布：旧版 `{dict(om['predictions'])}`；新版 `{dict(nm['predictions'])}`。",
            "",
            f"配对 exact：两版都对 {ps['both_correct']}；仅旧版对 {ps['old_only']}；仅新版对 {ps['new_only']}；两版都错 {ps['both_wrong']}；方向变化 {ps['changed']}。",
            f"方向 Oracle 上的配对净胜负：旧版独赢 {ps['strict_old_only']}，新版独赢 {ps['strict_new_only']}；exact McNemar p={ps['strict_mcnemar_p']:.4f}。",
            "",
            f"图谱概况：{q['n']} 张，平均 claims {q['claims_per_graph']:.2f}、edges {q['edges_per_graph']:.2f}；零 claim {q['zero_claim']}；sufficient {q['sufficient']}；代理图 {q['proxy']}。",
            "",
            "方向迁移：",
            "",
            *[f"- `{key}`: {value}" for key, value in ps["transitions"].most_common()],
            "",
        ]

    full_ids = paired
    for market in ("CN", "US"):
        ids = {eid for eid in full_ids if old[eid].get("market") == market}
        om, nm = metrics([old[eid] for eid in ids]), metrics([new[eid] for eid in ids])
        lines += [
            f"## {market} 分层",
            "",
            f"样本 {len(ids)}；strict ACC：旧 {pct(om['strict'], om['n'])} → 新 {pct(nm['strict'], nm['n'])}；exact：旧 {pct(om['exact'], om['n'])} → 新 {pct(nm['exact'], nm['n'])}；false-neutral：{om['false_neutral']} → {nm['false_neutral']}。",
            "",
        ]

    lines += [
        "## 解释边界",
        "",
        "- 本实验只测裁决器；Evidence Graph 固定，因此不衡量 `ar_decomposer` 修复对重新构图后的影响。",
        "- 模型即使 `temperature=0` 也可能存在服务端非完全确定性；应以配对净胜负及 McNemar 检验判断，而不是只看少量翻转。",
        f"- {len(paired) - len(native)} 条代理图含历史结构化摘要，不等同于正式 Evidence Graph，因此主结论以 {len(native)} 条原生图为准。",
        "",
    ]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "report.md").write_text("\n".join(lines))
    summary = {
        "paired_n": len(paired),
        "native_n": len(native),
        "legacy": metrics([old[eid] for eid in paired]),
        "new": metrics([new[eid] for eid in paired]),
        "paired": paired_stats(old, new, paired),
    }
    def serializable(value: Any) -> Any:
        if isinstance(value, Counter):
            return dict(value)
        if isinstance(value, dict):
            return {k: serializable(v) for k, v in value.items()}
        return value
    (OUT_ROOT / "summary.json").write_text(json.dumps(serializable(summary), ensure_ascii=False, indent=2))
    print(f"report {OUT_ROOT / 'report.md'}", flush=True)


async def main() -> None:
    events = read_jsonl(EVENTS)
    labels = {row["event_id"]: row for row in read_jsonl(LABELS)}
    graphs = {event["event_id"]: load_graph(event) for event in events}
    sources = Counter(source.split(":", 1)[0] for _, source in graphs.values())
    print(f"events={len(events)} graph_sources={dict(sources)}", flush=True)

    concurrency = int(os.environ.get("JUDGE_CONCURRENCY", "4"))
    limiter = RateLimiter(float(os.environ.get("JUDGE_INTERVAL", "0.65")))
    semaphore = asyncio.Semaphore(concurrency)
    jobs = [
        (event, labels[event["event_id"]], *graphs[event["event_id"]], variant)
        for event in events
        for variant in VARIANTS
    ]
    random.Random(20260901).shuffle(jobs)
    limit = int(os.environ.get("JUDGE_LIMIT", "0") or 0)
    if limit:
        jobs = jobs[:limit]
    done = 0

    async def run(job: tuple[Any, ...]) -> None:
        nonlocal done
        event, label, graph, source, variant = job
        await judge_one(event, label, graph, source, variant, semaphore, limiter)
        done += 1
        if done % 25 == 0 or done == len(jobs):
            old_n = len(load_results("legacy_v1"))
            new_n = len(load_results("no_conf_gate"))
            print(f"progress jobs={done}/{len(jobs)} valid_old={old_n} valid_new={new_n}", flush=True)

    await asyncio.gather(*(run(job) for job in jobs))
    if not limit:
        report(events, graphs)


if __name__ == "__main__":
    asyncio.run(main())

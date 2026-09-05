"""对固定 Evidence 重跑 Deep Researcher persona，隔离评估 Evidence Graph 质量。"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.roster import get_agent, resolve_deep_researcher_prompt_variant, system_prompt
from app import config
from app.llm import get_client, noop_artifact_store, run_agent
from app.skills.evidence_graph import EvidenceGraph, check_claim_title, eg_attach, eg_detach


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _trajectory_evidence(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    obj = json.loads(path.read_text(encoding="utf-8"))
    graphs = []
    for event in obj.get("trajectory_sse_events") or []:
        artifact = event.get("artifact") or {}
        if event.get("type") == "artifact" and artifact.get("kind") == "graph":
            graphs.append(artifact.get("payload") or {})
    if not graphs:
        return []
    allowed = {"expert_finding", "tool_trace"}
    return [
        node for node in (graphs[-1].get("nodes") or [])
        if node.get("kind") == "evidence" and node.get("source_kind") in allowed
    ][:10]


def _seed_graph(event: dict[str, Any], trajectory_dir: Path) -> tuple[EvidenceGraph, int]:
    graph = EvidenceGraph(
        question=f"{event.get('symbol')} {event.get('event_time')} {event.get('title')}",
        scope="固定 Evidence 的 Deep Researcher prompt A/B smoke",
    )
    packet = {
        key: event.get(key)
        for key in ("market", "symbol", "event_time", "event_type_l2", "title", "event_text", "benchmark")
    }
    graph.add_evidence(
        source_kind="as_of_packet",
        source_ref=str(event.get("event_id") or ""),
        title="严格 as-of 事件原文",
        summary=json.dumps(packet, ensure_ascii=False),
        raw=packet,
    )
    extras = _trajectory_evidence(trajectory_dir / f"{event['event_id']}.json")
    for node in extras:
        graph.add_evidence(
            source_kind=str(node.get("source_kind") or "expert_finding"),
            source_ref=str(node.get("source_ref") or "")[:500],
            title=str(node.get("title") or "既有专家证据"),
            summary=str(node.get("body") or ""),
            raw=node.get("source_data") if isinstance(node.get("source_data"), dict) else {},
        )
    return graph, 1 + len(extras)


def _quality(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    claims = [node for node in nodes if node.get("kind") == "claim"]
    substantive = {
        edge.get("src") for edge in edges
        if edge.get("relation") in {"supports", "contradicts"}
    }
    atomic_pass = sum(not check_claim_title(str(node.get("title") or ""))["warnings"] for node in claims)
    markers = ("事实：", "比较：", "反方/限制：", "验证条件：")
    rationale_complete = sum(all(marker in str(node.get("body") or "") for marker in markers) for node in claims)
    stats = payload.get("stats") or {}
    audit = payload.get("audit") or {}
    return {
        **stats,
        "substantive_claims": sum(node.get("id") in substantive for node in claims),
        "substantive_claim_rate": round(sum(node.get("id") in substantive for node in claims) / len(claims), 4) if claims else 0.0,
        "atomic_title_pass": atomic_pass,
        "atomic_title_pass_rate": round(atomic_pass / len(claims), 4) if claims else 0.0,
        "rationale_complete": rationale_complete,
        "rationale_complete_rate": round(rationale_complete / len(claims), 4) if claims else 0.0,
        "audit_total_findings": int((audit.get("summary") or {}).get("total_findings") or 0),
        "sufficient": bool(payload.get("sufficient")),
    }


def _direction_context(payload: dict[str, Any]) -> str:
    """压缩图谱为固定裁决器所需的可读上下文，避免把完整 raw 重复发给 LLM。"""
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    node_by_id = {str(node.get("id") or ""): node for node in nodes}
    lines: list[str] = []
    for node in nodes:
        if node.get("kind") != "claim":
            continue
        cid = str(node.get("id") or "")
        lines.append(
            f"CLAIM [{node.get('status') or 'open'}] {node.get('title') or ''}\n"
            f"{str(node.get('body') or '')[:1200]}"
        )
        for edge in edges:
            if str(edge.get("src") or "") != cid or edge.get("relation") not in {"supports", "contradicts"}:
                continue
            evidence = node_by_id.get(str(edge.get("dst") or ""), {})
            lines.append(
                f"  - {edge.get('relation')}: {evidence.get('title') or ''} | "
                f"{str(evidence.get('body') or '')[:700]}"
            )
    for node in nodes:
        if node.get("kind") == "missing":
            lines.append(f"MISSING: {node.get('title') or ''} | {str(node.get('body') or '')[:500]}")
    return "\n".join(lines)[:14000]


async def _judge_direction(event: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """固定裁决器：两组共用同一 prompt，方向差异只能来自 Evidence Graph。"""
    packet = {
        key: event.get(key)
        for key in ("market", "symbol", "event_time", "event_type_l2", "title", "event_text", "benchmark")
    }
    prompt = f"""你是严格 as-of 的独立方向裁决器。只允许使用事件 packet 与下方 Evidence Graph；
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
confidence 只表示判断的可靠程度，不改变净分确定的方向。
只输出单个 JSON：{{"pred_direction":"up|down|neutral","confidence":0.0,"rationale":"中文理由"}}

EVENT_PACKET:
{json.dumps(packet, ensure_ascii=False)}

EVIDENCE_GRAPH:
{_direction_context(payload)}"""
    response = await get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": "你是固定、保守、可复现的金融事件方向裁决器。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=500,
    )
    text = response.choices[0].message.content or ""
    match = re.search(r"\{.*\}", text, flags=re.S)
    obj: dict[str, Any] = {}
    if match:
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            obj = {}
    direction = str(obj.get("pred_direction") or "").strip().lower()
    if direction not in {"up", "down", "neutral"}:
        found = re.search(r"\b(up|down|neutral)\b", text, flags=re.I)
        direction = found.group(1).lower() if found else "neutral"
    try:
        confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.5)))
    except (TypeError, ValueError):
        confidence = 0.5
    raw_direction = direction
    gate_applied = False
    return {
        "pred_direction": direction,
        "raw_direction": raw_direction,
        "confidence": round(confidence, 4),
        "confidence_gate_applied": gate_applied,
        "rationale": str(obj.get("rationale") or text)[:1000],
        "raw_response": text[:2000],
    }


def _is_transient_error(error: str) -> bool:
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in (
            "apiconnectionerror", "readtimeout", "connecterror", "timeout",
            "apierror", "request burst", "system protection", "rate limit", "429",
        )
    )


async def _run_one(
    event: dict[str, Any],
    variant: str,
    trajectory_dir: Path,
    out_dir: Path,
    semaphore: asyncio.Semaphore,
    max_rounds: int,
    label: dict[str, Any] | None,
    retries: int,
) -> dict[str, Any]:
    effective = resolve_deep_researcher_prompt_variant(variant)
    queued_at = time.monotonic()
    started = queued_at
    error = ""
    direction: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    state: dict[str, Any] = {"content": "", "tool_trace": [], "rounds": 0}
    n_seed = 0
    attempts = 0

    # 一个样本的构图、重试和方向裁决始终占用同一个并发槽；连接抖动时不会
    # 释放槽位后把后续 200 个任务瞬间冲向端点。
    async with semaphore:
        started = time.monotonic()
        for attempt in range(1, max(1, retries + 1) + 1):
            attempts = attempt
            graph, n_seed = _seed_graph(event, trajectory_dir)
            token = eg_attach(graph)
            state = {"content": "", "tool_trace": [], "rounds": 0}
            error = ""
            try:
                agent = get_agent("deep_researcher", effective)
                if agent is None:
                    raise RuntimeError("deep_researcher 未注册")
                graph_only_agent = {**agent, "skills": ["evidence_graph"]}
                messages = [
                    {"role": "system", "content": system_prompt("deep_researcher", effective)},
                    {
                        "role": "user",
                        "content": (
                            "这是固定 Evidence 的 prompt A/B smoke。当前 Evidence Graph 已预载事件原文和既有专家证据。"
                            "不得调用外部数据；只能使用 evidence_graph 完成 Claim、实质连边、状态、Missing、"
                            "sufficient/audit/export。请围绕事件后 T+3 benchmark-relative CAR 形成审慎、可证伪的研究判断。"
                        ),
                    },
                ]
                async for _ in run_agent(
                    "deep_researcher",
                    messages,
                    agent_def=graph_only_agent,
                    state=state,
                    artifact_store=noop_artifact_store,
                    max_rounds=max_rounds,
                    emit_thinking=False,
                ):
                    pass
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            finally:
                payload = graph.to_payload()
                eg_detach(token)

            if not error:
                break
            if attempt <= retries and _is_transient_error(error):
                delay = min(30.0, 3.0 * (2 ** (attempt - 1)))
                print(f"[retry graph {attempt}/{retries}] {effective} {event['event_id']} sleep={delay:.1f}s {error}", flush=True)
                await asyncio.sleep(delay)
                continue
            break

        if not error:
            for judge_attempt in range(1, max(1, retries + 1) + 1):
                try:
                    direction = await _judge_direction(event, payload)
                    break
                except Exception as exc:  # noqa: BLE001
                    error = f"direction_judge {type(exc).__name__}: {exc}"
                    if judge_attempt <= retries and _is_transient_error(error):
                        delay = min(30.0, 3.0 * (2 ** (judge_attempt - 1)))
                        print(
                            f"[retry judge {judge_attempt}/{retries}] {effective} {event['event_id']} "
                            f"sleep={delay:.1f}s {error}",
                            flush=True,
                        )
                        await asyncio.sleep(delay)
                        error = ""
                        continue
                    break

    result = {
        "event_id": event["event_id"],
        "market": event.get("market"),
        "event_type_l2": event.get("event_type_l2"),
        "variant": effective,
        "seed_evidence": n_seed,
        "queue_seconds": round(started - queued_at, 3),
        "wall_seconds": round(time.monotonic() - started, 3),
        "rounds": int(state.get("rounds") or 0),
        "tool_calls": len(state.get("tool_trace") or []),
        "attempts": attempts,
        "error": error,
        "content": state.get("content") or "",
        "quality": _quality(payload),
        "direction": direction,
        "oracle": {
            key: (label or {}).get(key)
            for key in ("label_t3", "label_avg_all", "label_consensus66", "car_t3", "car_avg_all")
        },
        "graph": payload,
    }
    target = out_dir / effective
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{event['event_id']}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[{effective}] {event['event_id']} error={bool(error)} "
        f"claims={result['quality'].get('n_claim', 0)} edges={result['quality'].get('n_edges', 0)} "
        f"audit={result['quality']['audit_total_findings']} pred={direction.get('pred_direction', '?')} "
        f"wall={result['wall_seconds']}s",
        flush=True,
    )
    return result


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for variant in sorted({row["variant"] for row in rows}):
        group = [row for row in rows if row["variant"] == variant]
        valid = [row for row in group if not row["error"]]
        keys = (
            "n_claim", "n_edges", "n_supports", "n_contradicts", "n_missing",
            "substantive_claim_rate", "atomic_title_pass_rate",
            "rationale_complete_rate", "audit_total_findings",
        )
        out[variant] = {
            "n": len(group),
            "success": len(valid),
            "avg_wall_seconds": round(sum(row["wall_seconds"] for row in group) / len(group), 3),
            **{
                f"avg_{key}": round(sum(float(row["quality"].get(key) or 0) for row in valid) / len(valid), 4)
                if valid else None
                for key in keys
            },
        }
        predictions = [row for row in valid if row.get("direction", {}).get("pred_direction")]
        pred_counts = {
            direction: sum(row["direction"]["pred_direction"] == direction for row in predictions)
            for direction in ("up", "down", "neutral")
        }
        out[variant]["direction_distribution"] = pred_counts
        out[variant]["neutral_rate"] = round(pred_counts["neutral"] / len(predictions), 4) if predictions else None
        out[variant]["avg_confidence"] = (
            round(sum(float(row["direction"].get("confidence") or 0) for row in predictions) / len(predictions), 4)
            if predictions else None
        )
        for horizon in ("t3", "avg_all", "consensus66"):
            scored = [row for row in predictions if row.get("oracle", {}).get(f"label_{horizon}")]
            non_neutral = [row for row in scored if row["oracle"][f"label_{horizon}"] in {"up", "down"}]
            # 与 backtesting strict 口径一致：oracle neutral 不计正确，但保留在 strict 分母。
            correct = sum(
                row["oracle"][f"label_{horizon}"] != "neutral"
                and row["direction"]["pred_direction"] == row["oracle"][f"label_{horizon}"]
                for row in scored
            )
            correct_non_neutral = sum(
                row["direction"]["pred_direction"] == row["oracle"][f"label_{horizon}"]
                for row in non_neutral
            )
            out[variant][f"acc_{horizon}_strict"] = round(correct / len(scored), 4) if scored else None
            out[variant][f"acc_{horizon}_non_neutral"] = (
                round(correct_non_neutral / len(non_neutral), 4) if non_neutral else None
            )
    return out


async def _rejudge_one(
    event: dict[str, Any], result_path: Path, semaphore: asyncio.Semaphore, retries: int,
) -> dict[str, Any]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("error"):
        return result
    if result.get("direction_judge_version") == "backtesting_scorecard_v1":
        print(f"[resume judge] {result['variant']} {result['event_id']}", flush=True)
        return result
    async with semaphore:
        for attempt in range(1, max(1, retries + 1) + 1):
            try:
                direction = await _judge_direction(event, result.get("graph") or {})
                result.setdefault("direction_initial", result.get("direction") or {})
                result["direction"] = direction
                result["direction_judge_version"] = "backtesting_scorecard_v1"
                result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    f"[judge] {result['variant']} {result['event_id']} "
                    f"pred={direction['pred_direction']} conf={direction['confidence']}",
                    flush=True,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                if attempt <= retries and _is_transient_error(error):
                    delay = min(30.0, 3.0 * (2 ** (attempt - 1)))
                    print(f"[retry judge {attempt}/{retries}] {result['variant']} {result['event_id']} {error}", flush=True)
                    await asyncio.sleep(delay)
                    continue
                result["judge_error"] = error
                result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                return result
    return result


async def _main(args: argparse.Namespace) -> int:
    events = _jsonl(Path(args.events))[: args.limit]
    labels = {row["event_id"]: row for row in _jsonl(Path(args.labels))} if args.labels else {}
    variants = [resolve_deep_researcher_prompt_variant(v) for v in args.variants.split(",") if v.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max(1, args.concurrency))
    if args.judge_only:
        event_by_id = {event["event_id"]: event for event in events}
        paths = [
            out_dir / variant / f"{event['event_id']}.json"
            for event in events for variant in variants
            if (out_dir / variant / f"{event['event_id']}.json").is_file()
        ]
        rows = await asyncio.gather(*[
            _rejudge_one(
                event_by_id[json.loads(path.read_text(encoding="utf-8"))["event_id"]],
                path, sem, args.retries,
            )
            for path in paths
        ])
        summary = {"events": len(events), "variants": variants, "judge_version": "backtesting_scorecard_v1", "aggregate": _aggregate(rows)}
        (out_dir / "summary_scorecard.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if all(not row.get("judge_error") for row in rows) else 2
    async def run_or_resume(event: dict[str, Any], variant: str) -> dict[str, Any]:
        effective = resolve_deep_researcher_prompt_variant(variant)
        checkpoint = out_dir / effective / f"{event['event_id']}.json"
        if args.resume and checkpoint.is_file():
            prior = json.loads(checkpoint.read_text(encoding="utf-8"))
            if not prior.get("error"):
                print(f"[resume] {effective} {event['event_id']}", flush=True)
                return prior
        return await _run_one(
            event, variant, Path(args.trajectory_dir), out_dir, sem, args.max_rounds,
            labels.get(event["event_id"]), args.retries,
        )

    tasks = [run_or_resume(event, variant) for event in events for variant in variants]
    rows = await asyncio.gather(*tasks)
    summary = {"events": len(events), "variants": variants, "aggregate": _aggregate(rows)}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(not row["error"] for row in rows) else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--trajectory-dir", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--variants", default="deep_researcher_v0,deep_researcher_claim_v2")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--judge-only", action="store_true")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

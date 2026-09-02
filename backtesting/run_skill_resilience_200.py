#!/usr/bin/env python3
"""Replay 200 historically failure-prone events against the current skill code.

The experiment is intentionally skill-only: it measures data-access changes
without adding LLM prompt/judge variance.  The old trajectory is the baseline;
the current implementation is called once per selected event for
stock_overview and market_research(price-only).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from collections import Counter
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parent
TARGET_SKILLS = ("stock_overview", "market_research")


def write_json_atomic(path: Path, payload: dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def load_candidates(trajectory_dir: Path) -> list[dict]:
    candidates: list[dict] = []
    for path in sorted(trajectory_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        trace = payload.get("team_final_state", {}).get("tool_trace", [])
        by_skill: dict[str, list[dict]] = {name: [] for name in TARGET_SKILLS}
        for item in trace:
            if not isinstance(item, dict) or item.get("type") != "tool":
                continue
            name = str(item.get("skill") or "")
            if name in by_skill:
                by_skill[name].append(item)
        failures = sum(not bool(item.get("ok")) for rows in by_skill.values() for item in rows)
        attempted = sum(len(rows) for rows in by_skill.values())
        if failures == 0:
            continue
        meta = payload.get("event_meta") or {}
        candidates.append({
            "event_id": str(payload.get("event_id") or meta.get("event_id") or path.stem),
            "market": str(meta.get("market") or "").upper(),
            "symbol": str(meta.get("symbol") or "").strip(),
            "event_time": str(meta.get("event_time") or ""),
            "event_type_l2": str(meta.get("event_type_l2") or ""),
            "trajectory_path": str(path),
            "baseline_failures": failures,
            "baseline_attempts": attempted,
            "baseline": {
                name: {
                    "calls": len(rows),
                    "ok": sum(bool(item.get("ok")) for item in rows),
                    "fail": sum(not bool(item.get("ok")) for item in rows),
                    "event_success": any(bool(item.get("ok")) for item in rows),
                }
                for name, rows in by_skill.items()
            },
        })
    return candidates


def select_balanced(candidates: list[dict], per_market: int) -> list[dict]:
    selected: list[dict] = []
    for market in ("CN", "US"):
        rows = [row for row in candidates if row["market"] == market and row["symbol"]]
        rows.sort(key=lambda row: (-row["baseline_failures"], -row["baseline_attempts"], row["event_id"]))
        selected.extend(rows[:per_market])
    selected.sort(key=lambda row: (row["market"], row["event_id"]))
    return selected


def compact_result(result: dict, elapsed: float) -> dict:
    data = result.get("data") if isinstance(result, dict) else None
    data = data if isinstance(data, dict) else {}
    sub_results = data.get("sub_results") if isinstance(data.get("sub_results"), list) else []
    price_child_ok = any(
        isinstance(item, dict) and item.get("skill") == "get_stock_daily" and item.get("ok")
        for item in sub_results
    )
    price_metrics = data.get("price_metrics") if isinstance(data.get("price_metrics"), dict) else {}
    artifacts = []
    if isinstance(result, dict):
        if isinstance(result.get("artifacts"), list):
            artifacts.extend(item for item in result["artifacts"] if isinstance(item, dict))
        if isinstance(result.get("artifact"), dict):
            artifacts.append(result["artifact"])
    data_points = data.get("data_points") if isinstance(data.get("data_points"), list) else []
    price_in_data = any(
        isinstance(point, list)
        and any(isinstance(item, dict) and "date" in item and "close" in item for item in point[:3])
        for point in data_points
    )
    price_artifact = any(item.get("kind") == "kline" for item in artifacts)
    return {
        "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "usable_price": bool(price_child_ok or price_metrics or price_in_data or price_artifact),
        "degraded": bool(result.get("degraded")) if isinstance(result, dict) else False,
        "error": str(result.get("error") or "")[:1000] if isinstance(result, dict) else "invalid result",
        "elapsed_seconds": round(elapsed, 3),
        "resolved_symbol": data.get("resolved_symbol") or data.get("symbol"),
        "market": data.get("market"),
        "security_kind": data.get("security_kind"),
        "price_metrics": price_metrics,
        "sub_results": sub_results,
    }


async def run_one(row: dict, semaphore: asyncio.Semaphore, out_dir: Path) -> dict:
    from app.llm import execute_skill

    result_path = out_dir / f"{row['event_id']}.json"
    if result_path.exists():
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    async with semaphore:
        fixed: dict[str, dict] = {}
        calls = {
            "stock_overview": {
                "symbol": row["symbol"],
                "market": row["market"],
            },
            "market_research": {
                "symbol": row["symbol"],
                "lookback_days": 60,
                "focus": ["price"],
            },
        }
        for name in TARGET_SKILLS:
            started = time.monotonic()
            result = await execute_skill(name, calls[name])
            fixed[name] = compact_result(result, time.monotonic() - started)
        output = {**row, "fixed": fixed}
        write_json_atomic(result_path, output)
        return output


async def run_isolated(
    row: dict, semaphore: asyncio.Semaphore, out_dir: Path, worker_timeout: float,
) -> dict:
    """Run one symbol in its own process so native provider crashes stay local."""
    result_path = out_dir / f"{row['event_id']}.json"
    if result_path.exists():
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    jobs_dir = out_dir.parent / "_jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    input_path = jobs_dir / f"{row['event_id']}.json"
    input_path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    async with semaphore:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker-input", str(input_path),
            "--worker-output", str(result_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + worker_timeout
        # A timed-out to_thread may keep Python's default executor alive after
        # the result is safely checkpointed.  End this dedicated worker once
        # its output exists; no unrelated work shares the process.
        while proc.returncode is None and loop.time() < deadline:
            if result_path.exists():
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                break
            await asyncio.sleep(0.25)
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if result_path.exists():
            try:
                return json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        reason = f"isolated worker failed (exit={proc.returncode})"
        failed = {
            **row,
            "fixed": {
                name: {
                    "ok": False, "usable_price": False, "degraded": False,
                    "error": reason, "elapsed_seconds": round(worker_timeout, 3),
                    "resolved_symbol": None, "market": row["market"],
                    "security_kind": None, "price_metrics": {}, "sub_results": [],
                }
                for name in TARGET_SKILLS
            },
        }
        write_json_atomic(result_path, failed)
        return failed


def pct(value: int, total: int) -> str:
    return f"{100 * value / total:.1f}%" if total else "—"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def write_report(rows: list[dict], report_path: Path) -> None:
    unique_symbols = len({(row["market"], row["symbol"]) for row in rows})
    lines = [
        f"# 高失败率事件技能修复实验（{len(rows)}条）",
        "",
        "> 从原1000条 trajectory 中按 stock_overview / market_research 失败调用数排序，并按市场等量抽样。",
        "> 修复后使用 packet 的明确 symbol 各调用一次；不调用 LLM，因此只反映数据访问与解析能力。",
        f"> {len(rows)} 个事件包含 {unique_symbols} 个唯一 market+symbol；同一时点、同一 symbol 的联网结果只抓取一次后映射回各事件。",
        "",
        "## 结果",
        "",
        "| skill | 修复前事件成功 | 修复后顶层成功 | 修复后价格可用 | degraded |",
        "|---|---:|---:|---:|---:|",
    ]
    for skill in TARGET_SKILLS:
        attempted = [row for row in rows if row["baseline"][skill]["calls"]]
        baseline_ok = sum(row["baseline"][skill]["event_success"] for row in attempted)
        fixed_ok = sum(row["fixed"][skill]["ok"] for row in rows)
        usable = sum(row["fixed"][skill]["usable_price"] for row in rows)
        degraded = sum(row["fixed"][skill]["degraded"] for row in rows)
        lines.append(
            f"| {skill} | {baseline_ok}/{len(attempted)} ({pct(baseline_ok, len(attempted))}) | "
            f"{fixed_ok}/{len(rows)} ({pct(fixed_ok, len(rows))}) | "
            f"{usable}/{len(rows)} ({pct(usable, len(rows))}) | {degraded}/{len(rows)} |"
        )
    lines += [
        "", "### 配对事件翻转", "",
        "| skill | 旧失败→新成功 | 旧成功→新失败 | 两者成功 | 两者失败 |",
        "|---|---:|---:|---:|---:|",
    ]
    for skill in TARGET_SKILLS:
        paired = [row for row in rows if row["baseline"][skill]["calls"]]
        recovered = sum(not row["baseline"][skill]["event_success"] and row["fixed"][skill]["ok"] for row in paired)
        regressed = sum(row["baseline"][skill]["event_success"] and not row["fixed"][skill]["ok"] for row in paired)
        both_ok = sum(row["baseline"][skill]["event_success"] and row["fixed"][skill]["ok"] for row in paired)
        both_fail = sum(not row["baseline"][skill]["event_success"] and not row["fixed"][skill]["ok"] for row in paired)
        lines.append(f"| {skill} | {recovered} | {regressed} | {both_ok} | {both_fail} |")
    lines += ["", "### 分市场", "", "| skill | market | 修复前顶层成功 | 修复后顶层成功 | 价格可用 |", "|---|---|---:|---:|---:|"]
    for skill in TARGET_SKILLS:
        for market in ("CN", "US"):
            subset = [row for row in rows if row["market"] == market]
            baseline_subset = [row for row in subset if row["baseline"][skill]["calls"]]
            baseline_ok = sum(row["baseline"][skill]["event_success"] for row in baseline_subset)
            ok_count = sum(row["fixed"][skill]["ok"] for row in subset)
            usable = sum(row["fixed"][skill]["usable_price"] for row in subset)
            lines.append(
                f"| {skill} | {market} | {baseline_ok}/{len(baseline_subset)} ({pct(baseline_ok, len(baseline_subset))}) | "
                f"{ok_count}/{len(subset)} ({pct(ok_count, len(subset))}) | "
                f"{usable}/{len(subset)} ({pct(usable, len(subset))}) |"
            )
    lines += ["", "### 修复后耗时（事件加权）", "", "| skill | median | p95 |", "|---|---:|---:|"]
    for skill in TARGET_SKILLS:
        elapsed = [float(row["fixed"][skill]["elapsed_seconds"]) for row in rows]
        lines.append(f"| {skill} | {percentile(elapsed, 0.5):.2f}s | {percentile(elapsed, 0.95):.2f}s |")
    lines += ["", "### 修复后失败摘要", ""]
    for skill in TARGET_SKILLS:
        failures = [row for row in rows if not row["fixed"][skill]["ok"]]
        reasons = Counter(
            "timeout" if "超时" in row["fixed"][skill]["error"] else
            "symbol" if "识别" in row["fixed"][skill]["error"] or "symbol" in row["fixed"][skill]["error"].lower() else
            "provider/empty"
            for row in failures
        )
        lines.append(f"- `{skill}`：失败 {len(failures)}；{dict(reasons)}")
    lines += [
        "",
        "## 口径限制",
        "",
        "- 这是历史失败压力集，不代表自然流量分布。",
        "- 修复前为 trajectory 中模型实际调用（可能多次重试）；修复后为每事件一次标准化调用。",
        "- 顶层成功与价格可用分别统计，避免辅助子接口成功掩盖核心行情失败。",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


async def async_main(args) -> None:
    trajectory_dir = args.trajectory_dir.resolve()
    out_dir = args.out_dir.resolve()
    results_dir = out_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    selected = select_balanced(load_candidates(trajectory_dir), args.per_market)
    if len(selected) != args.per_market * 2:
        raise SystemExit(f"高失败率事件不足：需要 {args.per_market * 2}，实际 {len(selected)}")

    with (out_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "event_id", "market", "symbol", "event_time", "event_type_l2",
            "baseline_failures", "baseline_attempts", "trajectory_path",
        ])
        writer.writeheader()
        for row in selected:
            writer.writerow({key: row.get(key) for key in writer.fieldnames})

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    representatives: dict[tuple[str, str], dict] = {}
    for row in selected:
        representatives.setdefault((row["market"], row["symbol"]), row)
    tasks = [
        asyncio.create_task(run_isolated(row, semaphore, results_dir, args.worker_timeout))
        for row in representatives.values()
    ]
    by_symbol: dict[tuple[str, str], dict] = {}
    for future in asyncio.as_completed(tasks):
        output = await future
        by_symbol[(output["market"], output["symbol"])] = output
        if len(by_symbol) % 10 == 0:
            print(f"unique-symbol progress {len(by_symbol)}/{len(tasks)}", flush=True)
    completed: list[dict] = []
    for row in selected:
        fixed = by_symbol[(row["market"], row["symbol"])]["fixed"]
        output = {**row, "fixed": fixed}
        completed.append(output)
        write_json_atomic(results_dir / f"{row['event_id']}.json", output)
    completed.sort(key=lambda row: (row["market"], row["event_id"]))
    write_report(completed, out_dir / "report.md")
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in completed:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(out_dir / "report.md")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-input", type=Path)
    parser.add_argument("--worker-output", type=Path)
    parser.add_argument(
        "--trajectory-dir", type=Path,
        default=ROOT / "_trajectory_ckpt_tf_cn_us_1000_v1",
    )
    parser.add_argument(
        "--out-dir", type=Path,
        default=ROOT / "skill_resilience_200_20260902",
    )
    parser.add_argument("--per-market", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--worker-timeout", type=float, default=75)
    args = parser.parse_args()
    if args.worker_input:
        if not args.worker_output:
            raise SystemExit("--worker-output is required with --worker-input")
        row = json.loads(args.worker_input.read_text(encoding="utf-8"))
        args.worker_output.parent.mkdir(parents=True, exist_ok=True)

        async def worker() -> None:
            result = await run_one(row, asyncio.Semaphore(1), args.worker_output.parent)
            if args.worker_output.name != f"{row['event_id']}.json":
                write_json_atomic(args.worker_output, result)

        asyncio.run(worker())
        return
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()

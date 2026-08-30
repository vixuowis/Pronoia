#!/usr/bin/env python3
"""Build a deterministic, stratified low-quality-event rerun set."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVENTS = ROOT / "events_cn_us_1000_v1.jsonl"
LABELS = ROOT / "labels_cn_us_1000_v1.jsonl"
QUALITY = ROOT / "low_quality_event_packets_20260829.csv"
TRAJECTORIES = ROOT / "_trajectory_ckpt_tf_cn_us_1000_v1"
OUT_EVENTS = ROOT / "events_low_quality_rerun_30_20260829.jsonl"
OUT_LABELS = ROOT / "labels_low_quality_rerun_30_20260829.jsonl"
OUT_MANIFEST = ROOT / "low_quality_rerun_30_manifest_20260829.csv"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def choose(rows: list[dict], used: set[str], n: int, predicate) -> list[dict]:
    candidates = [row for row in rows if row["event_id"] not in used and predicate(row)]
    candidates.sort(key=lambda row: (row.get("event_time", ""), row["event_id"]))
    selected = candidates[:n]
    used.update(row["event_id"] for row in selected)
    return selected


def main() -> None:
    events = {row["event_id"]: row for row in read_jsonl(EVENTS)}
    labels = {row["event_id"]: row for row in read_jsonl(LABELS)}
    with QUALITY.open(encoding="utf-8-sig", newline="") as handle:
        quality = {row["event_id"]: row for row in csv.DictReader(handle)}

    failures: dict[str, set[str]] = defaultdict(set)
    for path in sorted(TRAJECTORIES.glob("*.json")):
        event_id = path.stem
        raw = path.read_text(errors="replace")
        low = raw.lower()
        if "sz5" in low and "行情获取失败" in raw:
            failures[event_id].add("etf_prefix_failure")
        if "必须提供 symbol 或 keyword" in raw:
            failures[event_id].add("missing_symbol_failure")
        if "timeout" in low or "timed out" in low or "超时" in raw:
            failures[event_id].add("timeout_failure")

    rows: list[dict] = []
    for event_id, q in quality.items():
        if event_id not in events or event_id not in labels:
            continue
        row = dict(q)
        row["old_failures"] = ";".join(sorted(failures.get(event_id, set())))
        rows.append(row)

    used: set[str] = set()
    selected: list[tuple[str, dict]] = []
    strata = [
        ("etf_prefix_failure", 8, lambda r: "etf_prefix_failure" in r["old_failures"]),
        (
            "missing_symbol_non_etf",
            6,
            lambda r: "missing_symbol_failure" in r["old_failures"]
            and "etf_prefix_failure" not in r["old_failures"],
        ),
        (
            "macro_identity_or_template",
            6,
            lambda r: r["event_type_l2"] in {"通胀数据意外", "政策利率调整", "就业数据意外"}
            and ("模板" in r["quality_flags"] or "标题与正文" in r["quality_flags"]),
        ),
        (
            "earnings_missing_core",
            5,
            lambda r: "财报" in r["event_type_l2"] and "财报缺核心字段" in r["quality_flags"],
        ),
        (
            "other_low_quality_control",
            5,
            lambda r: r["event_type_l2"] not in {"通胀数据意外", "政策利率调整", "就业数据意外"}
            and "财报" not in r["event_type_l2"],
        ),
    ]
    for stratum, count, predicate in strata:
        picks = choose(rows, used, count, predicate)
        if len(picks) != count:
            raise RuntimeError(f"stratum {stratum}: wanted {count}, found {len(picks)}")
        selected.extend((stratum, row) for row in picks)

    selected_ids = [row["event_id"] for _, row in selected]
    OUT_EVENTS.write_text(
        "".join(json.dumps(events[event_id], ensure_ascii=False) + "\n" for event_id in selected_ids)
    )
    OUT_LABELS.write_text(
        "".join(json.dumps(labels[event_id], ensure_ascii=False) + "\n" for event_id in selected_ids)
    )
    fields = [
        "stratum", "event_id", "market", "symbol", "event_time", "event_type_l2",
        "severity", "title", "event_text", "quality_flags", "old_failures",
    ]
    with OUT_MANIFEST.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for stratum, row in selected:
            writer.writerow({"stratum": stratum, **{field: row.get(field, "") for field in fields[1:]}})

    print(f"selected={len(selected_ids)} unique={len(set(selected_ids))}")
    for stratum, count, _ in strata:
        print(f"{stratum}={sum(1 for value, _ in selected if value == stratum)}")
    print(OUT_EVENTS)
    print(OUT_LABELS)
    print(OUT_MANIFEST)


if __name__ == "__main__":
    main()

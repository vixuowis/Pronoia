#!/usr/bin/env python3
"""Verify the committed actor-scale bundle with the Python standard library."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CLASSES = ("up", "down", "neutral")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def brier(rows: list[dict[str, Any]], labels: dict[str, dict[str, Any]], arm: str) -> float:
    values = []
    for row in rows:
        oracle = labels[row["event_id"]]["label_t3"]
        probabilities = row[arm]["probabilities"]
        values.append(
            sum(
                (float(probabilities[item]) - (1.0 if item == oracle else 0.0)) ** 2
                for item in CLASSES
            )
        )
    return statistics.fmean(values)


def main() -> int:
    checksums = read_json(HERE / "checksums.json")
    for filename, expected in checksums["files"].items():
        actual = file_hash(HERE / filename)
        if actual != expected:
            raise AssertionError(f"checksum mismatch: {filename}")

    manifest = read_json(HERE / "manifest.json")
    manifest_hash = manifest["manifest_sha256"]
    unhashed_manifest = dict(manifest)
    unhashed_manifest.pop("manifest_sha256")
    if canonical_hash(unhashed_manifest) != manifest_hash:
        raise AssertionError("manifest canonical hash mismatch")

    event_path = (HERE / manifest["source"]["events_path"]).resolve()
    if file_hash(event_path) != manifest["source"]["events_sha256"]:
        raise AssertionError("source event dataset hash mismatch")

    report = read_json(HERE / "report.json")
    runs = read_jsonl(HERE / "runs.jsonl")
    primary_ids = {row["experiment_case_id"] for row in manifest["cases"]}
    all_ids = set(primary_ids)
    for group in manifest["actor_ablation"]["groups"]:
        all_ids.update(row["experiment_case_id"] for row in group["variants"])
    run_by_id = {row["experiment_case_id"]: row for row in runs}
    if len(runs) != len(run_by_id) or set(run_by_id) != all_ids:
        raise AssertionError("run IDs do not match the frozen 32-run design")
    if any(row["status"] not in {"completed", "partial"} for row in runs):
        raise AssertionError("bundle contains a non-completed run")

    primary = [run_by_id[case_id] for case_id in primary_ids]
    overall = report["engineering"]["primary_cases"]["overall"]
    if len(primary) != 24 or overall["completed_n"] != 24:
        raise AssertionError("primary run count is not 24/24")
    close(statistics.fmean(row["active_actor_ratio"] for row in primary),
          overall["mean_active_actor_ratio"], "active actor ratio")
    close(statistics.fmean(row["valid_decision_ratio"] for row in primary),
          overall["mean_valid_decision_ratio"], "valid decision ratio")
    close(statistics.median(row["wall_seconds"] for row in primary),
          overall["median_wall_seconds"], "median wall seconds")
    close(percentile([row["wall_seconds"] for row in primary], 0.9),
          overall["p90_wall_seconds"], "p90 wall seconds")

    primary_budgets = {
        budget: sum(row["actor_budget"] == budget for row in primary)
        for budget in (4, 6, 8)
    }
    if primary_budgets != {4: 8, 6: 8, 8: 8}:
        raise AssertionError(f"unbalanced primary actor budgets: {primary_budgets}")

    predictions = read_jsonl(HERE / "predictions.jsonl")
    label_rows = read_jsonl(HERE.parent / "labels_cn_us_1000_v1.jsonl")
    labels = {row["event_id"]: row for row in label_rows}
    t3 = report["prediction"]["horizons"]["t3"]
    close(brier(predictions, labels, "baseline"),
          t3["baseline"]["multiclass_brier"], "baseline T+3 Brier")
    close(brier(predictions, labels, "assisted"),
          t3["assisted"]["multiclass_brier"], "assisted T+3 Brier")

    print("verification: PASS")
    print(f"manifest: {manifest_hash}")
    print("simulations: 32/32; primary actor budgets: 4=8, 6=8, 8=8")
    print(
        "T+3 Brier: "
        f"{t3['baseline']['multiclass_brier']:.6f} -> "
        f"{t3['assisted']['multiclass_brier']:.6f} (qualification failed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

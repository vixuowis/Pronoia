#!/usr/bin/env python3
"""Verify and recompute the packaged decision-support evaluation."""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
QUALITY_KEYS = (
    "mechanism_coherence",
    "monitoring_actionability",
    "falsifiability",
    "evidence_discipline",
    "scenario_diversity",
)
FLAG_KEYS = (
    "multi_actor_causal_chain",
    "observable_trigger",
    "specific_invalidation",
    "decision_relevant",
    "evidence_grounded",
)
RANK = {"miss": 0, "partial": 1, "full": 2}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_close(actual: float, expected: float, name: str) -> None:
    if abs(actual - expected) > 1e-6:
        raise AssertionError(f"{name}: {actual} != {expected}")


def quality_result(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    if first["case_id"] != second["case_id"] or first["variant"] != second["variant"]:
        raise AssertionError("quality repeat metadata mismatch")
    left = first["set"]
    right = second["set"]
    right_branches = {item["id"]: item for item in right["branches"]}
    qualified = 0
    for branch in left["branches"]:
        other = right_branches[branch["id"]]
        qualified += all(branch[key] and other[key] for key in FLAG_KEYS)
    return {
        "total": sum(
            (left["scores"][key] + right["scores"][key]) / 2
            for key in QUALITY_KEYS
        ),
        "qualified": qualified,
    }


def outcome_result(first: dict[str, Any], second: dict[str, Any]) -> dict[str, int]:
    if first["case_id"] != second["case_id"] or first["variant"] != second["variant"]:
        raise AssertionError("outcome repeat metadata mismatch")
    left = {item["target_id"]: item for item in first["targets"]}
    right = {item["target_id"]: item for item in second["targets"]}
    if set(left) != set(right):
        raise AssertionError("outcome repeat targets mismatch")
    counts = {"full": 0, "partial": 0, "miss": 0}
    for target_id in left:
        a = left[target_id]["status"]
        b = right[target_id]["status"]
        if a == b == "full":
            status = "full"
        elif RANK[a] >= 1 and RANK[b] >= 1:
            status = "partial"
        else:
            status = "miss"
        counts[status] += 1
    return counts


def scan_privacy(value: Any, trail: str = "root") -> None:
    forbidden_keys = {
        "api_key",
        "data_sources",
        "source_url",
        "source_refs",
        "url",
        "symbol",
        "return_pct",
        "baseline_close",
        "end_close",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise AssertionError(f"forbidden key {trail}.{key}")
            scan_privacy(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            scan_privacy(item, f"{trail}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if value.startswith(("/Users/", "/home/")):
            raise AssertionError(f"absolute local path at {trail}")
        if "api_key=" in lowered or lowered.startswith("sk-"):
            raise AssertionError(f"credential-like value at {trail}")


def main() -> int:
    checksums = read(ROOT / "checksums.json")
    expected_files = checksums["files"]
    actual_files = sorted(
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.name not in {"checksums.json", ".DS_Store"}
        and "__pycache__" not in path.parts
    )
    if actual_files != sorted(expected_files):
        raise AssertionError("bundle file inventory differs from checksums")
    for relative, expected in expected_files.items():
        actual = file_hash(ROOT / relative)
        if actual != expected:
            raise AssertionError(f"checksum mismatch: {relative}")

    manifest = read(ROOT / "manifest.json")
    report = read(ROOT / manifest["reports"]["compiler_diagnostic"])
    cases = manifest["cases"]
    if len(cases) != manifest["case_count"] or len(cases) != report["case_count"]:
        raise AssertionError("case count mismatch")
    metrics: dict[str, dict[str, Any]] = {
        variant: {"quality": [], "qualified": 0, "coverage": [], "full": 0, "partial": 0}
        for variant in ("v5", "v6")
    }
    for case in cases:
        case_dir = ROOT / case["directory"]
        scan_privacy(read(case_dir / "spec.json"), case["case_id"] + ".spec")
        scan_privacy(
            read(case_dir / "observed-event-targets.json"),
            case["case_id"] + ".outcome",
        )
        for variant in ("v5", "v6"):
            scenario = read(case_dir / "compiler" / f"scenario-{variant}.json")
            scan_privacy(scenario, case["case_id"] + "." + variant)
            if len(scenario["branches"]) != 4:
                raise AssertionError("scenario budget is not four")
            covered = {
                actor
                for branch in scenario["branches"]
                for actor in branch["actor_ids"]
            }
            metrics[variant]["coverage"].append(
                len(covered) / case["decision_actor_count"]
            )
            quality = quality_result(
                read(case_dir / "compiler" / f"quality-{variant}-pass-1.json"),
                read(case_dir / "compiler" / f"quality-{variant}-pass-2.json"),
            )
            metrics[variant]["quality"].append(quality["total"])
            metrics[variant]["qualified"] += quality["qualified"]
            outcome = outcome_result(
                read(case_dir / "compiler" / f"outcome-{variant}-pass-1.json"),
                read(case_dir / "compiler" / f"outcome-{variant}-pass-2.json"),
            )
            metrics[variant]["full"] += outcome["full"]
            metrics[variant]["partial"] += outcome["partial"]

    for variant in ("v5", "v6"):
        expected = report["variants"][variant]
        target_count = expected["event_target_count"]
        branch_count = expected["branch_count"]
        assert_close(
            statistics.mean(metrics[variant]["coverage"]),
            expected["decision_actor_coverage"],
            variant + " actor coverage",
        )
        assert_close(
            statistics.mean(metrics[variant]["quality"]),
            expected["mean_quality_score_out_of_20"],
            variant + " quality",
        )
        if metrics[variant]["qualified"] != expected["qualified_branch_count"]:
            raise AssertionError(variant + " qualified branch count mismatch")
        assert_close(
            metrics[variant]["qualified"] / branch_count,
            expected["qualified_branch_rate"],
            variant + " qualified branch rate",
        )
        if metrics[variant]["full"] != expected["full_event_target_hit_count"]:
            raise AssertionError(variant + " full path count mismatch")
        assert_close(
            metrics[variant]["full"] / target_count,
            expected["full_event_target_recall_at_4"],
            variant + " full path recall",
        )
        assert_close(
            (metrics[variant]["full"] + metrics[variant]["partial"])
            / target_count,
            expected["inclusive_event_target_recall_at_4"],
            variant + " inclusive path recall",
        )

    print(
        "verified decision-support bundle: "
        f"{manifest['case_count']} cases, "
        f"v5 coverage={report['variants']['v5']['decision_actor_coverage']:.1%}, "
        f"v6 coverage={report['variants']['v6']['decision_actor_coverage']:.1%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

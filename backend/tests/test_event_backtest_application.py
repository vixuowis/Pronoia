from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.event_backtest.application import (
    collect_seed_events_file,
    curate_phase1_events_file,
    load_predictions,
    run_baseline_file,
    run_predictions_file,
    validate_events_file,
    write_event_template,
)
from app.event_backtest.models import EventRecord


class TestEventBacktestApplication(unittest.TestCase):
    def test_validate_events_file_passes_golden_fixture(self):
        root = Path(__file__).resolve().parent
        issues = validate_events_file(root / "golden" / "events_fixture.jsonl")
        self.assertEqual(issues, [])

    def test_run_baseline_file_writes_predictions(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "predictions.jsonl"
            count = run_baseline_file(
                events_path=root / "golden" / "events_fixture.jsonl",
                out_path=out,
                run_id="t0",
            )
            self.assertEqual(count, 2)
            rows = load_predictions(out)
            self.assertEqual([r.event_id for r in rows], ["e1", "e2"])
            self.assertEqual(rows[0].pred_direction, "up")
            self.assertEqual(rows[1].pred_direction, "down")

    def test_run_team_prompt_file_writes_predictions(self):
        root = Path(__file__).resolve().parent

        async def fake_complete_json(system, user, *, max_tokens=600):
            if "NVDA" in user:
                return {"pred_direction": "down", "confidence": 0.77, "rationale": "guidance cut"}
            return {"pred_direction": "up", "confidence": 0.66, "rationale": "policy easing"}

        with tempfile.TemporaryDirectory() as td, patch(
            "app.event_backtest.engine.complete_json",
            new=fake_complete_json,
        ):
            out = Path(td) / "predictions_team.jsonl"
            count = run_predictions_file(
                events_path=root / "golden" / "events_fixture.jsonl",
                out_path=out,
                run_id="t1",
                runner="team_prompt",
            )
            self.assertEqual(count, 2)
            rows = load_predictions(out)
            self.assertEqual(rows[0].pred_direction, "up")
            self.assertEqual(rows[1].pred_direction, "down")
            self.assertEqual(rows[0].model_version, "team-prompt-v0")

            count2 = run_predictions_file(
                events_path=root / "golden" / "events_fixture.jsonl",
                out_path=out,
                run_id="t1",
                runner="team_prompt",
                resume=True,
            )
            self.assertEqual(count2, 2)

    def test_write_event_template_emits_requested_count(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "events_template.jsonl"
            write_event_template(out, count=2)
            lines = out.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("event_id", lines[0])
            self.assertIn("event_type_l2", lines[0])

    def test_collect_seed_events_file_writes_rows(self):
        with tempfile.TemporaryDirectory() as td, patch(
            "app.event_backtest.application.collect_cn_announcement_seeds",
            return_value=[
                EventRecord(
                    event_id="e1",
                    market="CN",
                    symbol="600519",
                    event_time="2025-07-01",
                    event_type_l2="并购/分拆/再融资",
                    title="t1",
                    event_text="x",
                    source_url="u1",
                )
            ],
        ), patch(
            "app.event_backtest.application.collect_us_sec_seeds",
            return_value=[
                EventRecord(
                    event_id="e2",
                    market="US",
                    symbol="NVDA",
                    event_time="2025-07-02",
                    event_type_l2="财报超预期/不及预期",
                    title="t2",
                    event_text="y",
                    source_url="u2",
                )
            ],
        ):
            out = Path(td) / "seeds.jsonl"
            count = collect_seed_events_file(
                out_path=out,
                cn_dates=["20250701"],
                us_symbols=["NVDA"],
            )
            self.assertEqual(count, 2)
            lines = out.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)

    def test_curate_phase1_events_file_balances_types_with_symbol_cap(self):
        with tempfile.TemporaryDirectory() as td:
            seeds = Path(td) / "seeds.jsonl"
            out = Path(td) / "events_phase1.jsonl"
            rows = [
                EventRecord(
                    event_id="m1",
                    market="CN",
                    symbol="600001",
                    event_time="2025-07-03",
                    event_type_l2="并购/分拆/再融资",
                    title="m1",
                    event_text="x",
                    source_url="u1",
                ),
                EventRecord(
                    event_id="m2",
                    market="CN",
                    symbol="600001",
                    event_time="2025-07-02",
                    event_type_l2="并购/分拆/再融资",
                    title="m2",
                    event_text="x",
                    source_url="u2",
                ),
                EventRecord(
                    event_id="m3",
                    market="CN",
                    symbol="600002",
                    event_time="2025-07-01",
                    event_type_l2="并购/分拆/再融资",
                    title="m3",
                    event_text="x",
                    source_url="u3",
                ),
                EventRecord(
                    event_id="e1",
                    market="US",
                    symbol="NVDA",
                    event_time="2025-07-03",
                    event_type_l2="财报超预期/不及预期",
                    title="e1",
                    event_text="y",
                    source_url="u4",
                ),
                EventRecord(
                    event_id="e2",
                    market="US",
                    symbol="AAPL",
                    event_time="2025-07-02",
                    event_type_l2="财报超预期/不及预期",
                    title="e2",
                    event_text="y",
                    source_url="u5",
                ),
            ]
            seeds.write_text("".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

            summary = curate_phase1_events_file(
                seeds_path=seeds,
                out_path=out,
                per_type_target=2,
                max_per_symbol_per_type=1,
                type_order=["并购/分拆/再融资", "财报超预期/不及预期"],
                min_history_days=0,
            )
            lines = out.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(summary["selected"], 4)
            self.assertEqual(summary["type_shortfalls"]["并购/分拆/再融资"], 0)
            self.assertEqual(summary["type_shortfalls"]["财报超预期/不及预期"], 0)
            self.assertIn("600002", out.read_text(encoding="utf-8"))

    def test_curate_phase1_events_file_enforces_history_window(self):
        with tempfile.TemporaryDirectory() as td:
            seeds = Path(td) / "seeds.jsonl"
            out = Path(td) / "events_phase1.jsonl"
            rows = [
                EventRecord(
                    event_id="old1",
                    market="CN",
                    symbol="600001",
                    event_time="2025-06-01",
                    event_type_l2="并购/分拆/再融资",
                    title="old1",
                    event_text="x",
                    source_url="u1",
                ),
                EventRecord(
                    event_id="new1",
                    market="CN",
                    symbol="600002",
                    event_time="2099-12-31",
                    event_type_l2="并购/分拆/再融资",
                    title="new1",
                    event_text="x",
                    source_url="u2",
                ),
            ]
            seeds.write_text("".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            summary = curate_phase1_events_file(
                seeds_path=seeds,
                out_path=out,
                per_type_target=2,
                max_per_symbol_per_type=2,
                type_order=["并购/分拆/再融资"],
                start_date="2025-01-01",
                end_date="2026-01-01",
                min_history_days=0,
            )
            self.assertEqual(summary["selected"], 1)
            self.assertEqual(summary["date_range"]["min"], "2025-06-01")
            self.assertEqual(summary["date_range"]["max"], "2025-06-01")

    def test_curate_phase1_events_file_natural_respects_cn_ratio(self):
        with tempfile.TemporaryDirectory() as td:
            seeds = Path(td) / "seeds.jsonl"
            out = Path(td) / "events_phase1.jsonl"
            rows = []
            for i in range(10):
                rows.append(
                    EventRecord(
                        event_id=f"cn{i}",
                        market="CN",
                        symbol=f"6000{i:02d}",
                        event_time="2025-05-01",
                        event_type_l2="并购/分拆/再融资",
                        title=f"cn{i}",
                        event_text="x",
                        source_url=f"u_cn_{i}",
                    )
                )
            for i in range(10):
                rows.append(
                    EventRecord(
                        event_id=f"us{i}",
                        market="US",
                        symbol=f"US{i}",
                        event_time="2025-05-01",
                        event_type_l2="并购/分拆/再融资",
                        title=f"us{i}",
                        event_text="y",
                        source_url=f"u_us_{i}",
                    )
                )
            seeds.write_text("".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            summary = curate_phase1_events_file(
                seeds_path=seeds,
                out_path=out,
                mode="natural",
                total_target=10,
                cn_ratio=0.7,
                per_type_target=30,
                max_per_symbol_per_type=2,
                start_date="2025-01-01",
                end_date="2026-01-01",
                min_history_days=0,
            )
            self.assertEqual(summary["selected"], 10)
            self.assertEqual(summary["by_market"]["CN"], 7)
            self.assertEqual(summary["by_market"]["US"], 3)


if __name__ == "__main__":
    unittest.main()

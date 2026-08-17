from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.event_backtest.application import score_files


def _normalize(obj):
    if isinstance(obj, float):
        return round(obj, 8)
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items(), key=lambda x: x[0])}
    if isinstance(obj, list):
        return [_normalize(x) for x in obj]
    return obj


class TestEventBacktestMetricsGolden(unittest.TestCase):
    def test_metrics_match_golden(self):
        root = Path(__file__).resolve().parent
        golden = root / "golden"
        metrics = score_files(
            predictions_path=golden / "predictions_fixture.jsonl",
            labels_path=golden / "labels_fixture.jsonl",
            epsilon=0.005,
        ).to_dict()
        expected = json.loads((golden / "expected_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(_normalize(metrics), _normalize(expected))


if __name__ == "__main__":
    unittest.main()

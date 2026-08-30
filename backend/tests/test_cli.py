from __future__ import annotations

import unittest

from app.cli import build_parser, csv_items, normalize_api_base, parse_sse_lines
from app.event_backtest.cli import build_bt_parser


class TestCliHelpers(unittest.TestCase):
    def test_normalize_api_base_appends_api(self):
        self.assertEqual(normalize_api_base("http://127.0.0.1:8000"), "http://127.0.0.1:8000/api")
        self.assertEqual(normalize_api_base("http://127.0.0.1:8000/api"), "http://127.0.0.1:8000/api")

    def test_csv_items_filters_blanks(self):
        self.assertEqual(csv_items("router, predictor, ,deep_researcher"), ["router", "predictor", "deep_researcher"])
        self.assertEqual(csv_items(None), [])

    def test_parse_sse_lines_extracts_json_payloads(self):
        rows = list(
            parse_sse_lines(
                [
                    b"data: {\"type\":\"meta\",\"case_id\":\"abc\"}",
                    b"",
                    b"data: {\"type\":\"token\",\"delta\":\"hello\"}",
                ]
            )
        )
        self.assertEqual(rows[0]["type"], "meta")
        self.assertEqual(rows[0]["case_id"], "abc")
        self.assertEqual(rows[1]["delta"], "hello")

    def test_chat_parser_accepts_team_members(self):
        parser = build_parser()
        args = parser.parse_args(["chat", "hello", "--mode", "team", "--team-members", "event_scout,predictor"])
        self.assertEqual(args.command, "chat")
        self.assertEqual(args.mode, "team")
        self.assertEqual(args.team_members, "event_scout,predictor")

    def test_backtest_parser_accepts_deep_researcher_ab_variants(self):
        parser = build_bt_parser()
        for variant in ("deep_researcher_v0", "deep_researcher_claim_v2"):
            args = parser.parse_args([
                "run", "--events", "events.jsonl", "--out", "preds.jsonl",
                "--run-id", "smoke", "--runner", "team_full",
                "--system-prompt-variant", variant,
            ])
            self.assertEqual(args.system_prompt_variant, variant)


if __name__ == "__main__":
    unittest.main()

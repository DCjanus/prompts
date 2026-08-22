from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "chatgpt_usage.py"
SPEC = importlib.util.spec_from_file_location("chatgpt_usage", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
chatgpt_usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chatgpt_usage
SPEC.loader.exec_module(chatgpt_usage)


class ParseRateLimitsTests(unittest.TestCase):
    def test_parses_all_buckets_without_duplicating_top_level_bucket(self) -> None:
        result = {
            "rateLimits": {
                "limitId": "codex",
                "limitName": None,
                "planType": "pro",
                "primary": {
                    "usedPercent": 39,
                    "windowDurationMins": 10080,
                    "resetsAt": 2_000_000_000,
                },
                "secondary": None,
            },
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "limitName": None,
                    "planType": "pro",
                    "primary": {
                        "usedPercent": 39,
                        "windowDurationMins": 10080,
                        "resetsAt": 2_000_000_000,
                    },
                    "secondary": None,
                },
                "codex_spark": {
                    "limitId": "codex_spark",
                    "limitName": "Codex Spark",
                    "planType": "pro",
                    "primary": {
                        "usedPercent": 10,
                        "windowDurationMins": 300,
                        "resetsAt": 2_000_000_000,
                    },
                    "secondary": None,
                },
            },
        }

        buckets = chatgpt_usage.parse_rate_limits(result)

        self.assertEqual(
            [bucket.limit_id for bucket in buckets], ["codex", "codex_spark"]
        )
        self.assertEqual(buckets[0].plan_type, "pro")
        self.assertEqual(buckets[1].windows[0].duration_minutes, 300)

    def test_calculates_comparable_remaining_percentages(self) -> None:
        now = datetime(2030, 1, 1, tzinfo=UTC)
        window = chatgpt_usage.UsageWindow(
            used_percent=25,
            duration_minutes=300,
            resets_at=int(now.timestamp()) + 150 * 60,
        )

        progress = chatgpt_usage.calculate_progress(window, now)

        self.assertEqual(progress.quota_remaining_percent, 75)
        self.assertEqual(progress.time_remaining_percent, 50)
        self.assertEqual(progress.pace_delta, 25)


class RenderUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = io.StringIO()
        self.original_console = chatgpt_usage.console
        chatgpt_usage.console = Console(
            file=self.output, width=100, color_system=None, force_terminal=False
        )
        self.now = datetime(2030, 1, 1, tzinfo=UTC)
        self.buckets = [
            chatgpt_usage.LimitBucket(
                limit_id="codex_internal",
                name="Codex Spark",
                plan_type="pro",
                windows=(
                    chatgpt_usage.UsageWindow(
                        used_percent=25,
                        duration_minutes=300,
                        resets_at=int(self.now.timestamp()) + 150 * 60,
                    ),
                ),
            )
        ]

    def tearDown(self) -> None:
        chatgpt_usage.console = self.original_console

    def test_pace_threshold_depends_on_window_duration(self) -> None:
        slight_slow = chatgpt_usage._pace_text(9.9, 300)
        abnormal_slow = chatgpt_usage._pace_text(10, 300)
        slight_fast = chatgpt_usage._pace_text(-2.9, 10080)
        abnormal_fast = chatgpt_usage._pace_text(-3, 10080)

        self.assertEqual(
            (slight_slow.plain, slight_slow.style), ("略慢 +9.9pp", "cyan")
        )
        self.assertEqual(
            (abnormal_slow.plain, abnormal_slow.style), ("偏慢 +10.0pp", "green")
        )
        self.assertEqual(
            (slight_fast.plain, slight_fast.style), ("略快 -2.9pp", "cyan")
        )
        self.assertEqual(
            (abnormal_fast.plain, abnormal_fast.style), ("偏快 -3.0pp", "bright_red")
        )

    def test_default_output_keeps_compact_comparison_with_pace(self) -> None:
        chatgpt_usage.render_usage(self.buckets, self.now, verbose=False)

        output = self.output.getvalue()
        self.assertIn("Codex Spark · PRO", output)
        self.assertIn("5 小时", output)
        self.assertIn("额度", output)
        self.assertIn("时间", output)
        self.assertIn("偏慢 +25.0pp", output)
        self.assertNotIn("codex_internal", output)

    def test_verbose_output_restores_diagnostic_details(self) -> None:
        chatgpt_usage.render_usage(self.buckets, self.now, verbose=True)

        output = self.output.getvalue()
        self.assertIn("codex_internal", output)
        self.assertIn("偏慢 +25.0pp", output)
        self.assertEqual(output.count("偏慢 +25.0pp"), 1)
        self.assertIn("重置", output)


class AppServerTests(unittest.TestCase):
    def test_fetches_limits_through_authenticated_codex_app_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_codex = Path(directory) / "codex"
            fake_codex.write_text(
                """#!/bin/sh
while IFS= read -r line; do
    case "$line" in
        *'"id":1'*)
            printf '%s\\n' '{"id":1,"result":{"codexHome":"/tmp/codex"}}'
            ;;
        *'account/rateLimits/read'*)
            printf '%s\\n' '{"method":"unrelated/notification","params":{}}'
            printf '%s\\n' '{"id":2,"result":{"rateLimits":{"limitId":"codex"}}}'
            exit 0
            ;;
    esac
done
""",
                encoding="utf-8",
            )
            os.chmod(fake_codex, 0o755)

            result = chatgpt_usage.fetch_rate_limits(fake_codex, 12)

        self.assertEqual(result["rateLimits"]["limitId"], "codex")


if __name__ == "__main__":
    unittest.main()

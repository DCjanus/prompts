from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from rich.console import Console
from typer.testing import CliRunner

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

    def test_svg_groups_each_bucket_and_escapes_dynamic_text(self) -> None:
        buckets = [
            chatgpt_usage.LimitBucket(
                limit_id="codex_internal",
                name="Codex & <Fast>",
                plan_type="pro",
                windows=self.buckets[0].windows,
            )
        ]

        svg = chatgpt_usage.render_usage_svg(buckets, self.now, verbose=True)

        self.assertTrue(svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"'))
        self.assertIn('width="1440"', svg)
        self.assertIn("Codex &amp; &lt;Fast&gt;", svg)
        self.assertIn("5 小时", svg)
        self.assertIn("额度剩余", svg)
        self.assertIn("时间剩余", svg)
        self.assertIn(">75%</text>", svg)
        self.assertIn(">50%</text>", svg)
        self.assertIn("额度多 25.0pp · 偏慢", svg)
        self.assertIn("codex_internal", svg)
        self.assertNotIn("CODEX · LIVE LIMITS", svg)
        self.assertNotIn("Codex & <Fast>", svg)
        self.assertIn('data-role="quota-track"', svg)
        self.assertIn('data-role="time-track"', svg)
        self.assertNotIn('data-role="difference-band"', svg)
        self.assertNotIn('data-role="sync-guide"', svg)
        self.assertNotIn('data-role="tolerance-band"', svg)
        self.assertNotIn('data-role="quota-marker"', svg)
        self.assertNotIn('data-role="time-marker"', svg)
        self.assertNotIn("stroke-dasharray", svg)
        self.assertIn("额度充足，节奏安全", svg)

    def test_svg_is_rasterized_in_process(self) -> None:
        svg = chatgpt_usage.render_usage_svg(self.buckets, self.now, verbose=False)

        png = chatgpt_usage.svg_to_png(svg)

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(
            int.from_bytes(png[16:20]),
            chatgpt_usage.SVG_WIDTH * chatgpt_usage.IMAGE_SCALE,
        )

    def test_svg_places_three_windows_in_one_compact_model_row(self) -> None:
        buckets = [
            self.buckets[0],
            chatgpt_usage.LimitBucket(
                limit_id="codex_spark",
                name="Codex Spark",
                plan_type="pro",
                windows=self.buckets[0].windows * 2,
            ),
        ]

        svg = chatgpt_usage.render_usage_svg(buckets, self.now, verbose=False)
        height = int(svg.split('height="', 1)[1].split('"', 1)[0])

        self.assertLessEqual(height, 500)
        self.assertIn("Codex Spark", svg)

    @patch.object(chatgpt_usage, "render_png")
    @patch.object(
        chatgpt_usage,
        "svg_to_png",
        return_value=b"\x89PNG\r\n\x1a\nexample",
    )
    def test_image_output_delegates_to_kitty_library(
        self, svg_to_png_mock: unittest.mock.Mock, render_png_mock: unittest.mock.Mock
    ) -> None:
        chatgpt_usage.render_usage_image(
            self.buckets, self.now, columns=72, verbose=False
        )

        svg_to_png_mock.assert_called_once()
        render_png_mock.assert_called_once_with(b"\x89PNG\r\n\x1a\nexample", cols=72)


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


class CliTests(unittest.TestCase):
    @patch.object(
        chatgpt_usage.shutil,
        "get_terminal_size",
        return_value=os.terminal_size((200, 60)),
    )
    def test_default_image_width_reserves_one_column_to_prevent_wrapping(
        self, _terminal_size_mock: unittest.mock.Mock
    ) -> None:
        self.assertEqual(chatgpt_usage.default_image_columns(), 199)

    def test_image_environment_hint_recognizes_supported_terminals(self) -> None:
        self.assertTrue(
            chatgpt_usage.image_environment_hint({"TERM_PROGRAM": "ghostty"})
        )
        self.assertTrue(chatgpt_usage.image_environment_hint({"TERM": "xterm-kitty"}))
        self.assertFalse(
            chatgpt_usage.image_environment_hint({"TERM": "xterm-256color"})
        )
        self.assertFalse(chatgpt_usage.image_environment_hint({}))

    @patch.object(chatgpt_usage, "image_environment_hint", return_value=True)
    def test_image_support_requires_a_tty(self, _hint_mock: unittest.mock.Mock) -> None:
        stream = unittest.mock.Mock()
        stream.isatty.return_value = False

        self.assertFalse(chatgpt_usage.supports_image_output(stream))

        stream.isatty.return_value = True
        self.assertTrue(chatgpt_usage.supports_image_output(stream))

    @patch.object(chatgpt_usage, "render_usage_image")
    @patch.object(
        chatgpt_usage,
        "fetch_rate_limits",
        return_value={
            "rateLimits": {
                "limitId": "codex",
                "planType": "pro",
                "primary": {
                    "usedPercent": 25,
                    "windowDurationMins": 10080,
                    "resetsAt": 2_000_000_000,
                },
            }
        },
    )
    def test_image_mode_uses_requested_width_and_can_save_svg(
        self,
        _fetch_mock: unittest.mock.Mock,
        render_image_mock: unittest.mock.Mock,
    ) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as directory:
            svg_path = Path(directory) / "usage.svg"

            result = runner.invoke(
                chatgpt_usage.app,
                [
                    "--codex-bin",
                    "/tmp/codex",
                    "--image",
                    "--image-width",
                    "72",
                    "--save-svg",
                    str(svg_path),
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(svg_path.read_text().startswith("<svg"))
        self.assertEqual(render_image_mock.call_args.kwargs["columns"], 72)

    @patch.object(chatgpt_usage, "render_usage")
    @patch.object(chatgpt_usage, "render_usage_image")
    @patch.object(chatgpt_usage, "default_image_columns", return_value=80)
    @patch.object(chatgpt_usage, "supports_image_output", return_value=True)
    @patch.object(
        chatgpt_usage,
        "fetch_rate_limits",
        return_value={"rateLimits": {"limitId": "codex", "primary": None}},
    )
    def test_default_uses_image_when_terminal_supports_it(
        self,
        _fetch_mock: unittest.mock.Mock,
        _support_mock: unittest.mock.Mock,
        _columns_mock: unittest.mock.Mock,
        render_image_mock: unittest.mock.Mock,
        render_text_mock: unittest.mock.Mock,
    ) -> None:
        result = CliRunner().invoke(chatgpt_usage.app, ["--codex-bin", "/tmp/codex"])

        self.assertEqual(result.exit_code, 0, result.output)
        render_image_mock.assert_called_once()
        self.assertEqual(render_image_mock.call_args.kwargs["columns"], 80)
        render_text_mock.assert_not_called()

    @patch.object(chatgpt_usage, "render_usage")
    @patch.object(chatgpt_usage, "render_usage_image")
    @patch.object(chatgpt_usage, "supports_image_output", return_value=True)
    @patch.object(
        chatgpt_usage,
        "fetch_rate_limits",
        return_value={"rateLimits": {"limitId": "codex", "primary": None}},
    )
    def test_text_flag_overrides_image_detection(
        self,
        _fetch_mock: unittest.mock.Mock,
        _support_mock: unittest.mock.Mock,
        render_image_mock: unittest.mock.Mock,
        render_text_mock: unittest.mock.Mock,
    ) -> None:
        result = CliRunner().invoke(
            chatgpt_usage.app, ["--codex-bin", "/tmp/codex", "--text"]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        render_text_mock.assert_called_once()
        render_image_mock.assert_not_called()

    @patch.object(chatgpt_usage, "render_usage")
    @patch.object(
        chatgpt_usage,
        "render_usage_image",
        side_effect=chatgpt_usage.UsageError("protocol unavailable"),
    )
    @patch.object(chatgpt_usage, "supports_image_output", return_value=True)
    @patch.object(
        chatgpt_usage,
        "fetch_rate_limits",
        return_value={"rateLimits": {"limitId": "codex", "primary": None}},
    )
    def test_auto_image_failure_falls_back_to_text(
        self,
        _fetch_mock: unittest.mock.Mock,
        _support_mock: unittest.mock.Mock,
        _render_image_mock: unittest.mock.Mock,
        render_text_mock: unittest.mock.Mock,
    ) -> None:
        result = CliRunner().invoke(chatgpt_usage.app, ["--codex-bin", "/tmp/codex"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("已回退到文本", result.output)
        render_text_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

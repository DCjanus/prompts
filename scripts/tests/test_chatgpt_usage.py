from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from rich.console import Console
from typer.testing import CliRunner

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "chatgpt_usage.py"
SPEC = importlib.util.spec_from_file_location("chatgpt_usage", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
chatgpt_usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chatgpt_usage
SPEC.loader.exec_module(chatgpt_usage)


class ParseRateLimitsTests(unittest.TestCase):
    def test_parses_available_reset_credits_and_keeps_nearest_three_expirations(
        self,
    ) -> None:
        result = {
            "rateLimitResetCredits": {
                "availableCount": 4,
                "credits": [
                    {"status": "available", "expiresAt": 2_000_000_400},
                    {"status": "used", "expiresAt": 2_000_000_050},
                    {"status": "available", "expiresAt": 2_000_000_300},
                    {"status": "available", "expiresAt": 2_000_000_100},
                    {"status": "available", "expiresAt": 2_000_000_200},
                ],
            }
        }

        reset_credits = chatgpt_usage.parse_reset_credits(result)

        self.assertEqual(reset_credits.available_count, 4)
        self.assertEqual(
            reset_credits.next_expirations_at,
            (2_000_000_100, 2_000_000_200, 2_000_000_300),
        )

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
        self.assertIsNone(chatgpt_usage._catch_up_seconds(window, progress))

    def test_calculates_rest_time_until_usage_catches_up_with_time(self) -> None:
        now = datetime(2030, 1, 1, tzinfo=UTC)
        window = chatgpt_usage.UsageWindow(
            used_percent=75,
            duration_minutes=300,
            resets_at=int(now.timestamp()) + 150 * 60,
        )

        progress = chatgpt_usage.calculate_progress(window, now)

        self.assertEqual(progress.pace_delta, -25)
        self.assertEqual(chatgpt_usage._catch_up_seconds(window, progress), 75 * 60)


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
                name="Codex",
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
        self.assertIn("Codex · PRO", output)
        self.assertIn("5 小时", output)
        self.assertIn("额度", output)
        self.assertIn("时间", output)
        self.assertIn("偏慢 +25.0pp", output)
        self.assertNotIn("codex_internal", output)

    def test_outputs_reset_credit_count_and_next_expirations_everywhere(self) -> None:
        reset_credits = chatgpt_usage.ResetCredits(
            available_count=2,
            next_expirations_at=(
                int(datetime(2030, 1, 2, 12, tzinfo=UTC).timestamp()),
                int(datetime(2030, 1, 3, 18, 30, tzinfo=UTC).timestamp()),
            ),
        )

        chatgpt_usage.render_usage(
            self.buckets,
            self.now,
            reset_credits=reset_credits,
            verbose=False,
        )
        svg = chatgpt_usage.render_usage_svg(
            self.buckets,
            self.now,
            reset_credits=reset_credits,
            verbose=False,
        )
        report = chatgpt_usage._json_report(
            self.buckets,
            self.now,
            reset_credits=reset_credits,
        )

        output = self.output.getvalue()
        self.assertIn("Bank Reset", output)
        self.assertIn("● Bank Reset", output)
        self.assertIn("剩余 2 次", output)
        first_expiration = chatgpt_usage._reset_expiration_text(
            reset_credits.next_expirations_at[0]
        )
        second_expiration = chatgpt_usage._reset_expiration_text(
            reset_credits.next_expirations_at[1]
        )
        self.assertIn(first_expiration, output)
        self.assertIn(second_expiration, output)
        self.assertIn('data-role="reset-credits"', svg)
        self.assertNotIn('data-role="reset-credits" filter=', svg)
        reset_markup = svg.split('data-role="reset-credits"', 1)[1].split("</g>", 1)[0]
        self.assertIn("<circle", reset_markup)
        self.assertNotIn('text-anchor="end"', reset_markup)
        self.assertIn("剩余 2 次", svg)
        self.assertIn(first_expiration, svg)
        self.assertIn(second_expiration, svg)
        self.assertEqual(report["reset_credits"]["available_count"], 2)
        self.assertEqual(
            report["reset_credits"]["next_expirations_at"],
            [
                datetime.fromtimestamp(expires_at).astimezone().isoformat()
                for expires_at in reset_credits.next_expirations_at
            ],
        )

    def test_verbose_output_restores_diagnostic_details(self) -> None:
        chatgpt_usage.render_usage(self.buckets, self.now, verbose=True)

        output = self.output.getvalue()
        self.assertIn("codex_internal", output)
        self.assertIn("偏慢 +25.0pp", output)
        self.assertEqual(output.count("偏慢 +25.0pp"), 1)
        self.assertIn("重置", output)

    def test_fast_usage_shows_rest_time_until_pace_is_even(self) -> None:
        fast_bucket = chatgpt_usage.LimitBucket(
            limit_id="codex_internal",
            name="Codex",
            plan_type="pro",
            windows=(
                chatgpt_usage.UsageWindow(
                    used_percent=75,
                    duration_minutes=300,
                    resets_at=int(self.now.timestamp()) + 150 * 60,
                ),
            ),
        )

        chatgpt_usage.render_usage([fast_bucket], self.now, verbose=False)
        svg = chatgpt_usage.render_usage_svg([fast_bucket], self.now, verbose=False)

        self.assertIn("休息约1小时15分钟后持平", self.output.getvalue())
        self.assertIn("休息约1小时15分钟后持平", svg)

    def test_default_output_hides_spark_bucket_but_verbose_keeps_it(self) -> None:
        spark = chatgpt_usage.LimitBucket(
            limit_id="codex_spark",
            name="Codex Spark",
            plan_type="pro",
            windows=self.buckets[0].windows,
        )

        chatgpt_usage.render_usage([*self.buckets, spark], self.now, verbose=False)

        self.assertEqual(self.output.getvalue().count("Codex Spark · PRO"), 0)
        self.output.seek(0)
        self.output.truncate(0)

        chatgpt_usage.render_usage([*self.buckets, spark], self.now, verbose=True)

        self.assertEqual(self.output.getvalue().count("Codex Spark · PRO"), 1)

    def test_text_output_includes_daily_tokens_and_cache_hit_rate(self) -> None:
        history = chatgpt_usage.UsageHistory(
            days=(
                chatgpt_usage.DailyTokenUsage(
                    day=date(2029, 12, 31),
                    input_tokens=1_000,
                    cached_input_tokens=750,
                    cache_write_input_tokens=0,
                    output_tokens=200,
                    reasoning_output_tokens=50,
                    total_tokens=1_200,
                ),
                chatgpt_usage.DailyTokenUsage(
                    day=date(2030, 1, 1),
                    input_tokens=2_000,
                    cached_input_tokens=1_000,
                    cache_write_input_tokens=0,
                    output_tokens=300,
                    reasoning_output_tokens=75,
                    total_tokens=2_300,
                ),
                chatgpt_usage.DailyTokenUsage(
                    day=date(2030, 1, 2),
                    input_tokens=0,
                    cached_input_tokens=0,
                    cache_write_input_tokens=0,
                    output_tokens=0,
                    reasoning_output_tokens=0,
                    total_tokens=0,
                ),
            ),
            scan=chatgpt_usage.ScanStats(
                total_files=10,
                cache_hits=9,
                full_scans=0,
                incremental_scans=1,
            ),
        )

        chatgpt_usage.render_usage(
            self.buckets, self.now, history=history, verbose=False
        )

        output = self.output.getvalue()
        self.assertIn("最近 3 天 Token", output)
        self.assertLess(output.index("最近 3 天 Token"), output.index("Codex · PRO"))
        self.assertIn("12-31", output)
        self.assertIn("75.0%", output)
        self.assertIn("01-01", output)
        self.assertIn("50.0%", output)
        self.assertIn("预估金额", output)
        self.assertNotIn("索引命中", output)

        self.output.seek(0)
        self.output.truncate(0)
        chatgpt_usage.render_usage(
            self.buckets, self.now, history=history, verbose=True
        )
        self.assertIn("索引命中 9/10", self.output.getvalue())

        report = chatgpt_usage._json_report(self.buckets, self.now, history)
        self.assertEqual(report["local_usage"]["total_tokens"], 3_500)
        self.assertEqual(report["local_usage"]["days"][0]["day"], "2029-12-31")
        self.assertEqual(report["local_usage"]["scan"]["cache_hits"], 9)

    def test_estimates_cached_input_and_long_context_at_model_rates(self) -> None:
        short = chatgpt_usage.estimate_api_cost(
            "gpt-5.6-sol",
            input_tokens=100,
            cached_input_tokens=60,
            cache_write_input_tokens=10,
            output_tokens=20,
        )
        long = chatgpt_usage.estimate_api_cost(
            "gpt-5.6",
            input_tokens=300_000,
            cached_input_tokens=200_000,
            cache_write_input_tokens=50_000,
            output_tokens=10_000,
        )

        fast = chatgpt_usage.estimate_api_cost(
            "gpt-5.6-sol",
            input_tokens=100,
            cached_input_tokens=60,
            cache_write_input_tokens=10,
            output_tokens=20,
            service_tier="priority",
        )

        self.assertAlmostEqual(short, 0.000_594)
        self.assertAlmostEqual(long, 1.36)
        self.assertAlmostEqual(fast, short * 2)
        self.assertEqual(
            chatgpt_usage.estimate_api_cost(
                "gpt-free-cache",
                input_tokens=100,
                cached_input_tokens=100,
                cache_write_input_tokens=0,
                output_tokens=0,
                prices={"gpt-free-cache": chatgpt_usage.ModelPricing(1, 0, 2)},
            ),
            0,
        )
        self.assertIsNone(
            chatgpt_usage.estimate_api_cost(
                "codex-auto-review",
                input_tokens=100,
                cached_input_tokens=0,
                cache_write_input_tokens=0,
                output_tokens=20,
            )
        )

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

        svg = chatgpt_usage.render_usage_svg(buckets, self.now, verbose=True)
        height = int(svg.split('height="', 1)[1].split('"', 1)[0])

        self.assertLessEqual(height, 500)
        self.assertIn("Codex Spark", svg)

    def test_svg_includes_compact_daily_usage_and_hides_spark(self) -> None:
        spark = chatgpt_usage.LimitBucket(
            limit_id="codex_spark",
            name="Codex Spark",
            plan_type="pro",
            windows=self.buckets[0].windows,
        )
        history = chatgpt_usage.UsageHistory(
            days=(
                chatgpt_usage.DailyTokenUsage(
                    day=date(2030, 1, 1),
                    input_tokens=2_000,
                    cached_input_tokens=1_500,
                    cache_write_input_tokens=0,
                    output_tokens=300,
                    reasoning_output_tokens=75,
                    total_tokens=2_300,
                ),
                chatgpt_usage.DailyTokenUsage(
                    day=date(2030, 1, 2),
                    input_tokens=0,
                    cached_input_tokens=0,
                    cache_write_input_tokens=0,
                    output_tokens=0,
                    reasoning_output_tokens=0,
                    total_tokens=0,
                ),
            ),
            scan=chatgpt_usage.ScanStats(1, 1, 0, 0),
        )

        svg = chatgpt_usage.render_usage_svg(
            [*self.buckets, spark], self.now, history=history, verbose=False
        )

        self.assertIn("最近 2 天 Token", svg)
        self.assertIn("75.0%", svg)
        self.assertNotIn("codex_spark", svg)
        self.assertNotIn('height="0.0"', svg)
        self.assertEqual(svg.count('data-role="day-card"'), 2)
        self.assertIn('data-role="quota-summary"', svg)
        self.assertLess(
            svg.index('data-role="daily-usage"'),
            svg.index('data-role="quota-summary"'),
        )
        self.assertNotIn('data-role="quota-track"', svg)
        height = int(svg.split('height="', 1)[1].split('"', 1)[0])
        self.assertLessEqual(height, 560)

    def test_svg_wraps_thirty_days_into_three_rows(self) -> None:
        history = chatgpt_usage.UsageHistory(
            days=tuple(
                chatgpt_usage.DailyTokenUsage(
                    day=date(2030, 1, 30) - timedelta(days=29 - offset),
                    input_tokens=1_000 + offset,
                    cached_input_tokens=750,
                    cache_write_input_tokens=0,
                    output_tokens=100,
                    reasoning_output_tokens=0,
                    total_tokens=1_100 + offset,
                )
                for offset in range(30)
            ),
            scan=chatgpt_usage.ScanStats(1, 1, 0, 0),
        )

        svg = chatgpt_usage.render_usage_svg(
            self.buckets, self.now, history=history, verbose=False
        )

        self.assertEqual(svg.count('data-role="day-card"'), 30)
        self.assertIn('data-grid-columns="10"', svg)
        self.assertIn("最近 30 天 Token", svg)
        height = int(svg.split('height="', 1)[1].split('"', 1)[0])
        self.assertGreater(height, 560)
        self.assertLessEqual(height, 800)

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


class PricingCatalogTests(unittest.TestCase):
    @staticmethod
    def _models_dev_payload() -> bytes:
        return json.dumps(
            {
                "anthropic": {
                    "id": "anthropic",
                    "models": {
                        "claude-example": {
                            "id": "claude-example",
                            "cost": {"input": 1, "output": 5},
                        }
                    },
                },
                "openai": {
                    "id": "openai",
                    "models": {
                        "gpt-5.6-sol": {
                            "id": "gpt-5.6-sol",
                            "cost": {
                                "input": 3,
                                "output": 12,
                                "cache_read": 0.3,
                                "cache_write": 3.75,
                                "context_over_200k": {
                                    "input": 6,
                                    "output": 18,
                                    "cache_read": 0.6,
                                    "cache_write": 7.5,
                                },
                            },
                        },
                        "gpt-future": {
                            "id": "gpt-future",
                            "cost": {"input": 4, "output": 16},
                        },
                    },
                },
            }
        ).encode()

    def test_fetches_models_dev_catalog_and_reuses_fresh_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "pricing.json"
            now = datetime(2030, 1, 1, tzinfo=UTC)
            fetcher = Mock(return_value=self._models_dev_payload())

            fetched = chatgpt_usage.load_pricing_catalog(
                cache_path, now=now, timeout=2, fetcher=fetcher
            )
            cached = chatgpt_usage.load_pricing_catalog(
                cache_path,
                now=now + timedelta(hours=23),
                timeout=2,
                fetcher=Mock(side_effect=AssertionError("不应刷新新鲜缓存")),
            )

            self.assertEqual(fetched.metadata.source, "models.dev")
            self.assertFalse(fetched.metadata.stale)
            self.assertEqual(cached.metadata.source, "models.dev_cache")
            self.assertEqual(fetched.prices["gpt-future"].input_per_million, 4)
            self.assertEqual(
                fetched.prices["gpt-5.6-sol"].long_context_threshold, 272_000
            )
            self.assertEqual(fetched.prices["gpt-5.6-sol"].long_input_per_million, 6)
            fetcher.assert_called_once()

    def test_refresh_failure_uses_stale_cache_before_built_in_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "pricing.json"
            now = datetime(2030, 1, 1, tzinfo=UTC)
            chatgpt_usage.load_pricing_catalog(
                cache_path,
                now=now,
                timeout=2,
                fetcher=Mock(return_value=self._models_dev_payload()),
            )

            stale = chatgpt_usage.load_pricing_catalog(
                cache_path,
                now=now + timedelta(hours=25),
                timeout=2,
                fetcher=Mock(side_effect=OSError("offline")),
            )

            self.assertEqual(stale.metadata.source, "models.dev_cache")
            self.assertTrue(stale.metadata.stale)
            self.assertIn("offline", stale.metadata.error or "")
            self.assertIn("gpt-future", stale.prices)
            self.assertIn("gpt-5.5", stale.prices)

    def test_rejects_partial_catalog_and_uses_built_in_prices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            partial = json.dumps(
                {
                    "openai": {
                        "models": {
                            "gpt-future": {
                                "id": "gpt-future",
                                "cost": {"input": 4, "output": 16},
                            }
                        }
                    }
                }
            ).encode()

            catalog = chatgpt_usage.load_pricing_catalog(
                Path(directory) / "pricing.json",
                now=datetime(2030, 1, 1, tzinfo=UTC),
                timeout=2,
                fetcher=Mock(return_value=partial),
            )

            self.assertEqual(catalog.metadata.source, "built_in")
            self.assertIn("不完整", catalog.metadata.error or "")
            self.assertNotIn("gpt-future", catalog.prices)


class LocalUsageHistoryTests(unittest.TestCase):
    @staticmethod
    def _turn_context_line(timestamp: str, model: str) -> str:
        return json.dumps(
            {
                "timestamp": timestamp,
                "type": "turn_context",
                "payload": {"model": model},
            }
        )

    @staticmethod
    def _thread_settings_line(timestamp: str, model: str, service_tier: str) -> str:
        return json.dumps(
            {
                "timestamp": timestamp,
                "type": "event_msg",
                "payload": {
                    "type": "thread_settings_applied",
                    "thread_settings": {
                        "model": model,
                        "service_tier": service_tier,
                    },
                },
            }
        )

    def _token_count_line(
        self,
        timestamp: str,
        *,
        ordinal: int,
        total: tuple[int, int, int, int],
        last: tuple[int, int, int, int],
    ) -> str:
        def usage(values: tuple[int, int, int, int]) -> dict[str, int]:
            input_tokens, cached_tokens, output_tokens, total_tokens = values
            return {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "cache_write_input_tokens": 0,
                "output_tokens": output_tokens,
                "reasoning_output_tokens": 0,
                "total_tokens": total_tokens,
            }

        return json.dumps(
            {
                "timestamp": timestamp,
                "ordinal": ordinal,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": usage(total),
                        "last_token_usage": usage(last),
                    },
                },
            }
        )

    def test_keeps_completed_rollouts_when_a_later_scan_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            active = codex_home / "sessions" / "2030" / "01" / "08"
            active.mkdir(parents=True)
            thread_ids = [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
            ]
            for ordinal, thread_id in enumerate(thread_ids, start=1):
                rollout = (
                    active / f"rollout-2030-01-08T10-00-0{ordinal}-{thread_id}.jsonl"
                )
                rollout.write_text(
                    self._token_count_line(
                        "2030-01-08T10:00:00.000Z",
                        ordinal=ordinal,
                        total=(100, 50, 10, 110),
                        last=(100, 50, 10, 110),
                    )
                    + "\n",
                    encoding="utf-8",
                )
                scan_now = datetime(2030, 1, 8, 12, tzinfo=UTC)
                os.utime(rollout, (scan_now.timestamp(), scan_now.timestamp()))

            original_parser = chatgpt_usage._parse_rollout_usage
            first_completed = threading.Event()

            def fail_second_rollout(path: Path, **kwargs):
                if thread_ids[1] in path.name:
                    self.assertTrue(first_completed.wait(timeout=5))
                    raise OSError("simulated scan failure")
                result = original_parser(path, **kwargs)
                first_completed.set()
                return result

            cache_path = root / "cache" / "usage.duckdb"
            with (
                patch.object(
                    chatgpt_usage,
                    "_parse_rollout_usage",
                    side_effect=fail_second_rollout,
                ),
                self.assertRaises(chatgpt_usage.UsageError),
            ):
                chatgpt_usage.collect_usage_history(
                    codex_home,
                    cache_path,
                    now=scan_now,
                )

            connection = chatgpt_usage.duckdb.connect(str(cache_path))
            try:
                indexed_threads = connection.execute(
                    "SELECT thread_id, parsed_bytes FROM rollout_files ORDER BY thread_id"
                ).fetchall()
                event_threads = connection.execute(
                    "SELECT DISTINCT thread_id FROM token_usage_events ORDER BY thread_id"
                ).fetchall()
            finally:
                connection.close()
            self.assertGreater(indexed_threads[0][1], 0)
            self.assertEqual(indexed_threads[0][0], thread_ids[0])
            self.assertEqual(indexed_threads[1], (thread_ids[1], 0))
            self.assertEqual(event_threads, [(thread_ids[0],)])

            recovered = chatgpt_usage.collect_usage_history(
                codex_home,
                cache_path,
                now=scan_now,
            )

            self.assertEqual(recovered.days[-1].total_tokens, 220)
            self.assertEqual(recovered.scan, chatgpt_usage.ScanStats(2, 1, 1, 0))

    def test_incrementally_indexes_active_and_archived_rollouts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            active = codex_home / "sessions" / "2030" / "01" / "08"
            archived = codex_home / "archived_sessions"
            active.mkdir(parents=True)
            archived.mkdir(parents=True)
            thread_id = "00000000-0000-0000-0000-000000000123"
            rollout = active / f"rollout-2030-01-07T10-00-00-{thread_id}.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        self._turn_context_line("2029-12-31T11:59:00.000Z", "gpt-5.5"),
                        self._token_count_line(
                            "2029-12-31T12:00:00.000Z",
                            ordinal=0,
                            total=(50_000, 40_000, 5_000, 55_000),
                            last=(50_000, 40_000, 5_000, 55_000),
                        ),
                        self._token_count_line(
                            "2030-01-07T10:00:00.000Z",
                            ordinal=1,
                            total=(100, 60, 10, 110),
                            last=(100, 60, 10, 110),
                        ),
                        self._turn_context_line(
                            "2030-01-08T09:59:00.000Z", "gpt-5.6-sol"
                        ),
                        self._token_count_line(
                            "2030-01-08T10:00:00.000Z",
                            ordinal=2,
                            total=(250, 160, 30, 280),
                            last=(150, 100, 20, 170),
                        ),
                        self._token_count_line(
                            "2030-01-08T10:30:00.000Z",
                            ordinal=3,
                            total=(250, 160, 30, 280),
                            last=(999, 999, 0, 999),
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cache_path = root / "cache" / "usage.duckdb"
            now = datetime(2030, 1, 8, 12, tzinfo=UTC)
            os.utime(rollout, (now.timestamp(), now.timestamp()))

            first = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, days=7
            )

            by_day = {row.day: row for row in first.days}
            self.assertEqual(by_day[date(2030, 1, 7)].total_tokens, 110)
            self.assertEqual(by_day[date(2030, 1, 8)].total_tokens, 170)
            self.assertEqual(
                by_day[date(2030, 1, 8)].cache_hit_percent, 100 / 150 * 100
            )
            self.assertEqual(
                [usage.model for usage in by_day[date(2030, 1, 8)].models],
                ["gpt-5.6-sol"],
            )
            self.assertGreater(by_day[date(2030, 1, 8)].estimated_cost_usd, 0)
            self.assertEqual(first.scan, chatgpt_usage.ScanStats(1, 0, 1, 0))

            second = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, days=7
            )
            self.assertEqual(second.scan, chatgpt_usage.ScanStats(1, 1, 0, 0))

            archived_rollout = archived / rollout.name
            rollout.rename(archived_rollout)
            moved = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, days=7
            )
            self.assertEqual(moved.scan, chatgpt_usage.ScanStats(1, 1, 0, 0))

            with archived_rollout.open("a", encoding="utf-8") as file:
                file.write(
                    self._token_count_line(
                        "2030-01-08T11:00:00.000Z",
                        ordinal=4,
                        total=(350, 210, 40, 390),
                        last=(100, 50, 10, 110),
                    )
                    + "\n"
                )
            os.utime(archived_rollout, (now.timestamp(), now.timestamp()))

            appended = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, days=7
            )
            by_day = {row.day: row for row in appended.days}
            self.assertEqual(by_day[date(2030, 1, 8)].total_tokens, 280)
            self.assertEqual(
                [usage.model for usage in by_day[date(2030, 1, 8)].models],
                ["gpt-5.6-sol"],
            )
            self.assertEqual(appended.scan, chatgpt_usage.ScanStats(1, 0, 0, 1))

            expanded = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, days=30
            )
            by_day = {row.day: row for row in expanded.days}
            self.assertEqual(expanded.scan, chatgpt_usage.ScanStats(1, 0, 1, 0))
            self.assertEqual(by_day[date(2029, 12, 31)].total_tokens, 55_000)

            narrowed = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, days=7
            )
            by_day = {row.day: row for row in narrowed.days}
            self.assertEqual(len(narrowed.days), 7)
            self.assertNotIn(date(2029, 12, 31), by_day)
            self.assertEqual(by_day[date(2030, 1, 8)].total_tokens, 280)
            self.assertEqual(narrowed.scan, chatgpt_usage.ScanStats(1, 1, 0, 0))

            report = chatgpt_usage._json_report([], now, narrowed)
            latest = report["local_usage"]["days"][-1]
            self.assertEqual(latest["models"][0]["model"], "gpt-5.6-sol")
            self.assertGreater(latest["estimated_cost_usd"], 0)
            self.assertEqual(
                report["local_usage"]["pricing_basis"],
                "current_standard_api_equivalent",
            )
            self.assertEqual(report["local_usage"]["pricing"]["source"], "built_in")
            self.assertEqual(report["local_usage"]["pricing"]["fallback"], "built_in")

    def test_rebuilds_an_older_usage_cache_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_path = root / "cache" / "usage.duckdb"
            cache_path.parent.mkdir(parents=True)
            connection = chatgpt_usage.duckdb.connect(str(cache_path))
            connection.execute(
                """
                CREATE TABLE usage_cache_metadata (
                    key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL
                );
                INSERT INTO usage_cache_metadata VALUES
                    ('schema_version', '3'), ('coverage_days', '7'),
                    ('timezone', 'UTC');
                CREATE TABLE rollout_files (thread_id VARCHAR PRIMARY KEY);
                CREATE TABLE token_usage_daily (
                    thread_id VARCHAR, usage_date DATE
                );
                """
            )
            connection.close()

            history = chatgpt_usage.collect_usage_history(
                root / "codex", cache_path, now=datetime(2030, 1, 8, tzinfo=UTC)
            )

            self.assertEqual(history.total_tokens, 0)
            connection = chatgpt_usage.duckdb.connect(str(cache_path))
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info('token_usage_events')"
                ).fetchall()
            }
            version = connection.execute(
                "SELECT value FROM usage_cache_metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            connection.close()
            self.assertIn("model", columns)
            self.assertIn("service_tier", columns)
            self.assertIn("event_key", columns)
            self.assertNotIn("estimated_cost_usd", columns)
            self.assertEqual(version, str(chatgpt_usage.USAGE_CACHE_SCHEMA_VERSION))

    def test_reprices_cached_usage_without_rescanning_rollouts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            active = codex_home / "sessions" / "2030" / "01" / "08"
            active.mkdir(parents=True)
            thread_id = "00000000-0000-0000-0000-000000000456"
            rollout = active / f"rollout-2030-01-08T10-00-00-{thread_id}.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        self._turn_context_line(
                            "2030-01-08T09:59:00.000Z", "gpt-future"
                        ),
                        self._token_count_line(
                            "2030-01-08T10:00:00.000Z",
                            ordinal=1,
                            total=(1_000_000, 0, 1_000_000, 2_000_000),
                            last=(1_000_000, 0, 1_000_000, 2_000_000),
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            now = datetime(2030, 1, 8, 12, tzinfo=UTC)
            os.utime(rollout, (now.timestamp(), now.timestamp()))
            cache_path = root / "cache" / "usage.duckdb"

            low = chatgpt_usage.PricingCatalog(
                prices={"gpt-future": chatgpt_usage.ModelPricing(1, None, 2)},
                metadata=chatgpt_usage.PricingMetadata(
                    source="test", fetched_at=now, stale=False
                ),
            )
            high = chatgpt_usage.PricingCatalog(
                prices={"gpt-future": chatgpt_usage.ModelPricing(3, None, 4)},
                metadata=chatgpt_usage.PricingMetadata(
                    source="test", fetched_at=now, stale=False
                ),
            )

            first = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, pricing_catalog=low
            )
            repriced = chatgpt_usage.collect_usage_history(
                codex_home, cache_path, now=now, pricing_catalog=high
            )

            self.assertEqual(first.estimated_cost_usd, 3)
            self.assertEqual(repriced.estimated_cost_usd, 7)
            self.assertEqual(repriced.scan, chatgpt_usage.ScanStats(1, 1, 0, 0))

    def test_prices_fast_and_long_context_per_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            active = codex_home / "sessions" / "2030" / "01" / "08"
            active.mkdir(parents=True)
            thread_id = "00000000-0000-0000-0000-000000000789"
            rollout = active / f"rollout-2030-01-08T10-00-00-{thread_id}.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        self._thread_settings_line(
                            "2030-01-08T09:59:00.000Z",
                            "gpt-5.6-sol",
                            "priority",
                        ),
                        self._token_count_line(
                            "2030-01-08T10:00:00.000Z",
                            ordinal=1,
                            total=(200_000, 0, 0, 200_000),
                            last=(200_000, 0, 0, 200_000),
                        ),
                        self._token_count_line(
                            "2030-01-08T10:05:00.000Z",
                            ordinal=2,
                            total=(400_000, 0, 0, 400_000),
                            last=(200_000, 0, 0, 200_000),
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            now = datetime(2030, 1, 8, 12, tzinfo=UTC)
            os.utime(rollout, (now.timestamp(), now.timestamp()))
            pricing = chatgpt_usage.PricingCatalog(
                prices={
                    "gpt-5.6-sol": chatgpt_usage.ModelPricing(
                        1,
                        0.1,
                        2,
                        long_context_threshold=272_000,
                        long_input_per_million=10,
                        long_cached_input_per_million=1,
                        long_output_per_million=20,
                    )
                },
                metadata=chatgpt_usage.PricingMetadata(
                    source="test", fetched_at=now, stale=False
                ),
            )

            history = chatgpt_usage.collect_usage_history(
                codex_home,
                root / "cache" / "usage.duckdb",
                now=now,
                pricing_catalog=pricing,
            )

            model = history.days[-1].models[0]
            self.assertAlmostEqual(model.estimated_cost_usd or 0, 0.8)
            self.assertEqual(model.fast_tokens, 400_000)
            self.assertEqual(model.non_fast_tokens, 0)


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
    def setUp(self) -> None:
        self.history_patcher = patch.object(
            chatgpt_usage, "collect_usage_history", return_value=None
        )
        self.collect_history_mock = self.history_patcher.start()
        self.pricing_patcher = patch.object(
            chatgpt_usage,
            "load_pricing_catalog",
            return_value=chatgpt_usage.PricingCatalog(
                prices=dict(chatgpt_usage.MODEL_PRICING),
                metadata=chatgpt_usage.PricingMetadata(
                    source="built_in",
                    fetched_at=datetime(2030, 1, 1, tzinfo=UTC),
                    stale=False,
                ),
            ),
        )
        self.pricing_patcher.start()

    def tearDown(self) -> None:
        self.pricing_patcher.stop()
        self.history_patcher.stop()

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

    @patch.object(
        chatgpt_usage,
        "fetch_rate_limits",
        return_value={"rateLimits": {"limitId": "codex", "primary": None}},
    )
    def test_history_days_is_forwarded_to_local_usage_scan(
        self, _fetch_mock: unittest.mock.Mock
    ) -> None:
        result = CliRunner().invoke(
            chatgpt_usage.app,
            ["--codex-bin", "/tmp/codex", "--text", "--history-days", "30"],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.collect_history_mock.call_args.kwargs["days"], 30)

    def test_history_days_rejects_values_outside_supported_range(self) -> None:
        result = CliRunner().invoke(
            chatgpt_usage.app,
            ["--codex-bin", "/tmp/codex", "--history-days", "366"],
        )

        self.assertEqual(result.exit_code, 2, result.output)

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

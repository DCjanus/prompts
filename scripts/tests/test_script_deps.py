from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "script_deps.py"
SPEC = importlib.util.spec_from_file_location("script_deps", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
script_deps = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = script_deps
SPEC.loader.exec_module(script_deps)


class FetchLatestVersionTests(unittest.TestCase):
    def test_retries_a_transient_lookup_failure(self) -> None:
        response = io.BytesIO(json.dumps({"info": {"version": "1.2.3"}}).encode())

        with patch.object(
            script_deps,
            "urlopen",
            side_effect=[URLError("temporary"), response],
        ) as urlopen_mock:
            version, error = script_deps.fetch_latest_version(
                "example", timeout=1, retry_delay=0
            )

        self.assertEqual((version, error), ("1.2.3", None))
        self.assertEqual(urlopen_mock.call_count, 2)

    def test_reports_failure_after_retry_budget_is_exhausted(self) -> None:
        with patch.object(
            script_deps,
            "urlopen",
            side_effect=URLError("still offline"),
        ) as urlopen_mock:
            version, error = script_deps.fetch_latest_version(
                "example", timeout=1, attempts=3, retry_delay=0
            )

        self.assertIsNone(version)
        self.assertIn("still offline", error or "")
        self.assertEqual(urlopen_mock.call_count, 3)


class UpgradeActionTests(unittest.TestCase):
    def test_dry_run_displays_dependency_extras(self) -> None:
        output = io.StringIO()
        action = script_deps.UpgradeAction(
            Path("script.py"), "gql", "gql[httpx2]>=4.4.0b0"
        )

        with patch.object(
            script_deps,
            "console",
            script_deps.Console(file=output, width=120, color_system=None),
        ):
            script_deps.run_upgrade_actions([action], dry_run=True)

        self.assertIn("gql[httpx2]>=4.4.0b0", output.getvalue())

    def test_prerelease_pin_is_reported_and_converted_without_downgrade(self) -> None:
        report = script_deps.PackageReport(
            name="gql",
            latest="4.0.0",
            occurrences=[
                script_deps.DependencyOccurrence(
                    Path("script.py"),
                    "gql[httpx2]==4.4.0b0",
                    script_deps.Requirement("gql[httpx2]==4.4.0b0"),
                )
            ],
        )

        self.assertEqual(script_deps.package_status(report), "exact pin")
        self.assertEqual(
            script_deps.report_to_payload([report], [])["attention_count"], 1
        )
        self.assertEqual(
            script_deps.collect_upgrade_actions(Path("."), [report]),
            (
                [
                    script_deps.UpgradeAction(
                        Path("script.py"), "gql", "gql[httpx2]>=4.4.0b0"
                    )
                ],
                [],
            ),
        )

    def test_prerelease_lower_bound_upgrades_when_final_is_published(self) -> None:
        report = script_deps.PackageReport(
            name="gql",
            latest="4.0.0",
            occurrences=[
                script_deps.DependencyOccurrence(
                    Path("script.py"),
                    "gql[httpx2]>=4.4.0b0",
                    script_deps.Requirement("gql[httpx2]>=4.4.0b0"),
                )
            ],
        )

        self.assertEqual(script_deps.package_status(report), "ok")
        self.assertEqual(
            script_deps.collect_upgrade_actions(Path("."), [report]), ([], [])
        )

        report.latest = "4.4.0"
        self.assertEqual(script_deps.package_status(report), "minimum behind latest")
        self.assertEqual(
            script_deps.collect_upgrade_actions(Path("."), [report]),
            (
                [
                    script_deps.UpgradeAction(
                        Path("script.py"), "gql", "gql[httpx2]>=4.4.0"
                    )
                ],
                [],
            ),
        )

    def test_upgrade_only_changes_outdated_lower_bounds(self) -> None:
        report = script_deps.PackageReport(
            name="example",
            latest="1.2.0",
            occurrences=[
                script_deps.DependencyOccurrence(
                    Path("old.py"),
                    "example>=1.1.0",
                    script_deps.Requirement("example>=1.1.0"),
                ),
                script_deps.DependencyOccurrence(
                    Path("current.py"),
                    "example>=1.2.0",
                    script_deps.Requirement("example>=1.2.0"),
                ),
            ],
        )

        self.assertEqual(
            script_deps.report_to_payload([report], [])["attention_count"], 1
        )
        actions, skipped = script_deps.collect_upgrade_actions(Path("."), [report])
        self.assertEqual(
            actions,
            [script_deps.UpgradeAction(Path("old.py"), "example", "example>=1.2.0")],
        )
        self.assertEqual(skipped, [])

    def test_older_exact_pin_is_replaced_with_current_lower_bound(self) -> None:
        report = script_deps.PackageReport(
            name="example",
            latest="1.2.0",
            occurrences=[
                script_deps.DependencyOccurrence(
                    Path("script.py"),
                    "example==1.1.0",
                    script_deps.Requirement("example==1.1.0"),
                )
            ],
        )

        self.assertEqual(script_deps.package_status(report), "exact pin")
        actions, skipped = script_deps.collect_upgrade_actions(Path("."), [report])
        self.assertEqual(
            actions,
            [script_deps.UpgradeAction(Path("script.py"), "example", "example>=1.2.0")],
        )
        self.assertEqual(skipped, [])

    def test_wildcard_pin_needs_manual_change(self) -> None:
        report = script_deps.PackageReport(
            name="example",
            latest="1.2.0",
            occurrences=[
                script_deps.DependencyOccurrence(
                    Path("script.py"),
                    "example==1.*",
                    script_deps.Requirement("example==1.*"),
                )
            ],
        )

        self.assertEqual(script_deps.package_status(report), "exact pin")
        actions, skipped = script_deps.collect_upgrade_actions(Path("."), [report])
        self.assertEqual(actions, [])
        self.assertEqual(len(skipped), 1)

    def test_arbitrary_equality_needs_manual_change(self) -> None:
        report = script_deps.PackageReport(
            name="example",
            latest="1.2.0",
            occurrences=[
                script_deps.DependencyOccurrence(
                    Path("script.py"),
                    "example===1.2.0",
                    script_deps.Requirement("example===1.2.0"),
                )
            ],
        )

        self.assertEqual(script_deps.package_status(report), "exact pin")
        actions, skipped = script_deps.collect_upgrade_actions(Path("."), [report])
        self.assertEqual(actions, [])
        self.assertEqual(len(skipped), 1)

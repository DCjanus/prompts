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

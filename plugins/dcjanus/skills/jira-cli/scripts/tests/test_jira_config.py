from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from jira_config import (  # noqa: E402
    JiraCliSettings,
    load_settings,
    masked_settings,
    save_settings,
)


class JiraConfigTest(unittest.TestCase):
    def test_save_is_toml_atomic_private_and_round_trips(self):
        settings = JiraCliSettings(
            server="https://jira.example",
            token="top-secret-token",
            default_project="SATOS",
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "config.toml"
            save_settings(settings, target)
            mode = stat.S_IMODE(target.stat().st_mode)
            loaded = load_settings(target)
            contents = target.read_text(encoding="utf-8")

        self.assertEqual(mode, 0o600)
        self.assertEqual(loaded, settings)
        self.assertIn('default_project = "SATOS"', contents)

    def test_save_refuses_overwrite_without_explicit_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            save_settings(JiraCliSettings(token="first"), target)
            with self.assertRaises(FileExistsError):
                save_settings(JiraCliSettings(token="second"), target)
            self.assertEqual(load_settings(target).token, "first")

    def test_masked_settings_never_returns_full_token(self):
        masked = masked_settings(JiraCliSettings(token="abcdefghijklmnop"))
        self.assertEqual(masked["token"], "abcd...mnop")
        self.assertNotIn("abcdefghijklmnop", str(masked))

    def test_http_server_requires_explicit_dangerous_opt_in(self):
        with self.assertRaisesRegex(ValueError, "dangerously_allow_http"):
            JiraCliSettings(server="http://jira.example")
        settings = JiraCliSettings(
            server="http://jira.example", dangerously_allow_http=True
        )
        self.assertTrue(settings.dangerously_allow_http)

    def test_server_url_rejects_missing_host_credentials_query_and_fragment(self):
        for server in (
            "https://",
            "https://user:password@jira.example",
            "https://jira.example/path?x=1",
            "https://jira.example/path#fragment",
        ):
            with self.subTest(server=server), self.assertRaises(ValueError):
                JiraCliSettings(server=server)
        self.assertEqual(
            JiraCliSettings(server="https://jira.example/jira").server,
            "https://jira.example/jira",
        )


if __name__ == "__main__":
    unittest.main()

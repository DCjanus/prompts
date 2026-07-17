from __future__ import annotations

import json
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
    import_smc_settings,
    load_settings,
    masked_settings,
    save_settings,
)


class JiraConfigTest(unittest.TestCase):
    def test_import_smc_maps_existing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "jira_config.json"
            source.write_text(
                json.dumps(
                    {
                        "server": "https://jira.example",
                        "api_token": "top-secret-token",
                        "auth_type": "bearer",
                        "login": "jun@example.com",
                        "insecure": True,
                        "project": {"key": "SATOS"},
                        "board": "42",
                        "epic": {
                            "name": "customfield_10003",
                            "link": "customfield_10001",
                        },
                        "timezone": "Asia/Singapore",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "dangerously_disable_tls_verification"
            ):
                import_smc_settings(source)
            settings = import_smc_settings(
                source, dangerously_disable_tls_verification=True
            )

        self.assertEqual(settings.default_project, "SATOS")
        self.assertEqual(settings.epic_name_field, "customfield_10003")
        self.assertEqual(settings.epic_link_field, "customfield_10001")
        self.assertTrue(settings.dangerously_disable_tls_verification)

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


if __name__ == "__main__":
    unittest.main()

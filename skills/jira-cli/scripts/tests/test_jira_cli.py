from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rich.text import Text
from typer.testing import CliRunner


def load_cli_module():
    path = Path(__file__).resolve().parents[1] / "jira_cli.py"
    spec = importlib.util.spec_from_file_location("jira_cli_for_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load jira_cli.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class JiraCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_cli_module()
        cls.runner = CliRunner()

    def test_import_smc_creates_private_toml_and_masks_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "smc.json"
            target = root / "config.toml"
            source.write_text(
                json.dumps(
                    {
                        "server": "https://jira.example",
                        "api_token": "top-secret-token",
                        "auth_type": "bearer",
                        "project": {"key": "SATOS"},
                    }
                ),
                encoding="utf-8",
            )
            result = self.runner.invoke(
                self.cli.app,
                [
                    "--config",
                    str(target),
                    "--json",
                    "config",
                    "import-smc",
                    "--source",
                    str(source),
                ],
            )
            contents = target.read_text(encoding="utf-8")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("top-secret-token", result.output)
        self.assertIn("top-secret-token", contents)

    def test_config_set_does_not_persist_environment_token_override(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            original = os.environ.get("JIRA_API_TOKEN")
            os.environ["JIRA_API_TOKEN"] = "temporary-environment-token"
            try:
                result = self.runner.invoke(
                    self.cli.app,
                    [
                        "--config",
                        str(target),
                        "config",
                        "set",
                        "--default-project",
                        "SATOS",
                    ],
                )
            finally:
                if original is None:
                    os.environ.pop("JIRA_API_TOKEN", None)
                else:
                    os.environ["JIRA_API_TOKEN"] = original
            contents = target.read_text(encoding="utf-8")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("temporary-environment-token", contents)

    def test_undocumented_environment_aliases_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            target.write_text(
                'server = "https://jira.example"\ntoken = "persisted-secret-token"\n',
                encoding="utf-8",
            )
            old_values = {
                name: os.environ.get(name) for name in ("JIRA_BASE_URL", "JIRA_TOKEN")
            }
            os.environ["JIRA_BASE_URL"] = "https://evil.example"
            os.environ["JIRA_TOKEN"] = "unexpected-token"
            try:
                result = self.runner.invoke(
                    self.cli.app,
                    ["--config", str(target), "--json", "config", "show"],
                )
            finally:
                for name, value in old_values.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value

        payload = json.loads(result.output)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(payload["server"], "https://jira.example")
        self.assertNotIn("unexpected-token", result.output)

    def test_token_is_read_interactively_instead_of_from_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            help_result = self.runner.invoke(self.cli.app, ["config", "set", "--help"])
            result = self.runner.invoke(
                self.cli.app,
                ["--config", str(target), "config", "set", "--prompt-token"],
                input="top-secret-token\ntop-secret-token\n",
            )
            contents = target.read_text(encoding="utf-8")

        self.assertEqual(help_result.exit_code, 0, help_result.output)
        self.assertNotIn("--token ", Text.from_ansi(help_result.output).plain)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("top-secret-token", result.output)
        self.assertIn("top-secret-token", contents)

    def test_cancelled_token_prompt_has_no_traceback(self):
        script = Path(self.cli.__file__)
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--config",
                "/dev/null",
                "config",
                "set",
                "--prompt-token",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Aborted", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_json_mode_serializes_usage_and_network_errors(self):
        script = Path(self.cli.__file__)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                'server = "https://127.0.0.1:1"\n'
                'token = "secret"\n'
                "timeout_seconds = 0.1\n",
                encoding="utf-8",
            )
            cases = (
                ["--config", str(config), "--json", "issue", "delete", "SATOS-1"],
                ["--config", str(config), "--json", "server-info"],
                [
                    "--config",
                    "/dev/null/jira.toml",
                    "--json",
                    "config",
                    "set",
                    "--default-project",
                    "SATOS",
                ],
                [
                    "--config",
                    str(config),
                    "--json",
                    "config",
                    "set",
                    "--prompt-token",
                ],
            )
            for args in cases:
                with self.subTest(args=args):
                    result = subprocess.run(
                        [sys.executable, str(script), *args],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env={**os.environ, "NO_PROXY": "127.0.0.1"},
                        check=False,
                    )
                    payload = json.loads(result.stderr)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("error", payload)
                    self.assertNotIn("Traceback", result.stderr)

    def test_validation_errors_do_not_expose_token(self):
        script = Path(self.cli.__file__)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                'server = "http://jira.example"\ntoken = "sentinel-secret-token"\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--config",
                    str(config),
                    "--json",
                    "config",
                    "show",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        payload = json.loads(result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", payload)
        self.assertNotIn("sentinel-secret-token", result.stderr)

    def test_tls_disable_requires_dangerously_named_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            source = Path(directory) / "smc.json"
            source.write_text(
                json.dumps(
                    {
                        "server": "https://jira.example",
                        "api_token": "secret",
                        "insecure": True,
                    }
                ),
                encoding="utf-8",
            )
            old_verify = os.environ.get("JIRA_VERIFY_SSL")
            os.environ["JIRA_VERIFY_SSL"] = "false"
            try:
                show = self.runner.invoke(
                    self.cli.app,
                    ["--config", str(target), "--json", "config", "show"],
                )
            finally:
                if old_verify is None:
                    os.environ.pop("JIRA_VERIFY_SSL", None)
                else:
                    os.environ["JIRA_VERIFY_SSL"] = old_verify
            rejected = self.runner.invoke(
                self.cli.app,
                [
                    "--config",
                    str(target),
                    "config",
                    "import-smc",
                    "--source",
                    str(source),
                ],
            )
            allowed = self.runner.invoke(
                self.cli.app,
                [
                    "--config",
                    str(target),
                    "config",
                    "import-smc",
                    "--source",
                    str(source),
                    "--dangerously-disable-tls-verification",
                ],
            )

        self.assertEqual(show.exit_code, 0, show.output)
        self.assertFalse(
            json.loads(show.output)["dangerously_disable_tls_verification"]
        )
        self.assertNotEqual(rejected.exit_code, 0)
        self.assertIn(
            "dangerously-disable-tls-verification",
            Text.from_ansi(rejected.output).plain,
        )
        self.assertEqual(allowed.exit_code, 0, allowed.output)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            target.write_text(
                'server = "https://jira.example"\n'
                "dangerously_disable_tls_verification = true\n",
                encoding="utf-8",
            )
            old_disable = os.environ.get("JIRA_DANGEROUSLY_DISABLE_TLS_VERIFICATION")
            os.environ["JIRA_DANGEROUSLY_DISABLE_TLS_VERIFICATION"] = "false"
            try:
                restored = self.runner.invoke(
                    self.cli.app,
                    ["--config", str(target), "--json", "config", "show"],
                )
            finally:
                if old_disable is None:
                    os.environ.pop("JIRA_DANGEROUSLY_DISABLE_TLS_VERIFICATION", None)
                else:
                    os.environ["JIRA_DANGEROUSLY_DISABLE_TLS_VERIFICATION"] = (
                        old_disable
                    )
        self.assertFalse(
            json.loads(restored.output)["dangerously_disable_tls_verification"]
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            enabled = self.runner.invoke(
                self.cli.app,
                [
                    "--config",
                    str(target),
                    "config",
                    "set",
                    "--dangerously-allow-http",
                ],
            )
            restored = self.runner.invoke(
                self.cli.app,
                ["--config", str(target), "config", "set", "--require-https"],
            )
            settings = self.cli.load_settings(target)
        self.assertEqual(enabled.exit_code, 0, enabled.output)
        self.assertEqual(restored.exit_code, 0, restored.output)
        self.assertFalse(settings.dangerously_allow_http)

    def test_transition_fields_and_remote_link_upsert_are_explicit(self):
        move_help = self.runner.invoke(self.cli.app, ["issue", "move", "--help"])
        add_help = self.runner.invoke(self.cli.app, ["remote-link", "add", "--help"])
        upsert_help = self.runner.invoke(
            self.cli.app, ["remote-link", "upsert", "--help"]
        )
        self.assertEqual(move_help.exit_code, 0, move_help.output)
        self.assertIn("--field", Text.from_ansi(move_help.output).plain)
        self.assertNotIn("--global-id", Text.from_ansi(add_help.output).plain)
        self.assertEqual(upsert_help.exit_code, 0, upsert_help.output)
        self.assertIn("--global-id", Text.from_ansi(upsert_help.output).plain)

    def test_parse_pairs_accepts_json_and_plain_text(self):
        parsed = self.cli._parse_pairs(['labels=["one","two"]', "customfield_1=plain"])
        self.assertEqual(parsed["labels"], ["one", "two"])
        self.assertEqual(parsed["customfield_1"], "plain")

    def test_clone_omits_empty_optional_fields_rejected_by_create_screen(self):
        fields = self.cli._clone_fields(
            {
                "summary": "Source",
                "issuetype": {"name": "Task"},
                "description": "Body",
                "labels": [],
                "components": [],
                "fixVersions": [],
                "priority": {"name": "Medium"},
            },
            project="SATOS",
            summary=None,
            allowed_fields={"summary", "description", "priority"},
        )
        self.assertNotIn("fixVersions", fields)
        self.assertNotIn("components", fields)
        self.assertEqual(fields["description"], "Body")
        self.assertEqual(fields["priority"], {"name": "Medium"})

    def test_issue_create_rejects_custom_field_collisions(self):
        for field in (
            'project={"key":"OTHER"}',
            "summary=overridden",
            'parent={"key":"OTHER-1"}',
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(self.cli.typer.BadParameter),
            ):
                self.cli._issue_fields(
                    project="SATOS",
                    issue_type="Task",
                    summary="Expected",
                    description=None,
                    parent=None,
                    assignee=None,
                    reporter=None,
                    priority=None,
                    labels=None,
                    components=None,
                    fix_versions=None,
                    custom_fields=[field],
                )

    def test_subtask_clone_preserves_parent_only_within_project(self):
        source = {
            "project": {"key": "SATOS"},
            "issuetype": {"name": "Sub-task", "subtask": True},
            "summary": "Source",
            "parent": {"key": "SATOS-1"},
        }
        fields = self.cli._clone_fields(
            source,
            project="SATOS",
            summary=None,
            allowed_fields={"summary", "parent"},
        )
        self.assertEqual(fields["parent"], {"key": "SATOS-1"})
        with self.assertRaisesRegex(self.cli.typer.BadParameter, "--parent"):
            self.cli._clone_fields(
                source,
                project="OTHER",
                summary=None,
                allowed_fields={"summary", "parent"},
            )

    def test_clone_defaults_to_source_project_not_config_default(self):
        source_fields = {"project": {"key": "SOURCE"}}
        self.assertEqual(
            self.cli._clone_target_project(source_fields, explicit_project=None),
            "SOURCE",
        )
        self.assertEqual(
            self.cli._clone_target_project(source_fields, explicit_project="OTHER"),
            "OTHER",
        )

    def test_comment_and_issue_deletion_require_yes(self):
        for args in (
            ["comment", "delete", "SATOS-1", "123"],
            ["issue", "delete", "SATOS-1"],
            ["attachment", "delete", "123"],
            ["worklog", "delete", "SATOS-1", "123"],
        ):
            with self.subTest(args=args):
                result = self.runner.invoke(self.cli.app, args)
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("--yes", Text.from_ansi(result.output).plain)

    def test_epic_membership_preflights_all_targets_before_writing(self):
        class FakeClient:
            def __init__(self):
                self.edits: list[str] = []

            def get_issue(self, key, *, fields):
                if key == "BAD-1":
                    raise self_cli.JiraApiError("not found", status_code=404)
                return {"key": key}

            def edit_issue(self, key, fields):
                self.edits.append(key)

        self_cli = self.cli
        client = FakeClient()
        with self.assertRaises(self.cli.JiraApiError):
            self.cli._update_epic_membership(
                client, ["SATOS-1", "BAD-1"], "customfield_1", "SATOS-100"
            )
        self.assertEqual(client.edits, [])

    def test_epic_membership_reports_partial_write_progress(self):
        class FakeClient:
            def get_issue(self, key, *, fields):
                return {"key": key}

            def edit_issue(self, key, fields):
                if key == "SATOS-2":
                    raise self_cli.JiraApiError("write failed", status_code=500)

        self_cli = self.cli
        with self.assertRaises(self.cli.JiraApiError) as raised:
            self.cli._update_epic_membership(
                FakeClient(),
                ["SATOS-1", "SATOS-2", "SATOS-3"],
                "customfield_1",
                "SATOS-100",
            )
        self.assertEqual(
            raised.exception.payload,
            {
                "completed": ["SATOS-1"],
                "failed": "SATOS-2",
                "remaining": ["SATOS-3"],
                "jira": None,
            },
        )


if __name__ == "__main__":
    unittest.main()

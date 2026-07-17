from __future__ import annotations

import importlib.util
import json
import os
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pydantic import ValidationError

SCRIPT_PATH = Path(__file__).parents[1] / "commit_from_yaml.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))
SPEC = importlib.util.spec_from_file_location("commit_from_yaml", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
commit_from_yaml = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = commit_from_yaml
SPEC.loader.exec_module(commit_from_yaml)


class CommitFromYamlTest(unittest.TestCase):
    def test_renders_structured_sections_with_real_newlines(self) -> None:
        spec = commit_from_yaml.load_spec(
            """
subject: "chore(toolchain): configure JDK 17 with mise"
body:
  - heading: 背景
    bullets:
      - 项目以 Java 17 为目标。
  - heading: 验证
    paragraphs:
      - Maven 测试通过。
trailers:
  - key: Reviewed-by
    value: DCjanus <DCjanus@dcjanus.com>
paths:
  - .mise.toml
"""
        )

        message = commit_from_yaml.render_message(spec, "Codex:gpt-test")

        self.assertEqual(
            message,
            "chore(toolchain): configure JDK 17 with mise\n\n"
            "背景：\n"
            "- 项目以 Java 17 为目标。\n\n"
            "验证：\n"
            "Maven 测试通过。\n\n"
            "Reviewed-by: DCjanus <DCjanus@dcjanus.com>\n"
            "Assisted-by: Codex:gpt-test\n",
        )
        self.assertNotIn("\\n", message)

    def test_rejects_literal_backslash_n(self) -> None:
        with self.assertRaisesRegex(ValidationError, "literal \\\\n"):
            commit_from_yaml.load_spec(
                """
subject: "fix(commit): reject escaped newlines"
body:
  - heading: 背景
    paragraphs:
      - '第一行\\n第二行'
"""
            )

    def test_requires_breaking_details_for_a_breaking_subject(self) -> None:
        with self.assertRaisesRegex(ValidationError, "breaking_change"):
            commit_from_yaml.load_spec('subject: "feat(api)!: replace the contract"\n')

    def test_renders_breaking_change_impact_and_migration(self) -> None:
        spec = commit_from_yaml.load_spec(
            """
subject: "feat(api)!: replace the contract"
breaking_change:
  impact: 旧客户端请求会失效。
  migration: 升级到 v2 接口。
"""
        )

        message = commit_from_yaml.render_message(spec, "Codex:gpt-test")

        self.assertIn(
            "BREAKING CHANGE: 影响范围：旧客户端请求会失效。 迁移方式：升级到 v2 接口。",
            message,
        )

    def test_uses_explicit_model_without_auto_detection(self) -> None:
        with mock.patch.object(commit_from_yaml, "resolve_model_name") as resolve:
            got = commit_from_yaml.assisted_by_value("gpt-explicit", False)

        self.assertEqual(got, "Codex:gpt-explicit")
        resolve.assert_not_called()

    def test_skip_assisted_by_avoids_auto_detection(self) -> None:
        with mock.patch.object(commit_from_yaml, "resolve_model_name") as resolve:
            got = commit_from_yaml.assisted_by_value(None, True)

        self.assertIsNone(got)
        resolve.assert_not_called()

    def test_model_and_skip_are_mutually_exclusive(self) -> None:
        with self.assertRaisesRegex(commit_from_yaml.CommitError, "mutually exclusive"):
            commit_from_yaml.assisted_by_value("gpt-explicit", True)

    def test_reads_latest_complete_model_from_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout_path = Path(directory) / "rollout.jsonl"
            rollout_path.write_text(
                '{"type":"turn_context","payload":{"model":"gpt-old"}}\n'
                '{"type":"event_msg","payload":{}}\n'
                '{"type":"turn_context","payload":{"model":"gpt-new"}}\n'
                '{"type":"turn_context","payload":{"model":"unfinished"}',
                encoding="utf-8",
            )

            got = commit_from_yaml.read_latest_model_name(rollout_path)

        self.assertEqual(got, "gpt-new")

    def test_resolves_model_inside_commit_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout_path = Path(directory) / "rollout.jsonl"
            rollout_path.write_text(
                '{"type":"turn_context","payload":{"model":"gpt-current"}}\n',
                encoding="utf-8",
            )
            client = mock.MagicMock()
            client.__enter__.return_value = client
            client.request.return_value = SimpleNamespace(
                thread=SimpleNamespace(path=str(rollout_path))
            )

            with (
                mock.patch.object(commit_from_yaml, "CodexClient", return_value=client),
                mock.patch.object(
                    commit_from_yaml, "resolve_codex_bin", return_value="/usr/bin/codex"
                ),
                mock.patch.dict(
                    commit_from_yaml.os.environ,
                    {"CODEX_THREAD_ID": "thread-id"},
                    clear=True,
                ),
            ):
                got = commit_from_yaml.resolve_model_name()

        self.assertEqual(got, "gpt-current")
        client.request.assert_called_once()
        self.assertEqual(
            client.request.call_args.args,
            (
                "thread/read",
                {"threadId": "thread-id", "includeTurns": False},
            ),
        )

    def test_creates_a_real_commit_from_structured_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            commit_from_yaml.run_git(repo, ["init", "--quiet"])
            commit_from_yaml.run_git(repo, ["config", "user.name", "Test User"])
            commit_from_yaml.run_git(repo, ["config", "user.email", "test@example.com"])
            tracked = repo / "tracked.txt"
            tracked.write_text("content\n", encoding="utf-8")
            commit_from_yaml.run_git(repo, ["add", "tracked.txt"])
            spec = commit_from_yaml.load_spec(
                """
subject: "test(commit): create from yaml"
body:
  - heading: 验证
    bullets:
      - 正文使用真实换行。
paths:
  - tracked.txt
"""
            )
            message = commit_from_yaml.render_message(spec, "Codex:gpt-test")

            sha = commit_from_yaml.create_commit(repo, spec, message, "Codex:gpt-test")

            committed = commit_from_yaml.run_git(
                repo, ["show", "-s", "--format=%B", sha]
            )
        self.assertEqual(committed.rstrip("\n"), message.rstrip("\n"))
        self.assertNotIn("\\n", committed)


if __name__ == "__main__":
    unittest.main()

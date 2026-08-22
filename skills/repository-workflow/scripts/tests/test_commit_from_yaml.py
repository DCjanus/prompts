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
    def test_preserves_freeform_multiline_body(self) -> None:
        spec = commit_from_yaml.load_spec(
            """
subject: "chore(toolchain): configure JDK 17 with mise"
body: |
  背景：

  项目以 Java 17 为目标。

  验证：
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
            "背景：\n\n"
            "项目以 Java 17 为目标。\n\n"
            "验证：\n"
            "- Maven 测试通过。\n\n"
            "Reviewed-by: DCjanus <DCjanus@dcjanus.com>\n"
            "Assisted-by: Codex:gpt-test\n",
        )
        self.assertNotIn("\\n", message)

    def test_rejects_literal_backslash_n(self) -> None:
        with self.assertRaisesRegex(ValidationError, "literal \\\\n"):
            commit_from_yaml.load_spec(
                """
subject: "fix(commit): reject escaped newlines"
body: '第一行\\n第二行'
"""
            )

    def test_requires_breaking_details_for_a_breaking_subject(self) -> None:
        with self.assertRaisesRegex(ValidationError, "breaking_change"):
            commit_from_yaml.load_spec('subject: "feat(api)!: replace the contract"\n')

    def test_rejects_reserved_assisted_by_trailer(self) -> None:
        with self.assertRaisesRegex(ValidationError, "reserved trailer key"):
            commit_from_yaml.load_spec(
                """
subject: "chore(commit): reject reserved trailer"
trailers:
  - key: Assisted-by
    value: Manual:model
"""
            )

    def test_rejects_multiline_trailer_value(self) -> None:
        with self.assertRaises(ValidationError):
            commit_from_yaml.load_spec(
                """
subject: "chore(commit): reject multiline trailer"
trailers:
  - key: Reviewed-by
    value: |
      First reviewer
      Second reviewer
"""
            )

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
body: |
  验证：
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

    def test_commits_an_untracked_path_without_pre_staging_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            commit_from_yaml.run_git(repo, ["init", "--quiet"])
            commit_from_yaml.run_git(repo, ["config", "user.name", "Test User"])
            commit_from_yaml.run_git(repo, ["config", "user.email", "test@example.com"])
            unrelated = repo / "unrelated.txt"
            unrelated.write_text("base\n", encoding="utf-8")
            commit_from_yaml.run_git(repo, ["add", "unrelated.txt"])
            commit_from_yaml.run_git(repo, ["commit", "-m", "test: initial commit"])

            unrelated.write_text("staged change\n", encoding="utf-8")
            commit_from_yaml.run_git(repo, ["add", "unrelated.txt"])
            new_file = repo / "new.txt"
            new_file.write_text("new content\n", encoding="utf-8")
            spec = commit_from_yaml.load_spec(
                """
subject: "test(commit): include untracked path"
paths:
  - new.txt
"""
            )
            message = commit_from_yaml.render_message(spec, "Codex:gpt-test")

            sha = commit_from_yaml.create_commit(repo, spec, message, "Codex:gpt-test")

            committed_paths = commit_from_yaml.run_git(
                repo, ["show", "--format=", "--name-only", sha]
            ).splitlines()
            staged_paths = commit_from_yaml.run_git(
                repo, ["diff", "--cached", "--name-only"]
            ).splitlines()

        self.assertEqual(committed_paths, ["new.txt"])
        self.assertEqual(staged_paths, ["unrelated.txt"])

    def test_commits_tracked_and_untracked_paths_matching_git_glob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            commit_from_yaml.run_git(repo, ["init", "--quiet"])
            commit_from_yaml.run_git(repo, ["config", "user.name", "Test User"])
            commit_from_yaml.run_git(repo, ["config", "user.email", "test@example.com"])
            tracked = repo / "src" / "tracked.txt"
            tracked.parent.mkdir()
            tracked.write_text("base\n", encoding="utf-8")
            unrelated = repo / "unrelated.txt"
            unrelated.write_text("base\n", encoding="utf-8")
            commit_from_yaml.run_git(repo, ["add", "src/tracked.txt", "unrelated.txt"])
            commit_from_yaml.run_git(repo, ["commit", "-m", "test: initial commit"])

            tracked.write_text("changed\n", encoding="utf-8")
            untracked = repo / "src" / "nested" / "new.txt"
            untracked.parent.mkdir()
            untracked.write_text("new content\n", encoding="utf-8")
            unrelated.write_text("staged change\n", encoding="utf-8")
            commit_from_yaml.run_git(repo, ["add", "unrelated.txt"])
            spec = commit_from_yaml.load_spec(
                """
subject: "test(commit): support git glob pathspecs"
paths:
  - ":(glob)src/**/*.txt"
"""
            )
            message = commit_from_yaml.render_message(spec, "Codex:gpt-test")

            sha = commit_from_yaml.create_commit(repo, spec, message, "Codex:gpt-test")

            committed_paths = commit_from_yaml.run_git(
                repo, ["show", "--format=", "--name-only", sha]
            ).splitlines()
            staged_paths = commit_from_yaml.run_git(
                repo, ["diff", "--cached", "--name-only"]
            ).splitlines()

        self.assertEqual(
            committed_paths,
            ["src/nested/new.txt", "src/tracked.txt"],
        )
        self.assertEqual(staged_paths, ["unrelated.txt"])

    def test_restores_untracked_path_after_commit_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            commit_from_yaml.run_git(repo, ["init", "--quiet"])
            commit_from_yaml.run_git(repo, ["config", "user.name", "Test User"])
            commit_from_yaml.run_git(repo, ["config", "user.email", "test@example.com"])
            tracked = repo / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            commit_from_yaml.run_git(repo, ["add", "tracked.txt"])
            commit_from_yaml.run_git(repo, ["commit", "-m", "test: initial commit"])

            new_file = repo / "new.txt"
            new_file.write_text("new content\n", encoding="utf-8")
            hook = repo / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            hook.chmod(0o755)
            spec = commit_from_yaml.load_spec(
                'subject: "test(commit): fail safely"\npaths:\n  - new.txt\n'
            )
            message = commit_from_yaml.render_message(spec, "Codex:gpt-test")

            with self.assertRaises(commit_from_yaml.CommitError):
                commit_from_yaml.create_commit(repo, spec, message, "Codex:gpt-test")

            status = commit_from_yaml.run_git(
                repo, ["status", "--short", "--", "new.txt"]
            )

        self.assertEqual(status, "?? new.txt\n")


class ValidateMessageTest(unittest.TestCase):
    def test_accepts_regular_message_with_expected_assistant(self) -> None:
        commit_from_yaml.validate_message(
            "fix(cli): handle empty input\n\nAssisted-by: Codex:gpt-test\n",
            "Codex:gpt-test",
        )

    def test_accepts_breaking_message_with_footer(self) -> None:
        commit_from_yaml.validate_message(
            "feat(git)!: replace branch command\n\n"
            "BREAKING CHANGE: 影响范围：旧命令失效。迁移方式：使用新命令。\n\n"
            "Assisted-by: Codex:gpt-test\n",
            "Codex:gpt-test",
        )

    def test_rejects_breaking_title_without_footer(self) -> None:
        with self.assertRaisesRegex(
            commit_from_yaml.CommitValidationError,
            "must contain exactly one BREAKING CHANGE footer",
        ):
            commit_from_yaml.validate_message(
                "feat(git)!: replace branch command\n\nAssisted-by: Codex:gpt-test\n",
                "Codex:gpt-test",
            )

    def test_rejects_breaking_footer_without_bang(self) -> None:
        with self.assertRaisesRegex(
            commit_from_yaml.CommitValidationError,
            "requires ! in the title",
        ):
            commit_from_yaml.validate_message(
                "feat(git): replace branch command\n\n"
                "BREAKING CHANGE: 影响范围：旧命令失效。迁移方式：使用新命令。\n\n"
                "Assisted-by: Codex:gpt-test\n",
                "Codex:gpt-test",
            )

    def test_rejects_malformed_breaking_footer(self) -> None:
        with self.assertRaisesRegex(
            commit_from_yaml.CommitValidationError,
            "malformed BREAKING CHANGE footer",
        ):
            commit_from_yaml.validate_message(
                "feat(git)!: replace branch command\n\n"
                "BREAKING CHANGE: Invalid footer.:\n\n"
                "Assisted-by: Codex:gpt-test\n",
                "Codex:gpt-test",
            )

    def test_rejects_unparseable_assistant_trailer(self) -> None:
        with self.assertRaisesRegex(
            commit_from_yaml.CommitValidationError,
            "expected exactly one parsed trailer",
        ):
            commit_from_yaml.validate_message(
                "fix(cli): handle empty input\n\nAssisted-by: Codex:gpt-test:\n",
                "Codex:gpt-test",
            )

    def test_accepts_explicitly_skipped_assistant(self) -> None:
        commit_from_yaml.validate_message("chore: manual commit\n", None)

    def test_rejects_assistant_when_skipped(self) -> None:
        with self.assertRaisesRegex(
            commit_from_yaml.CommitValidationError,
            "must be absent",
        ):
            commit_from_yaml.validate_message(
                "chore: manual commit\n\nAssisted-by: Codex:gpt-test\n",
                None,
            )


if __name__ == "__main__":
    unittest.main()

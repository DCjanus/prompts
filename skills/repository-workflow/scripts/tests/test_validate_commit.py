from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "validate_commit.py"
SPEC = importlib.util.spec_from_file_location("validate_commit", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
validate_commit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_commit)


class ValidateMessageTest(unittest.TestCase):
    def test_accepts_a_regular_commit_with_the_expected_assistant(self) -> None:
        validate_commit.validate_message(
            "fix(cli): handle empty input\n\nAssisted-by: Codex:gpt-test\n",
            "Codex:gpt-test",
        )

    def test_accepts_a_breaking_commit_with_a_footer_and_assistant(self) -> None:
        validate_commit.validate_message(
            "feat(git)!: replace branch command\n\n"
            "BREAKING CHANGE: Replace trim with branches and recreate exclude rules.\n\n"
            "Assisted-by: Codex:gpt-test\n",
            "Codex:gpt-test",
        )

    def test_rejects_a_breaking_title_without_a_footer(self) -> None:
        with self.assertRaisesRegex(
            validate_commit.ValidationError,
            "must contain exactly one BREAKING CHANGE footer",
        ):
            validate_commit.validate_message(
                "feat(git)!: replace branch command\n\nAssisted-by: Codex:gpt-test\n",
                "Codex:gpt-test",
            )

    def test_rejects_a_breaking_footer_without_a_bang(self) -> None:
        with self.assertRaisesRegex(
            validate_commit.ValidationError,
            "requires ! in the title",
        ):
            validate_commit.validate_message(
                "feat(git): replace branch command\n\n"
                "BREAKING CHANGE: Replace trim with branches.\n\n"
                "Assisted-by: Codex:gpt-test\n",
                "Codex:gpt-test",
            )

    def test_rejects_breaking_change_misused_as_a_git_trailer(self) -> None:
        with self.assertRaisesRegex(
            validate_commit.ValidationError,
            "malformed BREAKING CHANGE footer",
        ):
            validate_commit.validate_message(
                "feat(git)!: replace branch command\n\n"
                "BREAKING CHANGE: Replace trim with branches.:\n"
                "Assisted-by: Codex:gpt-test\n",
                "Codex:gpt-test",
            )

    def test_rejects_an_unparseable_assistant_trailer(self) -> None:
        with self.assertRaisesRegex(
            validate_commit.ValidationError,
            "expected exactly one parsed trailer",
        ):
            validate_commit.validate_message(
                "fix(cli): handle empty input\n\nAssisted-by: Codex:gpt-test:\n",
                "Codex:gpt-test",
            )


if __name__ == "__main__":
    unittest.main()

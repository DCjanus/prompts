from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "codex_git_commit.py"
SPEC = importlib.util.spec_from_file_location("codex_git_commit", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
codex_git_commit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_git_commit)


class ResolveModelNameTest(unittest.TestCase):
    def test_reads_only_model_without_validating_thread_turns(self) -> None:
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.request.return_value = SimpleNamespace(model="gpt-test")
        client.thread_resume.side_effect = AssertionError(
            "thread_resume must not parse the complete thread history"
        )

        with (
            mock.patch.object(codex_git_commit, "CodexClient", return_value=client),
            mock.patch.object(
                codex_git_commit, "resolve_codex_bin", return_value="/usr/bin/codex"
            ),
        ):
            got = codex_git_commit.resolve_model_name("thread-id")

        self.assertEqual(got, "gpt-test")
        client.request.assert_called_once()
        method, params = client.request.call_args.args
        self.assertEqual(method, "thread/resume")
        self.assertEqual(params, {"threadId": "thread-id"})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT_PATH = Path(__file__).parents[1] / "codex_git_commit.py"
SPEC = importlib.util.spec_from_file_location("codex_git_commit", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
codex_git_commit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_git_commit)


class ResolveModelNameTest(unittest.TestCase):
    def test_reads_latest_model_from_rollout_without_resuming_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout_path = Path(directory) / "rollout.jsonl"
            rollout_path.write_text(
                '{"type":"turn_context","payload":{"model":"gpt-old"}}\n'
                '{"type":"event_msg","payload":{}}\n'
                '{"type":"turn_context","payload":{"model":"gpt-new"}}\n'
                '{"type":"turn_context","payload":{"model":"unfinished"}',
                encoding="utf-8",
            )

            client = mock.MagicMock()
            client.__enter__.return_value = client
            client.request.return_value = SimpleNamespace(
                thread=SimpleNamespace(path=str(rollout_path))
            )

            with (
                mock.patch.object(codex_git_commit, "CodexClient", return_value=client),
                mock.patch.object(
                    codex_git_commit,
                    "resolve_codex_bin",
                    return_value="/usr/bin/codex",
                ),
                mock.patch.dict(codex_git_commit.os.environ, {}, clear=True),
            ):
                got = codex_git_commit.resolve_model_name("thread-id")

        self.assertEqual(got, "gpt-new")
        client.request.assert_called_once()
        method, params = client.request.call_args.args
        self.assertEqual(method, "thread/read")
        self.assertEqual(
            params,
            {"threadId": "thread-id", "includeTurns": False},
        )

    def test_prefers_explicit_model_name_without_starting_app_server(self) -> None:
        with (
            mock.patch.object(codex_git_commit, "CodexClient") as client_class,
            mock.patch.dict(
                codex_git_commit.os.environ,
                {"CODEX_MODEL_NAME": " gpt-override "},
                clear=True,
            ),
        ):
            got = codex_git_commit.resolve_model_name("thread-id")

        self.assertEqual(got, "gpt-override")
        client_class.assert_not_called()

    def test_rejects_malformed_complete_rollout_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout_path = Path(directory) / "rollout.jsonl"
            rollout_path.write_text(
                '{"type":"turn_context","payload":{"model":"gpt-old"}}\nnot-json\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "invalid rollout JSON at line 2"):
                codex_git_commit.read_latest_model_name(rollout_path)

    def test_requires_rollout_path_from_thread_read(self) -> None:
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.request.return_value = SimpleNamespace(thread=SimpleNamespace(path=None))

        with (
            mock.patch.object(codex_git_commit, "CodexClient", return_value=client),
            mock.patch.object(
                codex_git_commit, "resolve_codex_bin", return_value="/usr/bin/codex"
            ),
            mock.patch.dict(codex_git_commit.os.environ, {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "does not have a rollout path"),
        ):
            codex_git_commit.resolve_model_name("thread-id")


if __name__ == "__main__":
    unittest.main()

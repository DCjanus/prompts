from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "configure_squash_merge_policy.py"
SPEC = importlib.util.spec_from_file_location(
    "configure_squash_merge_policy", SCRIPT_PATH
)
assert SPEC is not None
configure_squash_merge_policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(configure_squash_merge_policy)


def test_normalize_repo() -> None:
    assert (
        configure_squash_merge_policy.normalize_repo("DCjanus/prompts")
        == "DCjanus/prompts"
    )
    assert (
        configure_squash_merge_policy.normalize_repo(
            "https://github.com/DCjanus/prompts.git"
        )
        == "DCjanus/prompts"
    )


def test_policy_payload() -> None:
    assert configure_squash_merge_policy.policy_payload() == {
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "squash_merge_commit_title": "PR_TITLE",
        "squash_merge_commit_message": "PR_BODY",
        "delete_branch_on_merge": True,
    }


def test_apply_policy_updates_and_reads_repo(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class FakeCompletedProcess:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(
        args: list[str],
        *,
        cwd: str,
        input: str | None,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> FakeCompletedProcess:
        parsed_input = json.loads(input) if input is not None else None
        calls.append(
            {
                "args": args,
                "cwd": cwd,
                "input": parsed_input,
                "text": text,
                "capture_output": capture_output,
                "check": check,
            }
        )
        return FakeCompletedProcess(
            json.dumps(
                {
                    "allow_squash_merge": True,
                    "allow_merge_commit": False,
                    "allow_rebase_merge": False,
                    "squash_merge_commit_title": "PR_TITLE",
                    "squash_merge_commit_message": "PR_BODY",
                    "delete_branch_on_merge": True,
                }
            )
        )

    monkeypatch.setattr(configure_squash_merge_policy.subprocess, "run", fake_run)

    response = configure_squash_merge_policy.apply_policy(
        repo="DCjanus/prompts",
        cwd=tmp_path,
        hostname="github.example.com",
    )

    assert response["allow_squash_merge"] is True
    assert calls == [
        {
            "args": [
                "gh",
                "api",
                "repos/DCjanus/prompts",
                "--method",
                "PATCH",
                "--input",
                "-",
                "--header",
                "Content-Type: application/json",
                "--hostname",
                "github.example.com",
            ],
            "cwd": str(tmp_path),
            "input": {
                "allow_squash_merge": True,
                "allow_merge_commit": False,
                "allow_rebase_merge": False,
                "squash_merge_commit_title": "PR_TITLE",
                "squash_merge_commit_message": "PR_BODY",
                "delete_branch_on_merge": True,
            },
            "text": True,
            "capture_output": True,
            "check": False,
        },
        {
            "args": [
                "gh",
                "api",
                "repos/DCjanus/prompts",
                "--method",
                "GET",
                "--hostname",
                "github.example.com",
            ],
            "cwd": str(tmp_path),
            "input": None,
            "text": True,
            "capture_output": True,
            "check": False,
        },
    ]


def test_validate_settings_reports_mismatch() -> None:
    payload = configure_squash_merge_policy.expected_settings()
    payload["allow_merge_commit"] = True

    try:
        configure_squash_merge_policy.validate_settings(payload)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "verification failed" in message
    assert "- allow_merge_commit: expected False, got True" in message

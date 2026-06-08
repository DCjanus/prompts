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


def test_encode_project() -> None:
    assert configure_squash_merge_policy.encode_project("122477") == "122477"
    assert (
        configure_squash_merge_policy.encode_project("group/project")
        == "group%2Fproject"
    )


def test_policy_payload() -> None:
    assert configure_squash_merge_policy.policy_payload() == {
        "merge_method": "rebase_merge",
        "squash_option": "always",
        "squash_commit_template": "%{title}\n\n%{description}\n\n%{co_authored_by}",
        "remove_source_branch_after_merge": True,
    }


def test_apply_policy_updates_and_reads_project(monkeypatch, tmp_path: Path) -> None:
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
                    "merge_method": "rebase_merge",
                    "squash_option": "always",
                    "squash_commit_template": "%{title}\n\n%{description}\n\n%{co_authored_by}",
                    "remove_source_branch_after_merge": True,
                    "merge_commit_template": None,
                }
            )
        )

    monkeypatch.setattr(configure_squash_merge_policy.subprocess, "run", fake_run)

    response = configure_squash_merge_policy.apply_policy(
        project="group/project",
        cwd=tmp_path,
        hostname="gitlab.example.com",
    )

    assert response["merge_method"] == "rebase_merge"
    assert calls == [
        {
            "args": [
                "glab",
                "api",
                "projects/group%2Fproject",
                "--method",
                "PUT",
                "--input",
                "-",
                "--header",
                "Content-Type: application/json",
                "--hostname",
                "gitlab.example.com",
            ],
            "cwd": str(tmp_path),
            "input": {
                "merge_method": "rebase_merge",
                "squash_option": "always",
                "squash_commit_template": "%{title}\n\n%{description}\n\n%{co_authored_by}",
                "remove_source_branch_after_merge": True,
            },
            "text": True,
            "capture_output": True,
            "check": False,
        },
        {
            "args": [
                "glab",
                "api",
                "projects/group%2Fproject",
                "--method",
                "GET",
                "--hostname",
                "gitlab.example.com",
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
    payload["squash_option"] = "default_on"

    try:
        configure_squash_merge_policy.validate_settings(payload)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "verification failed" in message
    assert "- squash_option: expected 'always', got 'default_on'" in message

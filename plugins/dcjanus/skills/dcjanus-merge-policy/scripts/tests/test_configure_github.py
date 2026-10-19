from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "configure_github.py"
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
        "allow_auto_merge": True,
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
                    "owner": {"type": "User"},
                    "allow_squash_merge": True,
                    "allow_merge_commit": False,
                    "allow_rebase_merge": False,
                    "allow_auto_merge": True,
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
    assert response["allow_auto_merge"] is True
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
                "allow_auto_merge": True,
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


@pytest.mark.parametrize("actual", [False, None])
def test_validate_settings_requires_auto_merge(actual: bool | None) -> None:
    payload = configure_squash_merge_policy.expected_settings()
    if actual is None:
        payload.pop("allow_auto_merge")
    else:
        payload["allow_auto_merge"] = actual

    with pytest.raises(RuntimeError, match="allow_auto_merge: expected True"):
        configure_squash_merge_policy.validate_settings(payload)


@pytest.fixture
def organization_api(monkeypatch):
    """以有状态 API 替身验证 CLI 写入、重入与回读行为。"""

    state = SimpleNamespace(rulesets={}, writes=[], ignore_enforcement=False)
    repository = {"owner": {"type": "Organization"}, "default_branch": "main"}

    def fake_run(args, *, input, **kwargs):
        path = args[2].split("repos/example/project", 1)[1].lstrip("/")
        method = args[args.index("--method") + 1]
        payload = json.loads(input) if input else None
        if method in ("POST", "PUT", "PATCH"):
            state.writes.append((method, path, deepcopy(payload)))
        if not path:
            if payload:
                repository.update(payload)
            response = repository
        elif path.startswith("rulesets?"):
            response = [
                [
                    {"id": key, "name": value["name"]}
                    for key, value in state.rulesets.items()
                ]
            ]
        elif path == "rulesets" or path.startswith("rulesets/"):
            rule_id = (
                int(path.split("/")[1]) if "/" in path else len(state.rulesets) + 1
            )
            if payload:
                state.rulesets[rule_id] = {"id": rule_id, **payload}
                if state.ignore_enforcement:
                    state.rulesets[rule_id]["enforcement"] = "disabled"
            response = state.rulesets[rule_id]
        elif path == "rules/branches/main":
            response = [
                {**rule, "ruleset_id": rule_id}
                for rule_id, ruleset in state.rulesets.items()
                if ruleset["enforcement"] == "active"
                for rule in ruleset["rules"]
            ]
        else:
            raise AssertionError(f"unexpected API route: {method} {path}")
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")

    monkeypatch.setattr(configure_squash_merge_policy.subprocess, "run", fake_run)
    return state


def invoke_organization(*args):
    return CliRunner().invoke(
        configure_squash_merge_policy.app,
        ["--repo", "example/project", "--json", *args],
    )


def test_organization_cli_enables_effective_squash_queue(organization_api):
    result = invoke_organization(
        "--required-check", "test", "--required-check", "build"
    )
    assert result.exit_code == 0, result.output
    queue = json.loads(result.stdout)["merge_queue"]
    assert queue["status"] == "configured"
    assert len(organization_api.rulesets) == 1
    ruleset = queue["ruleset"]
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    rules = {rule["type"]: rule["parameters"] for rule in ruleset["rules"]}
    assert rules["merge_queue"]["merge_method"] == "SQUASH"
    assert {
        item["context"]
        for item in rules["required_status_checks"]["required_status_checks"]
    } == {"test", "build"}


def test_organization_cli_preserves_existing_rules_and_checks(organization_api):
    assert invoke_organization("--required-check", "test").exit_code == 0
    current = organization_api.rulesets[1]
    current["rules"].append({"type": "required_signatures"})
    current["bypass_actors"] = [
        {"actor_type": "OrganizationAdmin", "bypass_mode": "always"}
    ]
    result = invoke_organization(
        "--required-check", "build", "--required-check", "test"
    )
    assert result.exit_code == 0, result.output
    assert len(organization_api.rulesets) == 1
    current = organization_api.rulesets[1]
    assert {"type": "required_signatures"} in current["rules"]
    assert current["bypass_actors"][0]["actor_type"] == "OrganizationAdmin"
    checks = next(
        rule["parameters"]["required_status_checks"]
        for rule in current["rules"]
        if rule["type"] == "required_status_checks"
    )
    assert [item["context"] for item in checks] == ["test", "build"]
    assert invoke_organization().exit_code == 0
    assert organization_api.rulesets[1]["rules"] == current["rules"]


def test_organization_cli_preserves_external_queue(organization_api):
    assert invoke_organization().exit_code == 0
    organization_api.rulesets[1]["name"] = "Team rules"
    before = deepcopy(organization_api.rulesets)
    result = invoke_organization()
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["merge_queue"]["status"] == "existing"
    assert organization_api.rulesets == before
    result = invoke_organization("--required-check", "test")
    assert result.exit_code == 1
    assert organization_api.rulesets == before


def test_organization_cli_fails_when_saved_queue_is_not_active(organization_api):
    organization_api.ignore_enforcement = True
    result = invoke_organization()
    assert result.exit_code == 1
    assert "verification failed" in result.output

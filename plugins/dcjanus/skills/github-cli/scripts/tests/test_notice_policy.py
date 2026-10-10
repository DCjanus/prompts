"""验证 GitHub 身份查询、负责人及无写入预览。"""

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "github_notice", Path(__file__).resolve().parents[1] / "github_pr.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def args(**overrides):
    return argparse.Namespace(
        **(
            {
                "repo": "org/repo",
                "actor": "me",
                "assignee": None,
                "notice_mode": "auto",
                "notice_language": "zh",
                "notice": None,
                "no_notice": False,
                "dry_run": True,
                "title": None,
                "draft": False,
            }
            | overrides
        )
    )


@pytest.mark.parametrize(
    "role,assigned,expected",
    [
        ("maintain", False, "actor-is-maintainer"),
        ("admin", False, "actor-is-maintainer"),
        ("write", True, "actor-is-assignee"),
        ("write", False, "external-contribution"),
        (None, False, "identity-unknown"),
    ],
)
def test_roles_and_assignees(monkeypatch, role, assigned, expected):
    def gh(*command, **kwargs):
        assert "PATCH" not in command
        if command[0] == "repo":
            return json.dumps(
                {
                    "nameWithOwner": "org/repo",
                    "url": "https://enterprise.example/org/repo",
                }
            )
        assert "enterprise.example" in command
        if role is None:
            raise subprocess.CalledProcessError(403, command)
        return json.dumps({"role_name": role, "permission": "write"})

    monkeypatch.setattr(module, "gh", gh)
    pr = {
        "assignees": [{"login": "ME"}] if assigned else [],
        "reviewers": [{"login": "me"}],
    }
    body, reason = module.notice_body(args(), "Technical\n\n" + module.CHINESE, pr)
    assert reason == expected
    assert (module.CHINESE in body) == (
        expected in {"external-contribution", "identity-unknown"}
    )


def test_create_reconciles_server_assignee(monkeypatch, tmp_path):
    source = tmp_path / "body.md"
    source.write_text("Technical")
    options = args(
        body_file=source,
        base="main",
        head="me:fix",
        title="Fix",
        dry_run=False,
        no_maintainer_edit=False,
        assignee=["other"],
    )
    patches = []

    def gh(*command, **kwargs):
        if command[0] == "repo":
            return json.dumps(
                {"nameWithOwner": "org/repo", "url": "https://github.com/org/repo"}
            )
        if command[0] == "pr":
            assert "--assignee" in command
            return "https://github.com/org/repo/pull/1"
        if "PATCH" in command:
            patches.append(kwargs["payload"])
            return "{}"
        return json.dumps({"role_name": "write"})

    monkeypatch.setattr(module, "gh", gh)
    actual = {
        "number": 1,
        "title": "Fix",
        "body": "Technical",
        "assignees": [{"login": "me"}],
    }
    monkeypatch.setattr(module, "verify_permission", lambda *a: actual)
    monkeypatch.setattr(module, "read_pr", lambda *a: actual)
    assert module.create(options).endswith("/1")
    assert patches == [{"body": "Technical\n"}]
    assert source.read_text() == "Technical"


def test_update_dry_run_reads_existing_assignees(monkeypatch, tmp_path):
    source = tmp_path / "body.md"
    source.write_text("Technical\n\n" + module.CHINESE)
    calls = []

    def gh(*command, **kwargs):
        calls.append(command)
        if command[0:2] == ("pr", "view"):
            return json.dumps(
                {
                    "url": "https://github.com/org/repo/pull/1",
                    "assignees": [{"login": "me"}],
                }
            )
        if command[0] == "repo":
            return json.dumps(
                {"nameWithOwner": "org/repo", "url": "https://github.com/org/repo"}
            )
        return json.dumps({"role_name": "write"})

    monkeypatch.setattr(module, "gh", gh)
    preview = json.loads(module.update(args(pr="1", body_file=source)))
    assert preview["notice_reason"] == "actor-is-assignee"
    assert preview["body"] == "Technical\n"
    assert all("PATCH" not in call for call in calls)


def test_update_writes_assignees_via_issue_endpoint(monkeypatch, tmp_path):
    source = tmp_path / "body.md"
    source.write_text("Technical\n\n" + module.CHINESE)
    actual = {
        "url": "https://github.com/org/repo/pull/1",
        "body": source.read_text(),
        "title": "Fix",
        "assignees": [],
    }
    writes = []

    def gh(*command, **kwargs):
        if command[0] == "pr":
            return json.dumps(actual)
        if command[0] == "repo":
            return json.dumps(
                {"nameWithOwner": "org/repo", "url": "https://github.com/org/repo"}
            )
        if "PATCH" in command:
            assert "repos/org/repo/issues/1" in command
            payload = kwargs["payload"]
            writes.append(payload)
            actual["body"] = payload["body"]
            actual["assignees"] = [{"login": user} for user in payload["assignees"]]
            return "{}"
        return json.dumps({"role_name": "write"})

    monkeypatch.setattr(module, "gh", gh)
    monkeypatch.setattr(module, "read_pr", lambda *a: actual)
    module.update(args(pr="1", body_file=source, dry_run=False, assignee=["me"]))
    assert writes == [{"body": "Technical\n", "assignees": ["me"]}]


def test_unknown_authenticated_identity_preserves_notice(monkeypatch):
    def gh(*command, **kwargs):
        if command[0] == "repo":
            return json.dumps(
                {"nameWithOwner": "org/repo", "url": "https://github.com/org/repo"}
            )
        raise subprocess.CalledProcessError(403, command)

    monkeypatch.setattr(module, "gh", gh)
    body, reason = module.notice_body(args(actor=None), "Technical")
    assert reason == "identity-unknown"
    assert module.CHINESE in body

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx2 as httpx
import pytest
from rich.text import Text
from typer.testing import CliRunner

SCRIPT = Path(__file__).parents[1] / "scripts" / "linear_cli.py"
SPEC = importlib.util.spec_from_file_location("linear_cli", SCRIPT)
assert SPEC and SPEC.loader
linear_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = linear_cli
SPEC.loader.exec_module(linear_cli)


def response(data: dict, status: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "https://linear.test/graphql")
    return httpx.Response(status, json=data, request=request)


def test_help_uses_progressive_resource_groups() -> None:
    runner = CliRunner()

    root = runner.invoke(linear_cli.app, ["--help"])
    assert root.exit_code == 0, root.output
    assert "team" in root.output
    assert "issue" in root.output
    assert "workflow-state" in root.output
    assert "team-show" not in root.output
    assert "issue-get" not in root.output

    team = runner.invoke(linear_cli.app, ["team", "--help"])
    assert team.exit_code == 0, team.output
    assert "automation" in team.output

    automation = runner.invoke(linear_cli.app, ["team", "automation", "--help"])
    assert automation.exit_code == 0, automation.output
    assert "show" in automation.output
    assert "update" in automation.output

    issue = runner.invoke(linear_cli.app, ["issue", "--help"])
    assert issue.exit_code == 0, issue.output
    assert "comment" in issue.output
    assert "relation" in issue.output

    label = runner.invoke(linear_cli.app, ["label", "--help"])
    assert label.exit_code == 0, label.output
    assert "list" in label.output
    assert "get" in label.output
    assert "create" in label.output
    assert "update" in label.output
    assert "delete" in label.output

    workflow_state = runner.invoke(linear_cli.app, ["workflow-state", "--help"])
    assert workflow_state.exit_code == 0, workflow_state.output
    assert "list" in workflow_state.output
    assert "create" in workflow_state.output
    assert "update" in workflow_state.output

    api = runner.invoke(linear_cli.app, ["api", "--help"])
    assert api.exit_code == 0, api.output
    assert "graphql" in api.output


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["api", "graphql", "--help"], ["QUERY_FILE", "JSON_FILE"]),
        (
            ["issue", "create", "--help"],
            [
                "MARKDOWN_FILE",
                "%Y-%m-%d",
                "--state-id",
                "STATE_ID",
                "--label-id",
                "LABEL_ID",
                "--no-due-date",
                "--no-assignee",
            ],
        ),
        (
            ["issue", "update", "--help"],
            [
                "ISSUE_ID",
                "MARKDOWN_FILE",
                "%Y-%m-%d",
                "--state-id",
                "STATE_ID",
            ],
        ),
        (
            ["issue", "comment", "create", "--help"],
            ["ISSUE_ID", "MARKDOWN_FILE"],
        ),
        (["view", "create", "--help"], ["JSON_OBJECT"]),
    ],
)
def test_help_exposes_semantic_parameter_contracts(
    arguments: list[str], expected: list[str]
) -> None:
    result = CliRunner().invoke(linear_cli.app, arguments)

    assert result.exit_code == 0, result.output
    output = Text.from_ansi(result.output).plain
    for value in expected:
        assert value in output


def test_api_key_auth_and_graphql_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "lin_api_key"
        return response({"data": {"viewer": {"id": "me"}}})

    client = linear_cli.LinearClient(
        linear_cli.Settings("https://linear.test/graphql", "lin_api_key", False),
        transport=httpx.MockTransport(handler),
    )
    assert client.query("query Viewer { viewer { id } }")["viewer"]["id"] == "me"

    broken = linear_cli.LinearClient(
        linear_cli.Settings("https://linear.test/graphql", "key", False),
        transport=httpx.MockTransport(
            lambda request: response(
                {"data": {"issue": None}, "errors": [{"message": "denied"}]}
            )
        ),
    )
    with pytest.raises(linear_cli.LinearError, match="denied"):
        broken.query("query Issue { issue { id } }")


def test_oauth_uses_bearer_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer oauth-token"
        return response({"data": {"viewer": {"id": "me"}}})

    client = linear_cli.LinearClient(
        linear_cli.Settings("https://linear.test/graphql", "oauth-token", True),
        transport=httpx.MockTransport(handler),
    )
    assert client.query("query Viewer { viewer { id } }")["viewer"]["id"] == "me"


def test_config_set_requires_prompt_and_saves_mode_0600(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "linear" / "config.toml"
    runner = CliRunner()
    rejected = runner.invoke(linear_cli.app, ["config", "set", "--config", str(config)])
    assert rejected.exit_code != 0

    monkeypatch.setattr(linear_cli.getpass, "getpass", lambda prompt: "secret")
    saved = runner.invoke(
        linear_cli.app,
        [
            "config",
            "set",
            "--config",
            str(config),
            "--auth-type",
            "oauth",
            "--prompt-token",
        ],
    )
    assert saved.exit_code == 0, saved.output
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert "secret" not in saved.output


@pytest.mark.parametrize("token", ["wrong", "lin_api_bad key", "lin_api_bad\nkey"])
def test_personal_api_key_format_is_rejected_before_network(token: str) -> None:
    with pytest.raises(linear_cli.LinearError):
        linear_cli.validate_personal_api_key(token)


def test_auth_login_api_key_hides_and_saves_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "linear" / "config.toml"
    monkeypatch.setattr(linear_cli.getpass, "getpass", lambda prompt: "lin_api_secret")
    monkeypatch.setattr(
        linear_cli,
        "read_identity",
        lambda client: {
            "viewer": {"id": "me", "name": "Me"},
            "organization": {"id": "org", "name": "Workspace", "urlKey": "ws"},
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["auth", "login-api-key", "--config", str(config)],
    )

    assert result.exit_code == 0, result.output
    assert "lin_api_secret" not in result.output
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert linear_cli.tomllib.loads(config.read_text()) == {
        "auth_type": "api-key",
        "token": "lin_api_secret",
    }


def test_auth_login_api_key_does_not_replace_config_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "linear" / "config.toml"
    linear_cli.save_config({"auth_type": "api-key", "token": "existing"}, config)
    monkeypatch.setattr(linear_cli.getpass, "getpass", lambda prompt: "invalid")

    def reject(client: object) -> dict:
        raise linear_cli.LinearError("unauthorized")

    monkeypatch.setattr(linear_cli, "read_identity", reject)
    result = CliRunner().invoke(
        linear_cli.app,
        ["auth", "login-api-key", "--config", str(config)],
    )

    assert result.exit_code != 0
    assert "invalid" not in result.output
    assert linear_cli.tomllib.loads(config.read_text())["token"] == "existing"


def test_config_show_masks_all_tokens(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    linear_cli.save_config(
        {
            "auth_type": "oauth",
            "token": "access-secret",
            "refresh_token": "refresh-secret",
        },
        config,
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["config", "show", "--config", str(config)],
    )

    assert result.exit_code == 0, result.output
    assert "access-secret" not in result.output
    assert "refresh-secret" not in result.output
    payload = json.loads(result.output)
    assert payload["token"] == "********"
    assert payload["refresh_token"] == "********"


def test_default_team_can_be_set_used_overridden_and_cleared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    linear_cli.save_config(
        {"auth_type": "api-key", "token": "lin_api_saved-key"}, config
    )
    monkeypatch.setenv("LINEAR_CONFIG", str(config))
    resolved_keys: list[str] = []

    class StubClient:
        pass

    monkeypatch.setattr(
        linear_cli, "get_client", lambda endpoint, config_path=None: StubClient()
    )

    def resolve(client: object, team: str) -> dict:
        resolved_keys.append(team)
        return {"id": f"{team}-id", "key": team.upper(), "name": team}

    monkeypatch.setattr(linear_cli, "resolve_team", resolve)
    runner = CliRunner()

    saved = runner.invoke(
        linear_cli.app,
        ["config", "set-default-team", "dcj", "--config", str(config)],
    )
    assert saved.exit_code == 0, saved.output
    assert linear_cli.load_config(config) == {
        "auth_type": "api-key",
        "token": "lin_api_saved-key",
        "default_team": "DCJ",
    }
    assert linear_cli.select_team(None) == "DCJ"
    assert linear_cli.select_team("OTHER") == "OTHER"

    cleared = runner.invoke(
        linear_cli.app,
        ["config", "clear-default-team", "--config", str(config)],
    )
    assert cleared.exit_code == 0, cleared.output
    assert "default_team" not in linear_cli.load_config(config)
    with pytest.raises(linear_cli.typer.BadParameter, match="未设置 default_team"):
        linear_cli.select_team(None)
    assert resolved_keys == ["dcj"]


def test_auth_update_preserves_default_team(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    linear_cli.save_config({"default_team": "DCJ"}, config)
    monkeypatch.setattr(linear_cli.getpass, "getpass", lambda prompt: "oauth-token")

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "config",
            "set",
            "--config",
            str(config),
            "--auth-type",
            "oauth",
            "--prompt-token",
        ],
    )

    assert result.exit_code == 0, result.output
    assert linear_cli.load_config(config)["default_team"] == "DCJ"


def test_auth_repair_reuses_saved_key_and_persists_working_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    linear_cli.save_config(
        {"auth_type": "api-key", "token": "lin_api_saved-key"}, config
    )

    def identify(client: object) -> dict:
        if not client.client.transport.kwargs["headers"]["Authorization"].startswith(
            "Bearer "
        ):
            raise linear_cli.LinearError("unauthorized")
        return {
            "viewer": {"id": "me", "name": "Me"},
            "organization": {"id": "org", "name": "Workspace", "urlKey": "ws"},
        }

    monkeypatch.setattr(linear_cli, "read_identity", identify)
    result = CliRunner().invoke(
        linear_cli.app,
        ["auth", "repair", "--config", str(config)],
    )

    assert result.exit_code == 0, result.output
    assert "lin_api_saved-key" not in result.output
    assert linear_cli.load_config(config) == {
        "auth_type": "api-key-bearer",
        "token": "lin_api_saved-key",
    }


def test_team_automation_show_resolves_auto_close_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "query Team(" in query:
                return {
                    "teams": {
                        "nodes": [{"id": "team-id", "key": "DCJ", "name": "DCjanus"}]
                    }
                }
            assert variables == {"id": "team-id"}
            return {
                "team": {
                    "id": "team-id",
                    "key": "DCJ",
                    "name": "DCjanus",
                    "autoArchivePeriod": 6.0,
                    "autoClosePeriod": 6.0,
                    "autoCloseStateId": "canceled-id",
                    "autoCloseParentIssues": None,
                    "autoCloseChildIssues": None,
                    "states": {
                        "nodes": [
                            {"id": "done-id", "name": "Done", "type": "completed"},
                            {
                                "id": "canceled-id",
                                "name": "Canceled",
                                "type": "canceled",
                            },
                        ]
                    },
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app, ["team", "automation", "show", "--team", "DCJ"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["autoArchivePeriod"] == 6.0
    assert payload["autoCloseState"] == {
        "id": "canceled-id",
        "name": "Canceled",
        "type": "canceled",
    }


def test_team_automation_update_previews_periods_and_resolved_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "query Team(" in query:
                return {
                    "teams": {
                        "nodes": [{"id": "team-id", "key": "DCJ", "name": "DCjanus"}]
                    }
                }
            if "query TeamAutomations" in query:
                return {
                    "team": {
                        "id": "team-id",
                        "key": "DCJ",
                        "name": "DCjanus",
                        "autoArchivePeriod": 6.0,
                        "autoClosePeriod": 6.0,
                        "autoCloseStateId": "old-state",
                        "autoCloseParentIssues": None,
                        "autoCloseChildIssues": None,
                        "states": {
                            "nodes": [
                                {
                                    "id": "old-state",
                                    "name": "Canceled",
                                    "type": "canceled",
                                }
                            ]
                        },
                    }
                }
            if "query TeamStates" in query:
                return {
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "done-id", "name": "Done", "type": "completed"}
                            ]
                        }
                    }
                }
            raise AssertionError("preview must not call teamUpdate")

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app,
        [
            "team",
            "automation",
            "update",
            "--team",
            "DCJ",
            "--auto-archive-months",
            "12",
            "--auto-close-months",
            "3",
            "--auto-close-state",
            "Done",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["preview"] is True
    assert payload["input"] == {
        "autoArchivePeriod": 12.0,
        "autoClosePeriod": 3.0,
        "autoCloseStateId": "done-id",
    }


def test_team_automation_update_can_preview_disabling_automation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": team, "name": "DCjanus"},
    )
    monkeypatch.setattr(
        linear_cli,
        "read_team_automations",
        lambda client, team_id: {"id": team_id, "autoArchivePeriod": 6.0},
    )
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "team",
            "automation",
            "update",
            "--team",
            "DCJ",
            "--disable-auto-archive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["input"] == {"autoArchivePeriod": None}


def test_issue_get_reads_back_assignee(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert "assignee { id name email }" in query
            assert variables == {"id": "DCJ-93"}
            return {
                "issue": {
                    "id": "issue-id",
                    "identifier": "DCJ-93",
                    "assignee": {
                        "id": "user-id",
                        "name": "DCjanus",
                        "email": "dcjanus@example.com",
                    },
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(linear_cli.app, ["issue", "get", "DCJ-93"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["assignee"]["name"] == "DCjanus"


def test_issue_list_selects_requested_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict | None]] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            calls.append((query, variables))
            return {
                "issues": {
                    "nodes": [
                        {
                            "identifier": "DCJ-104",
                            "title": "校准身份契约",
                            "state": {"name": "Doing", "type": "started"},
                        }
                    ]
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "DCJ", "name": "DCjanus"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "DCJ")

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "list",
            "--fields",
            "identifier,title,state",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        {
            "identifier": "DCJ-104",
            "state": {"name": "Doing", "type": "started"},
            "title": "校准身份契约",
        }
    ]
    query, variables = calls[-1]
    assert "identifier title state { id name type }" in " ".join(query.split())
    assert "description" not in query
    assert variables == {"id": "team-id", "first": 100}


def test_issue_list_rejects_unknown_or_empty_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    runner = CliRunner()

    unknown = runner.invoke(
        linear_cli.app,
        ["issue", "list", "--team", "DCJ", "--fields", "identifier,secret"],
    )
    empty = runner.invoke(
        linear_cli.app,
        ["issue", "list", "--team", "DCJ", "--fields", " , "],
    )

    assert unknown.exit_code != 0
    assert "不支持的 Issue 字段：secret" in unknown.output
    assert empty.exit_code != 0
    assert "不能为空" in empty.output


def test_issue_create_and_update_read_description_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    description_file = tmp_path / "issue.md"
    description_file.write_text("## 目标\n\n- 保留 Markdown 结构\n", encoding="utf-8")
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "DCJ", "name": "DCjanus"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "DCJ")
    monkeypatch.setattr(
        linear_cli,
        "read_identity",
        lambda client: {"viewer": {"id": "viewer-id", "name": "DCjanus"}},
    )
    monkeypatch.setattr(
        linear_cli,
        "resolve_workflow_state",
        lambda client, team_id, state: {
            "id": "todo-id",
            "name": state,
            "type": "unstarted",
        },
    )
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {
            "id": "issue-id",
            "identifier": issue_id,
            "title": "旧标题",
        },
    )
    runner = CliRunner()

    created = runner.invoke(
        linear_cli.app,
        [
            "issue",
            "create",
            "--title",
            "新事项",
            "--description-file",
            str(description_file),
            "--no-due-date",
        ],
    )
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["input"]["description"] == (
        "## 目标\n\n- 保留 Markdown 结构"
    )

    updated = runner.invoke(
        linear_cli.app,
        [
            "issue",
            "update",
            "DCJ-101",
            "--description-file",
            str(description_file),
        ],
    )
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.output)["input"]["description"] == (
        "## 目标\n\n- 保留 Markdown 结构"
    )

    dated_update = runner.invoke(
        linear_cli.app,
        ["issue", "update", "DCJ-101", "--due-date", "2026-10-01"],
    )
    assert dated_update.exit_code == 0, dated_update.output
    assert json.loads(dated_update.output)["input"]["dueDate"] == "2026-10-01"

    invalid_update = runner.invoke(
        linear_cli.app,
        ["issue", "update", "DCJ-101", "--due-date", "2026-02-30"],
    )
    assert invalid_update.exit_code != 0


def test_issue_create_defaults_to_todo_and_requires_due_date_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "DCJ", "name": "DCjanus"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "DCJ")
    monkeypatch.setattr(
        linear_cli,
        "read_identity",
        lambda client: {"viewer": {"id": "viewer-id", "name": "DCjanus"}},
    )
    monkeypatch.setattr(
        linear_cli,
        "resolve_workflow_state",
        lambda client, team_id, state: {
            "id": "todo-id",
            "name": state,
            "type": "unstarted",
        },
    )
    runner = CliRunner()

    missing = runner.invoke(
        linear_cli.app,
        ["issue", "create", "--title", "新事项"],
    )
    assert missing.exit_code != 0
    with pytest.raises(
        linear_cli.typer.BadParameter,
        match="--due-date.*--no-due-date",
    ):
        linear_cli.validate_create_due_date(None, False)

    dated = runner.invoke(
        linear_cli.app,
        [
            "issue",
            "create",
            "--title",
            "新事项",
            "--due-date",
            "2026-09-30",
        ],
    )
    assert dated.exit_code == 0, dated.output
    assert json.loads(dated.output)["input"] == {
        "assigneeId": "viewer-id",
        "dueDate": "2026-09-30",
        "stateId": "todo-id",
        "teamId": "team-id",
        "title": "新事项",
    }

    undated = runner.invoke(
        linear_cli.app,
        ["issue", "create", "--title", "新事项", "--no-due-date"],
    )
    assert undated.exit_code == 0, undated.output
    assert "dueDate" not in json.loads(undated.output)["input"]

    conflicting = runner.invoke(
        linear_cli.app,
        [
            "issue",
            "create",
            "--title",
            "新事项",
            "--due-date",
            "2026-09-30",
            "--no-due-date",
        ],
    )
    assert conflicting.exit_code != 0
    with pytest.raises(linear_cli.typer.BadParameter, match="不能同时使用"):
        linear_cli.validate_create_due_date(
            datetime(2026, 9, 30, tzinfo=timezone.utc), True
        )

    invalid = runner.invoke(
        linear_cli.app,
        [
            "issue",
            "create",
            "--title",
            "新事项",
            "--due-date",
            "2026-02-30",
        ],
    )
    assert invalid.exit_code != 0

    help_result = runner.invoke(linear_cli.app, ["issue", "create", "--help"])
    assert help_result.exit_code == 0, help_result.output
    help_output = Text.from_ansi(help_result.output).plain
    assert "--due-date" in help_output
    assert "%Y-%m-%d" in help_output

    unassigned = runner.invoke(
        linear_cli.app,
        [
            "issue",
            "create",
            "--title",
            "新事项",
            "--no-due-date",
            "--no-assignee",
        ],
    )
    assert unassigned.exit_code == 0, unassigned.output
    assert "assigneeId" not in json.loads(unassigned.output)["input"]

    conflicting_assignee = runner.invoke(
        linear_cli.app,
        [
            "issue",
            "create",
            "--title",
            "新事项",
            "--no-due-date",
            "--assignee-id",
            "other-user-id",
            "--no-assignee",
        ],
    )
    assert conflicting_assignee.exit_code != 0
    with pytest.raises(linear_cli.typer.BadParameter, match="不能同时使用"):
        linear_cli.resolve_create_assignee(object(), "other-user-id", True)
    assert (
        linear_cli.resolve_create_assignee(object(), "other-user-id", False)
        == "other-user-id"
    )


def test_issue_description_inputs_are_mutually_exclusive(tmp_path: Path) -> None:
    description_file = tmp_path / "issue.md"
    description_file.write_text("正文", encoding="utf-8")

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "create",
            "--title",
            "新事项",
            "--description",
            "内联正文",
            "--description-file",
            str(description_file),
        ],
    )

    assert result.exit_code != 0
    assert "不能同时使用" in result.output


def test_label_lifecycle_previews_writes_and_reads_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = [
        {
            "id": "workspace-label",
            "name": "workspace:shared",
            "description": None,
            "color": "#000000",
            "createdAt": "2026-09-16T00:00:00Z",
            "updatedAt": "2026-09-16T00:00:00Z",
            "team": None,
        }
    ]

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "query IssueLabels" in query:
                return {"issueLabels": {"nodes": labels}}
            if "mutation CreateIssueLabel" in query:
                assert variables == {
                    "input": {
                        "name": "area:de",
                        "teamId": "team-id",
                        "description": "数字员工相关事项",
                        "color": "#5E6AD2",
                    }
                }
                labels.append(
                    {
                        "id": "label-id",
                        **variables["input"],
                        "createdAt": "2026-09-16T00:00:00Z",
                        "updatedAt": "2026-09-16T00:00:00Z",
                        "team": {"id": "team-id", "key": "DCJ", "name": "DCjanus"},
                    }
                )
                labels[-1].pop("teamId")
                return {
                    "issueLabelCreate": {
                        "success": True,
                        "issueLabel": {"id": "label-id"},
                    }
                }
            if "mutation UpdateIssueLabel" in query:
                assert variables == {
                    "id": "label-id",
                    "input": {
                        "name": "area:middleware-de",
                        "description": "数字员工能力建设",
                    },
                }
                labels[-1].update(variables["input"])
                return {
                    "issueLabelUpdate": {
                        "success": True,
                        "issueLabel": {"id": "label-id"},
                    }
                }
            if "mutation DeleteIssueLabel" in query:
                assert variables == {"id": "label-id"}
                labels.pop()
                return {"issueLabelDelete": {"success": True}}
            raise AssertionError(query)

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "DCJ", "name": "DCjanus"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "DCJ")
    runner = CliRunner()

    preview = runner.invoke(
        linear_cli.app,
        [
            "label",
            "create",
            "--name",
            "area:de",
            "--description",
            "数字员工相关事项",
            "--color",
            "#5E6AD2",
        ],
    )
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["preview"] is True
    assert len(labels) == 1

    created = runner.invoke(
        linear_cli.app,
        [
            "label",
            "create",
            "--name",
            "area:de",
            "--description",
            "数字员工相关事项",
            "--color",
            "#5E6AD2",
            "--yes",
        ],
    )
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["name"] == "area:de"

    listed = runner.invoke(linear_cli.app, ["label", "list"])
    assert listed.exit_code == 0, listed.output
    assert [label["name"] for label in json.loads(listed.output)] == [
        "workspace:shared",
        "area:de",
    ]

    update_preview = runner.invoke(
        linear_cli.app,
        [
            "label",
            "update",
            "area:de",
            "--name",
            "area:middleware-de",
            "--description",
            "数字员工能力建设",
        ],
    )
    assert update_preview.exit_code == 0, update_preview.output
    assert json.loads(update_preview.output)["input"] == {
        "name": "area:middleware-de",
        "description": "数字员工能力建设",
    }

    updated = runner.invoke(
        linear_cli.app,
        [
            "label",
            "update",
            "area:de",
            "--name",
            "area:middleware-de",
            "--description",
            "数字员工能力建设",
            "--yes",
        ],
    )
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.output)["description"] == "数字员工能力建设"

    delete_preview = runner.invoke(
        linear_cli.app, ["label", "delete", "area:middleware-de"]
    )
    assert delete_preview.exit_code == 0, delete_preview.output
    assert json.loads(delete_preview.output)["preview"] is True

    deleted = runner.invoke(
        linear_cli.app, ["label", "delete", "area:middleware-de", "--yes"]
    )
    assert deleted.exit_code == 0, deleted.output
    assert json.loads(deleted.output)["deleted"] is True
    assert [label["name"] for label in labels] == ["workspace:shared"]


def test_workflow_state_create_previews_writes_reads_back_and_rejects_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = [
        {
            "id": "backlog-id",
            "name": "Backlog",
            "type": "backlog",
            "color": "#bec2c8",
            "description": None,
            "position": 0.0,
            "team": {"id": "team-id", "key": "SD", "name": "Side"},
        }
    ]

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "query WorkflowStates" in query:
                return {"team": {"states": {"nodes": states}}}
            if "mutation CreateWorkflowState" in query:
                assert variables == {
                    "input": {
                        "name": "Idea",
                        "type": "backlog",
                        "teamId": "team-id",
                        "color": "#95a2b3",
                        "description": "尚未承诺的想法和调研",
                    }
                }
                states.append(
                    {
                        "id": "idea-id",
                        "name": "Idea",
                        "type": "backlog",
                        "color": "#95a2b3",
                        "description": "尚未承诺的想法和调研",
                        "position": 1.0,
                        "team": {"id": "team-id", "key": "SD", "name": "Side"},
                    }
                )
                return {
                    "workflowStateCreate": {
                        "success": True,
                        "workflowState": {"id": "idea-id"},
                    }
                }
            raise AssertionError(query)

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "SD", "name": "Side"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "SD")
    runner = CliRunner()
    arguments = [
        "workflow-state",
        "create",
        "--name",
        "Idea",
        "--type",
        "backlog",
        "--description",
        "尚未承诺的想法和调研",
    ]

    preview = runner.invoke(linear_cli.app, arguments)
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output) == {
        "action": "workflowStateCreate",
        "input": {
            "name": "Idea",
            "type": "backlog",
            "teamId": "team-id",
            "color": "#95a2b3",
            "description": "尚未承诺的想法和调研",
        },
        "preview": True,
    }
    assert len(states) == 1

    created = runner.invoke(linear_cli.app, [*arguments, "--yes"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["id"] == "idea-id"

    listed = runner.invoke(linear_cli.app, ["workflow-state", "list"])
    assert listed.exit_code == 0, listed.output
    assert [state["name"] for state in json.loads(listed.output)] == [
        "Backlog",
        "Idea",
    ]

    duplicate = runner.invoke(linear_cli.app, arguments)
    assert duplicate.exit_code != 0
    assert isinstance(duplicate.exception, linear_cli.LinearError)
    assert "已存在于 Team SD" in str(duplicate.exception)


def test_workflow_state_update_previews_writes_and_reads_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "id": "backlog-id",
        "name": "Backlog",
        "type": "backlog",
        "color": "#bec2c8",
        "description": None,
        "position": 0.0,
        "team": {"id": "team-id", "key": "SD", "name": "Side"},
    }

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "query WorkflowStates" in query:
                return {"team": {"states": {"nodes": [state]}}}
            if "mutation UpdateWorkflowState" in query:
                assert variables == {
                    "id": "backlog-id",
                    "input": {"description": "已记录但尚未排期的候选事项。"},
                }
                state.update(variables["input"])
                return {
                    "workflowStateUpdate": {
                        "success": True,
                        "workflowState": {"id": "backlog-id"},
                    }
                }
            raise AssertionError(query)

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "SD", "name": "Side"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "SD")
    runner = CliRunner()
    arguments = [
        "workflow-state",
        "update",
        "Backlog",
        "--description",
        "已记录但尚未排期的候选事项。",
    ]

    preview = runner.invoke(linear_cli.app, arguments)
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["input"] == {
        "description": "已记录但尚未排期的候选事项。"
    }
    assert state["description"] is None

    updated = runner.invoke(linear_cli.app, [*arguments, "--yes"])
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.output)["description"] == "已记录但尚未排期的候选事项。"


def test_workflow_state_update_rejects_conflicting_description_options() -> None:
    result = CliRunner().invoke(
        linear_cli.app,
        [
            "workflow-state",
            "update",
            "Backlog",
            "--description",
            "候选事项",
            "--clear-description",
        ],
    )

    assert result.exit_code != 0
    assert "不能同时使用" in result.output


def test_workflow_state_update_rejects_reserved_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "SD", "name": "Side"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "SD")
    monkeypatch.setattr(
        linear_cli,
        "resolve_workflow_state",
        lambda client, team_id, state: {
            "id": "duplicate-id",
            "name": "Duplicate",
            "type": "duplicate",
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "workflow-state",
            "update",
            "Duplicate",
            "--description",
            "重复事项",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, linear_cli.LinearError)
    assert "保留的 Duplicate" in str(result.exception)


def test_label_create_supports_workspace_scope_and_rejects_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[dict] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "query IssueLabels" in query:
                return {"issueLabels": {"nodes": labels}}
            if "mutation CreateIssueLabel" in query:
                assert variables == {
                    "input": {
                        "name": "draft",
                        "description": "Issue 尚未稳定",
                        "color": "#95a2b3",
                    }
                }
                labels.append(
                    {
                        "id": "draft-id",
                        **variables["input"],
                        "createdAt": "2026-09-17T00:00:00Z",
                        "updatedAt": "2026-09-17T00:00:00Z",
                        "team": None,
                    }
                )
                return {
                    "issueLabelCreate": {
                        "success": True,
                        "issueLabel": {"id": "draft-id"},
                    }
                }
            raise AssertionError(query)

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    runner = CliRunner()
    arguments = [
        "label",
        "create",
        "--workspace",
        "--name",
        "draft",
        "--description",
        "Issue 尚未稳定",
        "--color",
        "#95a2b3",
    ]

    preview = runner.invoke(linear_cli.app, arguments)
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["input"] == {
        "name": "draft",
        "description": "Issue 尚未稳定",
        "color": "#95a2b3",
    }
    assert labels == []

    created = runner.invoke(linear_cli.app, [*arguments, "--yes"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["team"] is None

    duplicate = runner.invoke(linear_cli.app, arguments)
    assert duplicate.exit_code != 0
    assert isinstance(duplicate.exception, linear_cli.LinearError)
    assert "已存在于 workspace" in str(duplicate.exception)

    conflicting_scope = runner.invoke(linear_cli.app, [*arguments, "--team", "SD"])
    assert conflicting_scope.exit_code != 0
    assert "不能同时使用" in conflicting_scope.output


def test_label_update_can_clear_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda client, team: {"id": "team-id", "key": "DCJ", "name": "DCjanus"},
    )
    monkeypatch.setattr(linear_cli, "select_team", lambda team: team or "DCJ")
    monkeypatch.setattr(
        linear_cli,
        "resolve_label",
        lambda client, label, team_id: {
            "id": "label-id",
            "name": "area:de",
            "description": "旧描述",
            "team": {"id": "team-id"},
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["label", "update", "area:de", "--clear-description"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["input"] == {"description": None}


def test_issue_search_uses_native_full_text_with_strict_team_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict | None]] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            calls.append((query, variables))
            if "query Team(" in query:
                return {
                    "teams": {
                        "nodes": [{"id": "team-id", "key": "DCJ", "name": "DCjanus"}]
                    }
                }
            assert "searchIssues(" in query
            return {
                "searchIssues": {
                    "totalCount": 1,
                    "pageInfo": {"hasNextPage": False, "endCursor": "cursor-1"},
                    "nodes": [
                        {
                            "id": "issue-id",
                            "identifier": "DCJ-71",
                            "title": "Grafana URL",
                        }
                    ],
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "search",
            "  monitorUri Grafana  ",
            "--team",
            "DCJ",
            "--first",
            "25",
            "--after",
            "cursor-0",
            "--include-archived",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totalCount"] == 1
    assert payload["nodes"][0]["identifier"] == "DCJ-71"
    search_query, variables = calls[-1]
    assert "$filter: IssueFilter" in search_query
    assert variables == {
        "term": "monitorUri Grafana",
        "filter": {"team": {"id": {"eq": "team-id"}}},
        "first": 25,
        "after": "cursor-0",
        "includeComments": True,
        "includeArchived": True,
    }


def test_issue_search_can_exclude_comments_and_rejects_blank_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict | None] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "query Team(" in query:
                return {
                    "teams": {
                        "nodes": [{"id": "team-id", "key": "DCJ", "name": "DCjanus"}]
                    }
                }
            calls.append(variables)
            return {
                "searchIssues": {
                    "totalCount": 0,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    runner = CliRunner()
    result = runner.invoke(
        linear_cli.app,
        ["issue", "search", "Grafana", "--team", "DCJ", "--no-include-comments"],
    )
    assert result.exit_code == 0, result.output
    assert calls[-1]["includeComments"] is False

    rejected = runner.invoke(
        linear_cli.app, ["issue", "search", "   ", "--team", "DCJ"]
    )
    assert rejected.exit_code != 0
    assert "搜索词不能为空" in rejected.output


def test_api_graphql_executes_query_from_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    query_file = tmp_path / "query.graphql"
    query_file.write_text(
        "query Search($term: String!) { searchIssues(term: $term) { totalCount } }"
    )
    variables_file = tmp_path / "variables.json"
    variables_file.write_text(json.dumps({"term": "Grafana"}))
    calls: list[tuple[str, dict | None]] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            calls.append((query, variables))
            return {"searchIssues": {"totalCount": 2}}

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app,
        [
            "api",
            "graphql",
            str(query_file),
            "--variables-file",
            str(variables_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"searchIssues": {"totalCount": 2}}
    assert calls == [(query_file.read_text(), {"term": "Grafana"})]


def test_api_graphql_requires_double_confirmation_for_mutations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    query_file = tmp_path / "mutation.graphql"
    query_file.write_text(
        "mutation Update($id: String!) { issueUpdate(id: $id, input: {}) { success } }"
    )
    variables_file = tmp_path / "variables.json"
    variables_file.write_text(json.dumps({"id": "DCJ-71"}))
    calls: list[dict | None] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            calls.append(variables)
            return {"issueUpdate": {"success": True}}

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    runner = CliRunner()
    with pytest.raises(
        linear_cli.typer.BadParameter,
        match="必须同时提供 --allow-mutation 和 --yes",
    ):
        linear_cli.api_graphql(
            query_file,
            variables_file,
            linear_cli.DEFAULT_ENDPOINT,
            False,
            False,
        )
    assert not calls

    accepted = runner.invoke(
        linear_cli.app,
        [
            "api",
            "graphql",
            str(query_file),
            "--variables-file",
            str(variables_file),
            "--allow-mutation",
            "--yes",
        ],
    )
    assert accepted.exit_code == 0, accepted.output
    assert calls == [{"id": "DCJ-71"}]


def test_api_graphql_rejects_multiple_operations_and_non_object_variables(
    tmp_path: Path,
) -> None:
    multiple = tmp_path / "multiple.graphql"
    multiple.write_text("query One { viewer { id } } query Two { viewer { name } }")
    runner = CliRunner()
    rejected_multiple = runner.invoke(linear_cli.app, ["api", "graphql", str(multiple)])
    assert rejected_multiple.exit_code != 0
    assert "只能包含一个 operation" in rejected_multiple.output

    query_file = tmp_path / "query.graphql"
    query_file.write_text("query Viewer { viewer { id } }")
    variables_file = tmp_path / "variables.json"
    variables_file.write_text("[]")
    rejected_variables = runner.invoke(
        linear_cli.app,
        [
            "api",
            "graphql",
            str(query_file),
            "--variables-file",
            str(variables_file),
        ],
    )
    assert rejected_variables.exit_code != 0
    assert "顶层必须是 object" in rejected_variables.output


def test_team_automation_update_writes_and_reads_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutation_calls: list[dict] = []

    class MutationClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            mutation_calls.append(variables or {})
            return {"teamUpdate": {"success": True, "team": {"id": "team-id"}}}

    mutation_client = MutationClient()
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: mutation_client)
    monkeypatch.setattr(
        linear_cli,
        "resolve_team",
        lambda selected, team: {"id": "team-id", "key": team, "name": "DCjanus"},
    )
    readings = iter(
        [
            {"id": "team-id", "autoArchivePeriod": 6.0},
            {"id": "team-id", "autoArchivePeriod": 12.0},
        ]
    )
    monkeypatch.setattr(
        linear_cli,
        "read_team_automations",
        lambda selected, team_id: next(readings),
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "team",
            "automation",
            "update",
            "--team",
            "DCJ",
            "--auto-archive-months",
            "12",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert mutation_calls == [{"id": "team-id", "input": {"autoArchivePeriod": 12.0}}]
    assert json.loads(result.output)["autoArchivePeriod"] == 12.0


def test_team_automation_update_rejects_conflicting_archive_options() -> None:
    result = CliRunner().invoke(
        linear_cli.app,
        [
            "team",
            "automation",
            "update",
            "--team",
            "DCJ",
            "--auto-archive-months",
            "6",
            "--disable-auto-archive",
        ],
    )

    assert result.exit_code != 0
    assert "不能同时使用" in result.output


def test_view_create_preview_is_generic_and_non_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            raise AssertionError("preview must not call GraphQL")

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app,
        [
            "view",
            "create",
            "--name",
            "My work",
            "--filter-json",
            '{"assignee":{"id":{"eq":"me"}}}',
            "--team-id",
            "team-id",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "action": "customViewCreate",
        "input": {
            "filterData": {"assignee": {"id": {"eq": "me"}}},
            "name": "My work",
            "shared": False,
            "teamId": "team-id",
        },
        "preview": True,
    }


def test_comment_list_returns_comments_in_chronological_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert variables == {"id": "issue-id", "first": 25}
            return {
                "issue": {
                    "id": "issue-id",
                    "identifier": "DCJ-77",
                    "comments": {
                        "nodes": [
                            {"id": "new", "createdAt": "2026-09-16T02:00:00Z"},
                            {"id": "old", "createdAt": "2026-09-16T01:00:00Z"},
                        ]
                    },
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {"id": "issue-id", "identifier": "DCJ-77"},
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["issue", "comment", "list", "DCJ-77", "--first", "25"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["issue"]["identifier"] == "DCJ-77"
    assert [comment["id"] for comment in payload["comments"]] == ["old", "new"]


def test_comment_create_previews_file_body_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-id")
    body_file = tmp_path / "comment.md"
    body_file.write_text("阶段结论\n", encoding="utf-8")

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            raise AssertionError("preview must not call commentCreate")

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {
            "id": "issue-id",
            "identifier": "DCJ-77",
            "title": "AIDE",
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "comment",
            "create",
            "DCJ-77",
            "--body-file",
            str(body_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "action": "commentCreate",
        "input": {
            "body": (
                "阶段结论\n\n---\n\n+++ 在 Codex 中继续\n\n"
                "```sh\ncodex resume thread-id\n```\n\n+++"
            ),
            "issueId": "issue-id",
        },
        "issue": {"id": "issue-id", "identifier": "DCJ-77", "title": "AIDE"},
        "preview": True,
    }


def test_comment_create_can_disable_codex_resume_footer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-id")
    body_file = tmp_path / "comment.md"
    body_file.write_text("阶段结论\n", encoding="utf-8")

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            raise AssertionError("preview must not call commentCreate")

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {
            "id": "issue-id",
            "identifier": "DCJ-77",
            "title": "AIDE",
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "comment",
            "create",
            "DCJ-77",
            "--body-file",
            str(body_file),
            "--no-codex-resume",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["input"]["body"] == "阶段结论"


def test_comment_create_without_codex_thread_id_keeps_body_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    body_file = tmp_path / "comment.md"
    body_file.write_text("阶段结论\n", encoding="utf-8")

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {
            "id": "issue-id",
            "identifier": "DCJ-77",
            "title": "AIDE",
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "comment",
            "create",
            "DCJ-77",
            "--body-file",
            str(body_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["input"]["body"] == "阶段结论"


def test_comment_create_does_not_duplicate_existing_codex_resume_footer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-id")
    body = (
        "阶段结论\n\n---\n\n+++ 在 Codex 中继续\n\n"
        "```sh\ncodex resume thread-id\n```\n\n+++"
    )
    body_file = tmp_path / "comment.md"
    body_file.write_text(body, encoding="utf-8")

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {
            "id": "issue-id",
            "identifier": "DCJ-77",
            "title": "AIDE",
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "comment",
            "create",
            "DCJ-77",
            "--body-file",
            str(body_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["input"]["body"] == body


def test_comment_create_writes_and_reads_back_comment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-id")
    body_file = tmp_path / "comment.md"
    body_file.write_text("最终结论", encoding="utf-8")
    expected_body = (
        "最终结论\n\n---\n\n+++ 在 Codex 中继续\n\n"
        "```sh\ncodex resume thread-id\n```\n\n+++"
    )

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert variables == {
                "input": {"issueId": "issue-id", "body": expected_body}
            }
            return {
                "commentCreate": {
                    "success": True,
                    "comment": {"id": "comment-id"},
                }
            }

    client = StubClient()
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: client)
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda selected, issue_id: {
            "id": "issue-id",
            "identifier": "DCJ-77",
            "title": "AIDE",
        },
    )
    monkeypatch.setattr(
        linear_cli,
        "read_comment",
        lambda selected, comment_id: {"id": comment_id, "body": "最终结论"},
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "comment",
            "create",
            "DCJ-77",
            "--body-file",
            str(body_file),
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["comment"] == {"id": "comment-id", "body": "最终结论"}


def test_comment_create_rejects_empty_body_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body_file = tmp_path / "comment.md"
    body_file.write_text("\n", encoding="utf-8")
    monkeypatch.setattr(
        linear_cli,
        "get_client",
        lambda endpoint: pytest.fail("empty body must fail before network"),
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "issue",
            "comment",
            "create",
            "DCJ-77",
            "--body-file",
            str(body_file),
        ],
    )

    assert result.exit_code != 0
    assert "内容不能为空" in result.output


def test_comment_delete_previews_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            raise AssertionError("preview must not call commentDelete")

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_comment",
        lambda client, comment_id: {
            "id": comment_id,
            "body": "稳定约定",
            "createdAt": "2026-09-21T10:20:15Z",
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["issue", "comment", "delete", "comment-id"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "action": "commentDelete",
        "before": {
            "id": "comment-id",
            "body": "稳定约定",
            "createdAt": "2026-09-21T10:20:15Z",
        },
        "preview": True,
    }


def test_comment_delete_writes_and_confirms_comment_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict | None]] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            calls.append((query, variables))
            if "mutation DeleteComment" in query:
                return {"commentDelete": {"success": True}}
            if "query Comment" in query:
                return {"comment": None}
            raise AssertionError(query)

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_comment",
        lambda client, comment_id: {"id": comment_id, "body": "稳定约定"},
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["issue", "comment", "delete", "comment-id", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "deleted": True,
        "comment": {"id": "comment-id", "body": "稳定约定"},
    }
    assert [variables for _, variables in calls] == [
        {"id": "comment-id"},
        {"id": "comment-id"},
    ]


def test_comment_delete_accepts_linear_not_found_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "mutation DeleteComment" in query:
                return {"commentDelete": {"success": True}}
            if "query Comment" in query:
                raise linear_cli.LinearError(
                    "Linear GraphQL 请求失败：Entity not found: Comment"
                )
            raise AssertionError(query)

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_comment",
        lambda client, comment_id: {"id": comment_id, "body": "稳定约定"},
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["issue", "comment", "delete", "comment-id", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["deleted"] is True


@pytest.mark.parametrize(
    ("command", "operation"),
    [("archive", "issueArchive"), ("restore", "issueUnarchive")],
)
def test_issue_lifecycle_write_reads_back(
    monkeypatch: pytest.MonkeyPatch, command: str, operation: str
) -> None:
    calls: list[dict] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            calls.append(variables or {})
            return {operation: {"success": True}}

    client = StubClient()
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: client)
    readings = iter(
        [
            {"id": "issue-id", "identifier": "DCJ-77", "archivedAt": None},
            {
                "id": "issue-id",
                "identifier": "DCJ-77",
                "archivedAt": "2026-09-16T00:00:00Z" if command == "archive" else None,
            },
        ]
    )
    monkeypatch.setattr(
        linear_cli, "read_issue", lambda selected, issue_id: next(readings)
    )

    result = CliRunner().invoke(linear_cli.app, ["issue", command, "DCJ-77", "--yes"])

    assert result.exit_code == 0, result.output
    assert calls == [{"id": "issue-id"}]
    assert json.loads(result.output)["identifier"] == "DCJ-77"


def test_issue_delete_is_recoverable_and_does_not_read_deleted_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert variables == {"id": "issue-id", "permanentlyDelete": False}
            return {"issueDelete": {"success": True}}

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {"id": "issue-id", "identifier": "DCJ-77"},
    )

    result = CliRunner().invoke(linear_cli.app, ["issue", "delete", "DCJ-77", "--yes"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["deleted"] is True
    assert payload["permanent"] is False
    assert payload["recoverableForDays"] == 30


def test_issue_delete_can_permanently_delete_with_explicit_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert variables == {"id": "issue-id", "permanentlyDelete": True}
            return {"issueDelete": {"success": True}}

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_issue",
        lambda client, issue_id: {"id": "issue-id", "identifier": "DCJ-77"},
    )

    result = CliRunner().invoke(
        linear_cli.app,
        ["issue", "delete", "DCJ-77", "--permanent", "--yes"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["deleted"] is True
    assert payload["permanent"] is True
    assert payload["recoverableForDays"] == 0


def test_view_issues_returns_matching_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert variables == {"id": "view-id", "first": 25}
            return {
                "customView": {
                    "id": "view-id",
                    "name": "Now",
                    "modelName": "Issue",
                    "issues": {"nodes": [{"id": "issue-id", "identifier": "DCJ-1"}]},
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app,
        ["view", "issues", "view-id", "--first", "25"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "Now"
    assert payload["issues"][0]["identifier"] == "DCJ-1"


def test_view_preferences_get_returns_explicit_and_effective_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            if "ViewPreferenceSchema" in query:
                assert variables is None
                return {
                    "__type": {
                        "fields": [
                            {
                                "name": "fieldDueDate",
                                "type": {
                                    "kind": "SCALAR",
                                    "name": "Boolean",
                                    "ofType": None,
                                },
                            },
                            {
                                "name": "issueGrouping",
                                "type": {
                                    "kind": "SCALAR",
                                    "name": "String",
                                    "ofType": None,
                                },
                            },
                        ]
                    }
                }
            assert "ViewPreferences" in query
            assert variables == {"id": "view-id"}
            return {
                "customView": {
                    "id": "view-id",
                    "slugId": "recent",
                    "name": "近期完成",
                    "modelName": "Issue",
                    "userViewPreferences": {
                        "id": "preference-id",
                        "type": "user",
                        "viewType": "customView",
                        "preferences": {
                            "fieldDueDate": False,
                            "issueGrouping": None,
                        },
                    },
                    "viewPreferencesValues": {
                        "fieldDueDate": False,
                        "issueGrouping": "workflowState",
                    },
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app, ["view", "preferences", "get", "view-id"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["preferenceId"] == "preference-id"
    assert payload["explicit"] == {"fieldDueDate": False}
    assert payload["effective"] == {
        "fieldDueDate": False,
        "issueGrouping": "workflowState",
    }


def test_view_preferences_update_previews_merged_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        linear_cli,
        "get_client",
        lambda endpoint: object(),
    )
    monkeypatch.setattr(
        linear_cli,
        "read_view_preference_schema",
        lambda client: {
            "closedIssuesOrderedByRecency": "Boolean",
            "fieldDueDate": "Boolean",
            "issueGrouping": "String",
        },
    )
    monkeypatch.setattr(
        linear_cli,
        "read_view_preferences",
        lambda client, view_id, schema: {
            "view": {"id": "view-id", "name": "近期完成"},
            "preferenceId": "preference-id",
            "explicit": {"issueGrouping": "workflowState"},
            "effective": {},
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "view",
            "preferences",
            "update",
            "view-id",
            "--set",
            "fieldDueDate=false",
            "--set",
            "closedIssuesOrderedByRecency=true",
            "--set",
            "issueGrouping=null",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["action"] == "viewPreferencesUpdate"
    assert payload["before"] == {"issueGrouping": "workflowState"}
    assert payload["after"] == {
        "closedIssuesOrderedByRecency": True,
        "fieldDueDate": False,
    }
    assert payload["preview"] is True


def test_view_preferences_update_writes_full_merged_object_and_reads_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutation_calls: list[dict] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert "UpdateViewPreferences" in query
            mutation_calls.append(variables or {})
            return {
                "viewPreferencesUpdate": {
                    "success": True,
                    "viewPreferences": {"id": "preference-id"},
                }
            }

    client = StubClient()
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: client)
    monkeypatch.setattr(
        linear_cli,
        "read_view_preference_schema",
        lambda selected: {
            "fieldDueDate": "Boolean",
            "issueGrouping": "String",
        },
    )
    readings = iter(
        [
            {
                "view": {"id": "view-id", "name": "近期完成"},
                "preferenceId": "preference-id",
                "explicit": {"issueGrouping": "workflowState"},
                "effective": {},
            },
            {
                "view": {"id": "view-id", "name": "近期完成"},
                "preferenceId": "preference-id",
                "explicit": {
                    "fieldDueDate": False,
                    "issueGrouping": "workflowState",
                },
                "effective": {
                    "fieldDueDate": False,
                    "issueGrouping": "workflowState",
                },
            },
        ]
    )
    monkeypatch.setattr(
        linear_cli,
        "read_view_preferences",
        lambda selected, view_id, schema: next(readings),
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "view",
            "preferences",
            "update",
            "view-id",
            "--set",
            "fieldDueDate=false",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert mutation_calls == [
        {
            "id": "preference-id",
            "input": {
                "preferences": {
                    "fieldDueDate": False,
                    "issueGrouping": "workflowState",
                }
            },
        }
    ]
    assert json.loads(result.output)["explicit"]["fieldDueDate"] is False


def test_view_preferences_update_creates_missing_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutation_calls: list[dict] = []

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert "CreateViewPreferences" in query
            mutation_calls.append(variables or {})
            return {
                "viewPreferencesCreate": {
                    "success": True,
                    "viewPreferences": {"id": "new-preference-id"},
                }
            }

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    monkeypatch.setattr(
        linear_cli,
        "read_view_preference_schema",
        lambda client: {"fieldDueDate": "Boolean", "issueGrouping": "String"},
    )
    readings = iter(
        [
            {
                "view": {"id": "view-id", "name": "近期完成"},
                "preferenceId": None,
                "explicit": {},
                "effective": {},
            },
            {
                "view": {"id": "view-id", "name": "近期完成"},
                "preferenceId": "new-preference-id",
                "explicit": {"fieldDueDate": False},
                "effective": {"fieldDueDate": False},
            },
        ]
    )
    monkeypatch.setattr(
        linear_cli,
        "read_view_preferences",
        lambda client, view_id, schema: next(readings),
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "view",
            "preferences",
            "update",
            "view-id",
            "--set",
            "fieldDueDate=false",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert mutation_calls == [
        {
            "input": {
                "type": "user",
                "viewType": "customView",
                "customViewId": "view-id",
                "preferences": {"fieldDueDate": False},
            }
        }
    ]


def test_view_preferences_update_patch_file_then_set_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_file = tmp_path / "preferences.json"
    patch_file.write_text(
        '{"fieldDueDate": true, "issueGrouping": "assignee"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "read_view_preference_schema",
        lambda client: {"fieldDueDate": "Boolean", "issueGrouping": "String"},
    )
    monkeypatch.setattr(
        linear_cli,
        "read_view_preferences",
        lambda client, view_id, schema: {
            "view": {"id": "view-id"},
            "preferenceId": "preference-id",
            "explicit": {},
            "effective": {},
        },
    )

    result = CliRunner().invoke(
        linear_cli.app,
        [
            "view",
            "preferences",
            "update",
            "view-id",
            "--patch-file",
            str(patch_file),
            "--set",
            "fieldDueDate=false",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["patch"] == {
        "fieldDueDate": False,
        "issueGrouping": "assignee",
    }


def test_view_preferences_update_rejects_unknown_or_wrong_typed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: object())
    monkeypatch.setattr(
        linear_cli,
        "read_view_preference_schema",
        lambda client: {"fieldDueDate": "Boolean"},
    )

    unknown = CliRunner().invoke(
        linear_cli.app,
        ["view", "preferences", "update", "view-id", "--set", "typo=true"],
    )
    wrong_type = CliRunner().invoke(
        linear_cli.app,
        [
            "view",
            "preferences",
            "update",
            "view-id",
            "--set",
            'fieldDueDate="false"',
        ],
    )

    assert unknown.exit_code != 0
    assert "未知 View preference" in unknown.output
    assert wrong_type.exit_code != 0
    assert "需要 Boolean" in wrong_type.output


def test_view_update_rejects_invalid_filter_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            return {"customView": {"id": "view-id", "name": "Before"}}

    monkeypatch.setattr(linear_cli, "get_client", lambda endpoint: StubClient())
    result = CliRunner().invoke(
        linear_cli.app,
        ["view", "update", "view-id", "--filter-json", "[]"],
    )
    assert result.exit_code != 0
    assert "JSON object" in result.output

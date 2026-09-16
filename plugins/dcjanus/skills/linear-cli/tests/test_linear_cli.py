from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import httpx2 as httpx
import pytest
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

    api = runner.invoke(linear_cli.app, ["api", "--help"])
    assert api.exit_code == 0, api.output
    assert "graphql" in api.output


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
        "input": {"body": "阶段结论", "issueId": "issue-id"},
        "issue": {"id": "issue-id", "identifier": "DCJ-77", "title": "AIDE"},
        "preview": True,
    }


def test_comment_create_writes_and_reads_back_comment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body_file = tmp_path / "comment.md"
    body_file.write_text("最终结论", encoding="utf-8")

    class StubClient:
        def query(self, query: str, variables: dict | None = None) -> dict:
            assert variables == {"input": {"issueId": "issue-id", "body": "最终结论"}}
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

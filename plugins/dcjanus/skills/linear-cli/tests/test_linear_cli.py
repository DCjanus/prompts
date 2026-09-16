from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import httpx
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


def test_api_key_auth_and_graphql_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "lin_api_key"
        return response({"data": {"viewer": {"id": "me"}}})

    client = linear_cli.LinearClient(
        linear_cli.Settings("https://linear.test/graphql", "lin_api_key", False),
        transport=httpx.MockTransport(handler),
    )
    assert client.query("query")["viewer"]["id"] == "me"

    broken = linear_cli.LinearClient(
        linear_cli.Settings("https://linear.test/graphql", "key", False),
        transport=httpx.MockTransport(
            lambda request: response(
                {"data": {"issue": None}, "errors": [{"message": "denied"}]}
            )
        ),
    )
    with pytest.raises(linear_cli.LinearError, match="denied"):
        broken.query("query")


def test_oauth_uses_bearer_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer oauth-token"
        return response({"data": {"viewer": {"id": "me"}}})

    client = linear_cli.LinearClient(
        linear_cli.Settings("https://linear.test/graphql", "oauth-token", True),
        transport=httpx.MockTransport(handler),
    )
    assert client.query("query")["viewer"]["id"] == "me"


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

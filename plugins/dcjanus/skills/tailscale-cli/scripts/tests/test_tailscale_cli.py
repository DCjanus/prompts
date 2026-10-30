"""验证 CLI 对官方 API 的请求契约、发布边界与错误结果。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs

import httpx2
import pytest
from rich.text import Text
from typer.testing import CliRunner

SCRIPT = Path(__file__).resolve().parents[1] / "tailscale_cli.py"
SPEC = importlib.util.spec_from_file_location("tailscale_cli", SCRIPT)
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cli
SPEC.loader.exec_module(cli)
ORIGINAL_CLIENT = httpx2.Client
CURRENT = b'// Keep this comment\n{"grants": [], "ssh": [],}\n'
CANDIDATE = b'// Keep this comment\n{"grants": [], "ssh": [], "groups": {},}\n'
ACL_PATH = "/api/v2/tailnet/example.com/acl"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name in ("TS_API_KEY", "TS_CLIENT_ID", "TS_CLIENT_SECRET", "TS_TAILNET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("TS_API_KEY", "test-api-secret")
    monkeypatch.setenv("TS_TAILNET", "example.com")

    def no_network(request):
        pytest.fail(f"意外请求：{request.method} {request.url.path}")

    monkeypatch.setattr(
        cli.httpx2,
        "Client",
        lambda **kw: ORIGINAL_CLIENT(transport=httpx2.MockTransport(no_network), **kw),
    )


@pytest.fixture
def policy_file(tmp_path):
    path = tmp_path / "candidate.hujson"
    path.write_bytes(CANDIDATE)
    return path


def mock_api(monkeypatch, handler):
    """记录真实客户端构建的请求，并交给模拟服务器。"""
    requests = []

    def respond(request):
        assert request.url.host == "api.tailscale.com"
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(
        cli.httpx2,
        "Client",
        lambda **kw: ORIGINAL_CLIENT(transport=httpx2.MockTransport(respond), **kw),
    )
    return requests


def invoke(*args):
    return CliRunner().invoke(cli.app, ["--json", "policy", *map(str, args)])


def test_get_preserves_hujson_and_etag_without_overwrite(monkeypatch, tmp_path):
    def respond(request):
        assert request.method == "GET" and request.url.path == ACL_PATH
        assert request.headers["Accept"] == "application/hujson"
        assert request.headers["Authorization"] == "Bearer test-api-secret"
        return httpx2.Response(200, content=CURRENT, headers={"ETag": '"v1"'})

    mock_api(monkeypatch, respond)
    output = tmp_path / "current.hujson"
    result = invoke("get", "--output", output)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["etag"] == '"v1"'
    assert output.read_bytes() == CURRENT
    assert invoke("get", "--output", output).exit_code == 1
    assert output.read_bytes() == CURRENT


@pytest.mark.parametrize(
    "kind,target", [("user", "alice@example.com"), ("ipport", "100.100.100.100:22")]
)
def test_preview_uses_official_query_parameters(monkeypatch, policy_file, kind, target):
    def respond(request):
        assert request.method == "POST" and request.url.path == ACL_PATH + "/preview"
        assert dict(request.url.params) == {"type": kind, "previewFor": target}
        assert request.content == CANDIDATE
        assert request.headers["Content-Type"] == "application/hujson"
        return httpx2.Response(
            200, json={"matches": [], "type": kind, "previewFor": target}
        )

    mock_api(monkeypatch, respond)
    result = invoke("preview", policy_file, "--type", kind, "--for", target)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["previewFor"] == target


@pytest.mark.parametrize(
    "validation",
    [
        {},
        None,
        {"message": "warning(s) found", "data": [{"warnings": ["group ignored"]}]},
    ],
)
def test_validate_accepts_empty_success_and_reports_warnings(
    monkeypatch, policy_file, validation
):
    mock_api(
        monkeypatch,
        lambda req: (
            httpx2.Response(200, json=validation)
            if validation is not None
            else httpx2.Response(200)
        ),
    )
    result = invoke("validate", policy_file)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["validation"] == (validation or {})


@pytest.mark.parametrize("execute", [False, True])
def test_apply_defaults_to_dry_run_and_verifies_executed_write(
    monkeypatch, policy_file, execute
):
    writes = []

    def respond(request):
        if request.method == "GET":
            return httpx2.Response(
                200,
                content=CANDIDATE if writes else CURRENT,
                headers={"ETag": '"v2"' if writes else '"v1"'},
            )
        if request.url.path.endswith("/validate"):
            assert request.content == CANDIDATE
            return httpx2.Response(200, json={})
        assert request.url.path == ACL_PATH
        assert request.headers["If-Match"] == '"v1"'
        assert request.content == CANDIDATE
        writes.append(request)
        return httpx2.Response(200, content=CANDIDATE, headers={"ETag": '"v2"'})

    requests = mock_api(monkeypatch, respond)
    args = ["apply", policy_file, "--if-match", '"v1"']
    if execute:
        args.append("--execute")
    result = invoke(*args)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["applied"] is execute
    assert '"groups"' in payload["diff"]
    assert len(requests) == (4 if execute else 2)
    assert len(writes) == int(execute)
    if execute:
        assert payload["verified"] is True and payload["etag"] == '"v2"'


def test_unchanged_policy_is_not_republished(monkeypatch, policy_file):
    requests = mock_api(
        monkeypatch,
        lambda req: (
            httpx2.Response(200, content=CANDIDATE, headers={"ETag": '"v1"'})
            if req.method == "GET"
            else httpx2.Response(200, json={})
        ),
    )
    result = invoke("apply", policy_file, "--if-match", '"v1"', "--execute")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["applied"] is False
    assert [r.url.path for r in requests] == [ACL_PATH, ACL_PATH + "/validate"]


@pytest.mark.parametrize(
    "validation",
    [
        {"message": "test(s) failed", "data": [{"errors": ["want Drop, got Accept"]}]},
        {"errors": ["invalid policy"]},
    ],
)
def test_http_200_validation_failure_blocks_publish(
    monkeypatch, policy_file, validation
):
    requests = mock_api(
        monkeypatch,
        lambda req: (
            httpx2.Response(200, content=CURRENT, headers={"ETag": '"v1"'})
            if req.method == "GET"
            else httpx2.Response(200, json=validation)
        ),
    )
    result = invoke("apply", policy_file, "--if-match", '"v1"', "--execute")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "策略校验失败" in json.loads(result.stderr)["error"]
    assert [r.url.path for r in requests] == [ACL_PATH, ACL_PATH + "/validate"]


@pytest.mark.parametrize("concurrent", [False, True])
def test_stale_baseline_or_write_conflict_never_retries(
    monkeypatch, policy_file, concurrent
):
    def respond(request):
        if request.method == "GET":
            return httpx2.Response(
                200,
                content=CURRENT,
                headers={"ETag": '"v1"' if concurrent else '"changed"'},
            )
        if request.url.path.endswith("/validate"):
            return httpx2.Response(200, json={})
        return httpx2.Response(412, json={"message": "invalid old hash"})

    requests = mock_api(monkeypatch, respond)
    result = invoke("apply", policy_file, "--if-match", '"v1"', "--execute")
    assert result.exit_code == 1
    assert "合并改动" in result.stderr
    assert len(requests) == (3 if concurrent else 1)


@pytest.mark.parametrize("failure", ["mismatch", "network", "post_network"])
def test_unknown_or_unverified_publish_is_never_reported_success(
    monkeypatch, policy_file, failure
):
    writes = []

    def respond(request):
        if request.method == "GET":
            if writes and failure == "network":
                raise httpx2.ReadTimeout("private transport detail", request=request)
            return httpx2.Response(
                200, content=CURRENT, headers={"ETag": '"other"' if writes else '"v1"'}
            )
        if request.url.path.endswith("/validate"):
            return httpx2.Response(200, json={})
        writes.append(request)
        if failure == "post_network":
            raise httpx2.ReadTimeout("private transport detail", request=request)
        return httpx2.Response(200, content=CANDIDATE, headers={"ETag": '"v2"'})

    mock_api(monkeypatch, respond)
    result = invoke("apply", policy_file, "--if-match", '"v1"', "--execute")
    assert result.exit_code == 1 and len(writes) == 1
    assert result.stdout == "" and "private transport detail" not in result.stderr
    assert "回读" in result.stderr or "结果未知" in result.stderr


def test_oauth_form_and_bearer_token(monkeypatch):
    monkeypatch.delenv("TS_API_KEY")
    monkeypatch.setenv("TS_CLIENT_ID", "test-client")
    monkeypatch.setenv("TS_CLIENT_SECRET", "test-client-secret")

    def respond(request):
        if request.url.path.endswith("/oauth/token"):
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["client_credentials"],
                "client_id": ["test-client"],
                "client_secret": ["test-client-secret"],
            }
            assert "Authorization" not in request.headers
            return httpx2.Response(200, json={"access_token": "test-oauth-token"})
        assert request.headers["Authorization"] == "Bearer test-oauth-token"
        return httpx2.Response(200, content=CURRENT, headers={"ETag": '"v1"'})

    mock_api(monkeypatch, respond)
    result = invoke("get")
    assert result.exit_code == 0, result.output
    assert (
        "test-oauth-token" not in result.output
        and "test-client-secret" not in result.output
    )


def test_oauth_error_never_echoes_secret(monkeypatch):
    monkeypatch.delenv("TS_API_KEY")
    monkeypatch.setenv("TS_CLIENT_ID", "client")
    monkeypatch.setenv("TS_CLIENT_SECRET", "private-secret")
    mock_api(monkeypatch, lambda req: httpx2.Response(400, text="private-secret"))
    result = invoke("get")
    assert result.exit_code == 1 and "private-secret" not in result.output
    assert "认证或权限不足" in result.stderr


def test_environment_credentials_do_not_mix_with_config(monkeypatch, tmp_path):
    config = tmp_path / "tailscale-cli/config.toml"
    config.parent.mkdir()
    config.write_text(
        'tailnet = "example.com"\nclient_id = "configured-client"\nclient_secret = "configured-secret"\n'
    )
    monkeypatch.delenv("TS_TAILNET")
    requests = mock_api(
        monkeypatch,
        lambda req: httpx2.Response(200, content=CURRENT, headers={"ETag": '"v1"'}),
    )
    assert invoke("get").exit_code == 0
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-api-secret"
    monkeypatch.delenv("TS_API_KEY")
    monkeypatch.setenv("TS_CLIENT_ID", "incomplete-env-client")
    assert invoke("get").exit_code == 1
    assert len(requests) == 1


@pytest.mark.parametrize("etag", ["*", "v1", 'W/"v1"', '"v1", "v2"'])
def test_cli_rejects_invalid_etag_before_network(policy_file, etag):
    result = invoke("apply", policy_file, "--if-match", etag)
    assert result.exit_code == 2


def test_help_exposes_real_options_and_types():
    result = invoke("preview", "--help")
    text = Text.from_ansi(result.stdout).plain
    assert result.exit_code == 0
    for term in ("--type", "--for", "user", "ipport"):
        assert term in text
    result = invoke("apply", "--help")
    text = Text.from_ansi(result.stdout).plain
    assert "--if-match" in text and "--execute" in text and "ETAG" in text


def test_cli_rejects_missing_file_and_unknown_preview_type(tmp_path, policy_file):
    assert invoke("validate", tmp_path / "missing").exit_code == 2
    assert (
        invoke("preview", policy_file, "--type", "tag", "--for", "tag:server").exit_code
        == 2
    )


def test_missing_etag_does_not_produce_a_publish_baseline(monkeypatch):
    mock_api(monkeypatch, lambda req: httpx2.Response(200, content=CURRENT))
    result = invoke("get")
    assert result.exit_code == 1 and "ETag" in result.stderr


def test_permission_error_keeps_response_body_private(monkeypatch):
    mock_api(monkeypatch, lambda req: httpx2.Response(403, text="private-response"))
    result = invoke("get")
    assert result.exit_code == 1 and "scopes" in result.stderr
    assert "private-response" not in result.output


def test_empty_policy_is_not_submitted(policy_file):
    policy_file.write_bytes(b" \n")
    result = invoke("validate", policy_file)
    assert result.exit_code == 1 and "策略文件为空" in result.stderr


def test_config_token_and_tailnet_override(monkeypatch, tmp_path):
    monkeypatch.delenv("TS_API_KEY")
    config = tmp_path / "explicit.toml"
    config.write_text('tailnet = "from-config"\napi_token = "config-token"\n')
    requests = mock_api(
        monkeypatch,
        lambda req: httpx2.Response(200, content=CURRENT, headers={"ETag": '"v1"'}),
    )
    result = CliRunner().invoke(
        cli.app,
        ["--config", str(config), "--tailnet", "explicit-tailnet", "policy", "get"],
    )
    assert result.exit_code == 0, result.output
    assert requests[0].url.path == "/api/v2/tailnet/explicit-tailnet/acl"
    assert requests[0].headers["Authorization"] == "Bearer config-token"


def test_malformed_config_does_not_echo_secret(tmp_path):
    config = tmp_path / "tailscale-cli/config.toml"
    config.parent.mkdir()
    config.write_text('client_secret = "unclosed-private-secret')
    result = invoke("get")
    assert result.exit_code == 1 and "unclosed-private-secret" not in result.output

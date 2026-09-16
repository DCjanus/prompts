#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "gql[httpx2]==4.4.0b0",
#     "tomli-w>=1.2.0",
#     "typer>=0.27.2",
# ]
# ///

"""通过 Linear 官方 GraphQL API 管理 Linear 资源。"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx2 as httpx
import tomli_w
import tomllib
import typer
from gql import Client as GraphQLClient
from gql import gql
from gql.transport.exceptions import TransportError
from gql.transport.httpx import HTTPXTransport
from graphql import GraphQLError

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
DEFAULT_ENDPOINT = "https://api.linear.app/graphql"
OAUTH_AUTHORIZE_URL = "https://linear.app/oauth/authorize"
OAUTH_TOKEN_URL = "https://api.linear.app/oauth/token"
DEFAULT_CONFIG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "linear-cli"
    / "config.toml"
)

ISSUE_FIELDS = """
id identifier title description priority dueDate url
state { id name type }
team { id key name }
cycle { id name number startsAt endsAt }
project { id name }
parent { id identifier title }
labels { nodes { id name } }
relations { nodes { id type relatedIssue { id identifier title } } }
inverseRelations { nodes { id type issue { id identifier title } } }
"""


class LinearError(RuntimeError):
    """Linear 请求或响应错误。"""


@dataclass(frozen=True)
class Settings:
    """Linear 连接配置。"""

    endpoint: str
    token: str
    oauth: bool


def validate_personal_api_key(token: str) -> str:
    """校验 Linear 个人 API key 的公开格式约束。"""
    if not token.startswith("lin_api_"):
        raise LinearError("Linear 个人 API key 必须以 lin_api_ 开头")
    if any(character.isspace() for character in token):
        raise LinearError("Linear 个人 API key 不能包含空白字符")
    return token


def save_config(data: dict[str, Any], path: Path = DEFAULT_CONFIG_PATH) -> None:
    """以 0600 原子保存配置。"""
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(tomli_w.dumps(data))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """读取本地配置而不输出凭据。"""
    path = path.expanduser()
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LinearError(f"配置不存在：{path}") from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise LinearError(f"无法读取配置 {path}：{error}") from error


def refresh_oauth_config(config: dict[str, Any], path: Path) -> dict[str, Any]:
    """使用 refresh token 刷新 OAuth access token。"""
    if not config.get("client_id") or not config.get("refresh_token"):
        raise LinearError("OAuth token 已过期且配置缺少 client_id/refresh_token")
    try:
        response = httpx.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": config["client_id"],
                "refresh_token": config["refresh_token"],
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise LinearError(f"OAuth token 刷新失败：{error}") from error
    config.update(
        token=payload["access_token"],
        refresh_token=payload.get("refresh_token", config["refresh_token"]),
        expires_at=int(time.time()) + int(payload.get("expires_in", 86400)) - 60,
    )
    save_config(config, path)
    return config


def settings_from_env(endpoint: str) -> Settings:
    """从环境变量或 XDG 配置读取认证信息。"""
    api_key = os.environ.get("LINEAR_API_KEY")
    access_token = os.environ.get("LINEAR_ACCESS_TOKEN")
    if api_key and access_token:
        raise LinearError("LINEAR_API_KEY 与 LINEAR_ACCESS_TOKEN 只能设置一个")
    if access_token:
        return Settings(endpoint, access_token, True)
    if api_key:
        return Settings(endpoint, validate_personal_api_key(api_key), False)
    config_path = Path(
        os.environ.get("LINEAR_CONFIG", DEFAULT_CONFIG_PATH)
    ).expanduser()
    if config_path.exists():
        config = load_config(config_path)
        auth_type = config.get("auth_type", "api-key")
        if (
            auth_type == "oauth"
            and config.get("refresh_token")
            and int(config.get("expires_at", 0)) <= int(time.time())
        ):
            config = refresh_oauth_config(config, config_path)
        token = config.get("token")
        if token and auth_type in {"api-key", "api-key-bearer", "oauth"}:
            if auth_type in {"api-key", "api-key-bearer"}:
                token = validate_personal_api_key(str(token))
            return Settings(
                endpoint,
                str(token),
                auth_type in {"api-key-bearer", "oauth"},
            )
    raise LinearError("缺少 Linear 凭据；设置环境变量或运行 auth login-api-key")


class LinearClient:
    """最小 Linear GraphQL 客户端。"""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        authorization = f"Bearer {settings.token}" if settings.oauth else settings.token
        graphql_transport = HTTPXTransport(
            url=settings.endpoint,
            headers={"Authorization": authorization},
            timeout=30,
            transport=transport,
        )
        self.client = GraphQLClient(transport=graphql_transport)

    def query(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        """执行 GraphQL 请求并拒绝部分成功响应。"""
        try:
            return self.client.execute(gql(query), variable_values=variables or {})
        except GraphQLError as error:
            raise LinearError(f"Linear GraphQL 文档错误：{error}") from error
        except TransportError as error:
            raise LinearError(f"Linear GraphQL 请求失败：{error}") from error


def emit(payload: Any) -> None:
    """输出稳定 UTF-8 JSON。"""
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def get_client(endpoint: str) -> LinearClient:
    """创建命令行客户端。"""
    return LinearClient(settings_from_env(endpoint))


def read_identity(client: LinearClient) -> dict[str, Any]:
    """读取当前用户与 workspace，验证认证是否真实可用。"""
    return client.query(
        """
        query Identity {
          viewer { id name }
          organization { id name urlKey }
        }
        """
    )


def resolve_team(client: LinearClient, team_key: str) -> dict[str, Any]:
    """按 key 精确解析 Team，并拒绝猜测。"""
    data = client.query(
        """
        query Team($key: String!) {
          teams(filter: { key: { eq: $key } }, first: 10) {
            nodes { id key name }
          }
        }
        """,
        {"key": team_key},
    )
    teams = data["teams"]["nodes"]
    if len(teams) != 1:
        raise LinearError(f"Team {team_key!r} 精确匹配数量为 {len(teams)}")
    return teams[0]


def read_view(client: LinearClient, view_id: str) -> dict[str, Any]:
    """按 UUID 或 slug 回读 Custom View。"""
    data = client.query(
        """
        query View($id: String!) {
          customView(id: $id) {
            id slugId name description shared icon color modelName filterData
            owner { id name } team { id key name }
          }
        }
        """,
        {"id": view_id},
    )
    view = data.get("customView")
    if not view:
        raise LinearError(f"找不到 Linear Custom View {view_id}")
    return view


config_app = typer.Typer(no_args_is_help=True)
auth_app = typer.Typer(no_args_is_help=True)
view_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(auth_app, name="auth")
app.add_typer(view_app, name="view")


@config_app.command("set")
def config_set(
    auth_type: Annotated[Literal["api-key", "oauth"], typer.Option()] = "api-key",
    prompt_token: Annotated[bool, typer.Option("--prompt-token")] = False,
    token_stdin: Annotated[bool, typer.Option("--token-stdin")] = False,
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    """安全保存 API key 或已获取的 OAuth access token。"""
    if prompt_token == token_stdin:
        raise typer.BadParameter("必须且只能使用 --prompt-token 或 --token-stdin")
    token = (
        getpass.getpass("Linear token: ").strip()
        if prompt_token
        else sys.stdin.read().strip()
    )
    if not token:
        raise typer.BadParameter("token 不能为空")
    if auth_type == "api-key":
        token = validate_personal_api_key(token)
    path = config_path.expanduser()
    save_config({"auth_type": auth_type, "token": token}, path)
    emit({"authType": auth_type, "config": str(path), "saved": True})


@config_app.command("show")
def config_show(
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    """显示遮蔽后的配置。"""
    path = config_path.expanduser()
    if not path.exists():
        emit({"config": str(path), "exists": False})
        return
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("token", "refresh_token"):
        if data.get(key):
            data[key] = "********"
    emit({"config": str(path), "exists": True, **data})


@auth_app.command("login-api-key")
def auth_login_api_key(
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """交互式验证并安全保存个人 API key。"""
    token = getpass.getpass("Linear personal API key: ").strip()
    if not token:
        raise typer.BadParameter("API key 不能为空")
    token = validate_personal_api_key(token)
    identity = read_identity(LinearClient(Settings(endpoint, token, False)))
    path = config_path.expanduser()
    save_config({"auth_type": "api-key", "token": token}, path)
    emit(
        {
            "authType": "api-key",
            "config": str(path),
            "loggedIn": True,
            **identity,
        }
    )


@auth_app.command("repair")
def auth_repair(
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """复用已保存凭据诊断并修复认证头模式。"""
    path = config_path.expanduser()
    config = load_config(path)
    token = str(config.get("token", "")).strip()
    if not token:
        raise LinearError("配置中没有可修复的 token")
    token = validate_personal_api_key(token.removeprefix("Bearer ").strip())

    candidates: list[tuple[str, str, bool]] = [("api-key", token, False)]
    candidates.append(("api-key-bearer", token, True))

    attempted: list[str] = []
    for auth_type, candidate, bearer in candidates:
        if auth_type in attempted:
            continue
        attempted.append(auth_type)
        try:
            identity = read_identity(
                LinearClient(Settings(endpoint, candidate, bearer))
            )
        except LinearError:
            continue
        config.update(auth_type=auth_type, token=candidate)
        save_config(config, path)
        emit(
            {
                "attempted": attempted,
                "authType": auth_type,
                "config": str(path),
                "repaired": True,
                **identity,
            }
        )
        return
    raise LinearError(f"已保存凭据使用认证模式 {attempted} 均被 Linear 拒绝")


@auth_app.command("login")
def auth_login(
    client_id: Annotated[str, typer.Option("--client-id")],
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 45831,
    scope: Annotated[str, typer.Option()] = "read,write",
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    """通过本机回调执行 Linear OAuth PKCE 登录。"""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            result["code"] = query.get("code", [""])[0]
            result["state"] = query.get("state", [""])[0]
            result["error"] = query.get("error", [""])[0]
            body = b"Linear CLI authorization received. You may close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    server.timeout = 180
    authorize_url = (
        OAUTH_AUTHORIZE_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scope,
                "state": state,
                "actor": "user",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    typer.echo(f"Open this URL to authorize:\n{authorize_url}")
    threading.Thread(target=webbrowser.open, args=(authorize_url,), daemon=True).start()
    server.handle_request()
    server.server_close()
    if result.get("error"):
        raise LinearError(f"OAuth 授权失败：{result['error']}")
    if not result.get("code") or result.get("state") != state:
        raise LinearError("OAuth 回调缺少 code 或 state 校验失败")
    try:
        response = httpx.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code": result["code"],
                "code_verifier": verifier,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise LinearError(f"OAuth code 交换失败：{error}") from error
    path = config_path.expanduser()
    save_config(
        {
            "auth_type": "oauth",
            "client_id": client_id,
            "token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", ""),
            "expires_at": int(time.time()) + int(payload.get("expires_in", 86400)) - 60,
            "scope": payload.get("scope", scope),
            "redirect_uri": redirect_uri,
        },
        path,
    )
    emit({"authType": "oauth", "config": str(path), "loggedIn": True})


def read_issue(client: LinearClient, issue_id: str) -> dict[str, Any]:
    """按 UUID 或标识回读 Issue。"""
    data = client.query(
        f"query Issue($id: String!) {{ issue(id: $id) {{ {ISSUE_FIELDS} }} }}",
        {"id": issue_id},
    )
    issue = data.get("issue")
    if not issue:
        raise LinearError(f"找不到 Linear Issue {issue_id}")
    return issue


@app.command("doctor")
def doctor(
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    team: Annotated[str | None, typer.Option("--team")] = None,
) -> None:
    """验证认证、workspace 与目标 Team 的只读能力。"""
    client = get_client(endpoint)
    data = read_identity(client)
    if team:
        data["team"] = resolve_team(client, team)
    emit(data)


@app.command("team-show")
def team_show(
    team: Annotated[str, typer.Option("--team")],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """读取 Team 的状态、Cycle、Label 与 Project 候选。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, team)
    data = client.query(
        """
        query TeamConfig($id: String!) {
          team(id: $id) {
            id key name
            states { nodes { id name type position } }
            cycles(first: 20) { nodes { id name number startsAt endsAt } }
            labels(first: 100) { nodes { id name color } }
            projects(first: 100) { nodes { id name state } }
          }
        }
        """,
        {"id": resolved["id"]},
    )
    emit(data["team"])


@app.command("issue-get")
def issue_get(
    issue_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """回读一个 Issue。"""
    emit(read_issue(get_client(endpoint), issue_id))


@app.command("issue-list")
def issue_list(
    team: Annotated[str, typer.Option("--team")],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    first: Annotated[int, typer.Option(min=1, max=250)] = 100,
) -> None:
    """列出目标 Team 的近期 Issue。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, team)
    data = client.query(
        f"""
        query Issues($id: ID!, $first: Int!) {{
          issues(
            filter: {{ team: {{ id: {{ eq: $id }} }} }}
            first: $first
            orderBy: updatedAt
          ) {{ nodes {{ {ISSUE_FIELDS} }} }}
        }}
        """,
        {"id": resolved["id"], "first": first},
    )
    emit(data["issues"]["nodes"])


def compact_input(values: dict[str, Any]) -> dict[str, Any]:
    """移除 CLI 未提供的可选字段。"""
    return {key: value for key, value in values.items() if value is not None}


@app.command("issue-create")
def issue_create(
    title: Annotated[str, typer.Option()],
    team: Annotated[str, typer.Option("--team")],
    description: Annotated[str | None, typer.Option()] = None,
    state_id: Annotated[str | None, typer.Option()] = None,
    priority: Annotated[int | None, typer.Option(min=0, max=4)] = None,
    cycle_id: Annotated[str | None, typer.Option()] = None,
    project_id: Annotated[str | None, typer.Option()] = None,
    parent_id: Annotated[str | None, typer.Option()] = None,
    due_date: Annotated[str | None, typer.Option()] = None,
    label_id: Annotated[list[str] | None, typer.Option()] = None,
    assignee_id: Annotated[str | None, typer.Option()] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或创建 Issue，并在写入后回读。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, team)
    fields = compact_input(
        {
            "teamId": resolved["id"],
            "title": title,
            "description": description,
            "stateId": state_id,
            "priority": priority,
            "cycleId": cycle_id,
            "projectId": project_id,
            "parentId": parent_id,
            "dueDate": due_date,
            "labelIds": label_id,
            "assigneeId": assignee_id,
        }
    )
    if not yes:
        emit({"action": "issueCreate", "input": fields, "preview": True})
        return
    data = client.query(
        """
        mutation Create($input: IssueCreateInput!) {
          issueCreate(input: $input) { success issue { id identifier } }
        }
        """,
        {"input": fields},
    )["issueCreate"]
    if not data["success"]:
        raise LinearError("issueCreate 返回 success=false")
    emit(read_issue(client, data["issue"]["id"]))


@app.command("issue-update")
def issue_update(
    issue_id: Annotated[str, typer.Argument()],
    title: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str | None, typer.Option()] = None,
    state_id: Annotated[str | None, typer.Option()] = None,
    priority: Annotated[int | None, typer.Option(min=0, max=4)] = None,
    cycle_id: Annotated[str | None, typer.Option()] = None,
    project_id: Annotated[str | None, typer.Option()] = None,
    parent_id: Annotated[str | None, typer.Option()] = None,
    due_date: Annotated[str | None, typer.Option()] = None,
    label_id: Annotated[list[str] | None, typer.Option()] = None,
    assignee_id: Annotated[str | None, typer.Option()] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或更新 Issue，并在写入后回读。"""
    client = get_client(endpoint)
    before = read_issue(client, issue_id)
    fields = compact_input(
        {
            "title": title,
            "description": description,
            "stateId": state_id,
            "priority": priority,
            "cycleId": cycle_id,
            "projectId": project_id,
            "parentId": parent_id,
            "dueDate": due_date,
            "labelIds": label_id,
            "assigneeId": assignee_id,
        }
    )
    if not fields:
        raise typer.BadParameter("至少提供一个更新字段")
    if not yes:
        emit(
            {
                "action": "issueUpdate",
                "before": before,
                "input": fields,
                "preview": True,
            }
        )
        return
    data = client.query(
        """
        mutation Update($id: String!, $input: IssueUpdateInput!) {
          issueUpdate(id: $id, input: $input) { success issue { id } }
        }
        """,
        {"id": before["id"], "input": fields},
    )["issueUpdate"]
    if not data["success"]:
        raise LinearError("issueUpdate 返回 success=false")
    emit(read_issue(client, before["id"]))


@app.command("relation-create")
def relation_create(
    issue_id: Annotated[str, typer.Argument()],
    related_issue_id: Annotated[str, typer.Argument()],
    relation_type: Annotated[
        Literal["blocks", "related", "duplicate"], typer.Option("--type")
    ] = "related",
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或创建原生 Issue 关系，并回读两端。"""
    client = get_client(endpoint)
    issue = read_issue(client, issue_id)
    related = read_issue(client, related_issue_id)
    fields = {
        "issueId": issue["id"],
        "relatedIssueId": related["id"],
        "type": relation_type,
    }
    if not yes:
        emit({"action": "issueRelationCreate", "input": fields, "preview": True})
        return
    data = client.query(
        """
        mutation Relation($input: IssueRelationCreateInput!) {
          issueRelationCreate(input: $input) { success issueRelation { id type } }
        }
        """,
        {"input": fields},
    )["issueRelationCreate"]
    if not data["success"]:
        raise LinearError("issueRelationCreate 返回 success=false")
    emit(
        {
            "relation": data["issueRelation"],
            "issue": read_issue(client, issue["id"]),
            "relatedIssue": read_issue(client, related["id"]),
        }
    )


def parse_json_object(raw: str, option_name: str) -> dict[str, Any]:
    """解析 CLI JSON object 参数。"""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise typer.BadParameter(f"{option_name} 不是有效 JSON：{error}") from error
    if not isinstance(value, dict):
        raise typer.BadParameter(f"{option_name} 必须是 JSON object")
    return value


@view_app.command("list")
def view_list(
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    first: Annotated[int, typer.Option(min=1, max=250)] = 100,
) -> None:
    """列出当前用户可访问的 Custom Views。"""
    client = get_client(endpoint)
    data = client.query(
        """
        query Views($first: Int!) {
          customViews(first: $first) { nodes {
            id slugId name description shared icon color modelName filterData
            owner { id name } team { id key name }
          } }
        }
        """,
        {"first": first},
    )
    emit(data["customViews"]["nodes"])


@view_app.command("get")
def view_get(
    view_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """回读一个 Custom View。"""
    emit(read_view(get_client(endpoint), view_id))


@view_app.command("issues")
def view_issues(
    view_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    first: Annotated[int, typer.Option(min=1, max=250)] = 100,
) -> None:
    """列出一个 Issue Custom View 当前命中的事项。"""
    client = get_client(endpoint)
    data = client.query(
        """
        query ViewIssues($id: String!, $first: Int!) {
          customView(id: $id) {
            id name modelName
            issues(first: $first) { nodes {
              id identifier title priority dueDate url
              state { id name type }
              assignee { id name }
            } }
          }
        }
        """,
        {"id": view_id, "first": first},
    )
    view = data.get("customView")
    if not view:
        raise LinearError(f"找不到 Linear Custom View {view_id}")
    if view["modelName"] != "Issue":
        raise LinearError(f"Custom View {view_id} 不是 Issue View")
    emit(
        {
            "id": view["id"],
            "name": view["name"],
            "issues": view["issues"]["nodes"],
        }
    )


@view_app.command("create")
def view_create(
    name: Annotated[str, typer.Option()],
    filter_json: Annotated[str, typer.Option("--filter-json")],
    description: Annotated[str | None, typer.Option()] = None,
    team_id: Annotated[str | None, typer.Option()] = None,
    owner_id: Annotated[str | None, typer.Option()] = None,
    shared: Annotated[bool, typer.Option("--shared/--personal")] = False,
    icon: Annotated[str | None, typer.Option()] = None,
    color: Annotated[str | None, typer.Option()] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或创建 Issue Custom View，并回读。"""
    client = get_client(endpoint)
    fields = compact_input(
        {
            "name": name,
            "description": description,
            "filterData": parse_json_object(filter_json, "--filter-json"),
            "teamId": team_id,
            "ownerId": owner_id,
            "shared": shared,
            "icon": icon,
            "color": color,
        }
    )
    if not yes:
        emit({"action": "customViewCreate", "input": fields, "preview": True})
        return
    result = client.query(
        """mutation CreateView($input: CustomViewCreateInput!) {
          customViewCreate(input: $input) { success customView { id slugId } }
        }""",
        {"input": fields},
    )["customViewCreate"]
    if not result["success"]:
        raise LinearError("customViewCreate 返回 success=false")
    emit(read_view(client, result["customView"]["id"]))


@view_app.command("update")
def view_update(
    view_id: Annotated[str, typer.Argument()],
    name: Annotated[str | None, typer.Option()] = None,
    filter_json: Annotated[str | None, typer.Option("--filter-json")] = None,
    description: Annotated[str | None, typer.Option()] = None,
    shared: Annotated[bool | None, typer.Option("--shared/--personal")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或更新 Custom View，并回读。"""
    client = get_client(endpoint)
    before = read_view(client, view_id)
    fields = compact_input(
        {
            "name": name,
            "description": description,
            "filterData": parse_json_object(filter_json, "--filter-json")
            if filter_json
            else None,
            "shared": shared,
        }
    )
    if not fields:
        raise typer.BadParameter("至少提供一个更新字段")
    if not yes:
        emit(
            {
                "action": "customViewUpdate",
                "before": before,
                "input": fields,
                "preview": True,
            }
        )
        return
    result = client.query(
        """mutation UpdateView($id: String!, $input: CustomViewUpdateInput!) {
          customViewUpdate(id: $id, input: $input) { success customView { id } }
        }""",
        {"id": before["id"], "input": fields},
    )["customViewUpdate"]
    if not result["success"]:
        raise LinearError("customViewUpdate 返回 success=false")
    emit(read_view(client, before["id"]))


def main() -> None:
    """执行 CLI 并统一输出错误。"""
    try:
        app()
    except LinearError as error:
        typer.echo(str(error), err=True)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

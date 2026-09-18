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
from datetime import date
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
from graphql import GraphQLError, OperationType, parse
from graphql.language.ast import OperationDefinitionNode

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
id identifier title description priority dueDate url archivedAt
state { id name type }
team { id key name }
cycle { id name number startsAt endsAt }
project { id name }
parent { id identifier title }
assignee { id name email }
labels { nodes { id name } }
relations { nodes { id type relatedIssue { id identifier title } } }
inverseRelations { nodes { id type issue { id identifier title } } }
"""

ISSUE_FIELD_SELECTIONS = {
    "id": "id",
    "identifier": "identifier",
    "title": "title",
    "description": "description",
    "priority": "priority",
    "dueDate": "dueDate",
    "url": "url",
    "archivedAt": "archivedAt",
    "createdAt": "createdAt",
    "updatedAt": "updatedAt",
    "state": "state { id name type }",
    "team": "team { id key name }",
    "cycle": "cycle { id name number startsAt endsAt }",
    "project": "project { id name }",
    "parent": "parent { id identifier title }",
    "assignee": "assignee { id name email }",
    "labels": "labels { nodes { id name } }",
    "relations": (
        "relations { nodes { id type relatedIssue { id identifier title } } }"
    ),
    "inverseRelations": (
        "inverseRelations { nodes { id type issue { id identifier title } } }"
    ),
}

LABEL_FIELDS = """
id name description color createdAt updatedAt
team { id key name }
"""

WORKFLOW_STATE_FIELDS = """
id name type color description position
team { id key name }
"""

COMMENT_FIELDS = """
id body createdAt updatedAt url
user { id name email }
"""

CODEX_RESUME_FOOTER_TEMPLATE = """---

+++ 在 Codex 中继续

```sh
codex resume {thread_id}
```

+++"""


class LinearError(RuntimeError):
    """Linear 请求或响应错误。"""


def select_issue_fields(fields: str | None) -> str:
    """把公开字段名转换为安全的 Issue GraphQL selection set。"""
    if fields is None:
        return ISSUE_FIELDS
    names = list(
        dict.fromkeys(name.strip() for name in fields.split(",") if name.strip())
    )
    if not names:
        raise typer.BadParameter("--fields 不能为空")
    unknown = [name for name in names if name not in ISSUE_FIELD_SELECTIONS]
    if unknown:
        raise typer.BadParameter(f"不支持的 Issue 字段：{', '.join(unknown)}")
    return "\n".join(ISSUE_FIELD_SELECTIONS[name] for name in names)


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


def update_config(updates: dict[str, Any], path: Path = DEFAULT_CONFIG_PATH) -> None:
    """保留其它配置项并原子更新指定字段。"""
    path = path.expanduser()
    config = load_config(path) if path.exists() else {}
    config.update(updates)
    save_config(config, path)


def default_team_from_config() -> str | None:
    """读取可选默认 Team；环境变量指定的配置路径同样生效。"""
    path = Path(os.environ.get("LINEAR_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    if not path.exists():
        return None
    team = load_config(path).get("default_team")
    if not isinstance(team, str) or not team.strip():
        return None
    return team.strip()


def select_team(team: str | None) -> str:
    """显式 Team 优先，否则回退到本地可选默认值。"""
    if team is not None and team.strip():
        return team.strip()
    default_team = default_team_from_config()
    if default_team:
        return default_team
    raise typer.BadParameter("缺少 --team，且配置中未设置 default_team")


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


def settings_from_env(endpoint: str, config_path: Path | None = None) -> Settings:
    """从环境变量或 XDG 配置读取认证信息。"""
    api_key = os.environ.get("LINEAR_API_KEY")
    access_token = os.environ.get("LINEAR_ACCESS_TOKEN")
    if api_key and access_token:
        raise LinearError("LINEAR_API_KEY 与 LINEAR_ACCESS_TOKEN 只能设置一个")
    if access_token:
        return Settings(endpoint, access_token, True)
    if api_key:
        return Settings(endpoint, validate_personal_api_key(api_key), False)
    config_path = (
        config_path
        if config_path is not None
        else Path(os.environ.get("LINEAR_CONFIG", DEFAULT_CONFIG_PATH))
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


def get_client(endpoint: str, config_path: Path | None = None) -> LinearClient:
    """创建命令行客户端。"""
    return LinearClient(settings_from_env(endpoint, config_path))


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


def read_team_automations(client: LinearClient, team_id: str) -> dict[str, Any]:
    """读取 Team 的自动关闭和自动归档设置，并解析目标状态。"""
    data = client.query(
        """
        query TeamAutomations($id: String!) {
          team(id: $id) {
            id key name
            autoArchivePeriod
            autoClosePeriod
            autoCloseStateId
            autoCloseParentIssues
            autoCloseChildIssues
            states { nodes { id name type } }
          }
        }
        """,
        {"id": team_id},
    )
    team = data.get("team")
    if not team:
        raise LinearError(f"找不到 Linear Team {team_id}")
    state_id = team.pop("autoCloseStateId")
    states = team.pop("states")["nodes"]
    team["autoCloseState"] = next(
        (state for state in states if state["id"] == state_id), None
    )
    return team


def resolve_team_state(
    client: LinearClient, team_id: str, state_name_or_id: str
) -> dict[str, Any]:
    """按 UUID 或名称精确解析 Team workflow state。"""
    data = client.query(
        """
        query TeamStates($id: String!) {
          team(id: $id) { states { nodes { id name type } } }
        }
        """,
        {"id": team_id},
    )
    team = data.get("team")
    if not team:
        raise LinearError(f"找不到 Linear Team {team_id}")
    states = [
        state
        for state in team["states"]["nodes"]
        if state["id"] == state_name_or_id or state["name"] == state_name_or_id
    ]
    if len(states) != 1:
        raise LinearError(
            f"Workflow state {state_name_or_id!r} 精确匹配数量为 {len(states)}"
        )
    if states[0]["type"] not in {"completed", "canceled"}:
        raise LinearError("自动关闭目标必须是 completed 或 canceled 状态")
    return states[0]


def list_workflow_states(client: LinearClient, team_id: str) -> list[dict[str, Any]]:
    """读取目标 Team 的 workflow states。"""
    data = client.query(
        f"""
        query WorkflowStates($id: String!) {{
          team(id: $id) {{
            states {{ nodes {{ {WORKFLOW_STATE_FIELDS} }} }}
          }}
        }}
        """,
        {"id": team_id},
    )
    team = data.get("team")
    if not team:
        raise LinearError(f"找不到 Linear Team {team_id}")
    return team["states"]["nodes"]


def resolve_workflow_state(
    client: LinearClient, team_id: str, state_name_or_id: str
) -> dict[str, Any]:
    """在目标 Team 内按 UUID 或名称精确解析 workflow state。"""
    states = [
        state
        for state in list_workflow_states(client, team_id)
        if state["id"] == state_name_or_id or state["name"] == state_name_or_id
    ]
    if len(states) != 1:
        raise LinearError(
            f"Workflow state {state_name_or_id!r} 精确匹配数量为 {len(states)}"
        )
    return states[0]


def list_labels(client: LinearClient) -> list[dict[str, Any]]:
    """读取 workspace 中的 Issue Labels。"""
    data = client.query(
        f"""
        query IssueLabels {{
          issueLabels(first: 250) {{ nodes {{ {LABEL_FIELDS} }} }}
        }}
        """
    )
    return data["issueLabels"]["nodes"]


def resolve_label(
    client: LinearClient,
    label_name_or_id: str,
    team_id: str | None = None,
) -> dict[str, Any]:
    """按 UUID 或名称精确解析 Label，并限制可选 Team 范围。"""
    labels = [
        label
        for label in list_labels(client)
        if label["id"] == label_name_or_id or label["name"] == label_name_or_id
    ]
    if team_id is not None:
        labels = [
            label
            for label in labels
            if label.get("team") is None or label["team"]["id"] == team_id
        ]
    if len(labels) != 1:
        raise LinearError(
            f"Issue Label {label_name_or_id!r} 精确匹配数量为 {len(labels)}"
        )
    return labels[0]


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


def read_view_preference_schema(client: LinearClient) -> dict[str, str]:
    """读取当前 Linear 支持的 View preference 字段与标量类型。"""
    data = client.query(
        """
        query ViewPreferenceSchema {
          __type(name: "ViewPreferencesValues") {
            fields { name type { kind name ofType { kind name } } }
          }
        }
        """
    )
    view_preferences_type = data.get("__type")
    if not view_preferences_type:
        raise LinearError("Linear schema 中缺少 ViewPreferencesValues")
    schema: dict[str, str] = {}
    for field in view_preferences_type["fields"]:
        field_type = field["type"]
        if field_type["kind"] == "NON_NULL":
            field_type = field_type["ofType"]
        if field_type["kind"] not in {"SCALAR", "ENUM"}:
            continue
        schema[field["name"]] = field_type["name"]
    return schema


def read_view_preferences(
    client: LinearClient,
    view_id: str,
    schema: dict[str, str] | None = None,
) -> dict[str, Any]:
    """读取 Custom View 的当前用户偏好与最终有效值。"""
    schema = schema or read_view_preference_schema(client)
    if not schema:
        raise LinearError("Linear schema 没有可读取的 View preference 字段")
    fields = "\n".join(sorted(schema))
    data = client.query(
        f"""
        query ViewPreferences($id: String!) {{
          customView(id: $id) {{
            id slugId name modelName
            userViewPreferences {{
              id type viewType
              preferences {{ {fields} }}
            }}
            viewPreferencesValues {{ {fields} }}
          }}
        }}
        """,
        {"id": view_id},
    )
    view = data.get("customView")
    if not view:
        raise LinearError(f"找不到 Linear Custom View {view_id}")
    if view["modelName"] != "Issue":
        raise LinearError(f"Custom View {view_id} 不是 Issue View")
    user_preferences = view.pop("userViewPreferences")
    effective = view.pop("viewPreferencesValues")
    explicit = {
        key: value
        for key, value in (user_preferences or {}).get("preferences", {}).items()
        if value is not None
    }
    return {
        "view": view,
        "preferenceId": user_preferences["id"] if user_preferences else None,
        "explicit": explicit,
        "effective": {
            key: value for key, value in effective.items() if value is not None
        },
    }


def parse_view_preference_assignment(raw: str) -> tuple[str, Any]:
    """解析 KEY=JSON_VALUE 形式的 preference patch。"""
    key, separator, raw_value = raw.partition("=")
    key = key.strip()
    if not separator or not key:
        raise typer.BadParameter("--set 必须使用 KEY=JSON_VALUE 格式")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise typer.BadParameter(f"--set {key} 的值不是有效 JSON：{error}") from error
    return key, value


def validate_view_preference_patch(
    patch: dict[str, Any], schema: dict[str, str]
) -> None:
    """拒绝未知 preference 和明显不匹配的 JSON 值。"""
    python_types: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "Boolean": bool,
        "Float": (int, float),
        "Int": int,
        "String": str,
    }
    for key, value in patch.items():
        if key not in schema:
            raise typer.BadParameter(f"未知 View preference：{key}")
        if value is None:
            continue
        expected = python_types.get(schema[key])
        if expected is not None and (
            not isinstance(value, expected)
            or schema[key] in {"Float", "Int"}
            and isinstance(value, bool)
        ):
            raise typer.BadParameter(f"View preference {key} 需要 {schema[key]} 值")


def load_view_preference_patch(
    assignments: list[str], patch_file: Path | None
) -> dict[str, Any]:
    """合并 JSON patch file 与可重复的 --set；--set 后写并覆盖同名 key。"""
    patch: dict[str, Any] = {}
    if patch_file is not None:
        try:
            loaded = json.loads(patch_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LinearError(
                f"无法读取 preference patch {patch_file}：{error}"
            ) from error
        if not isinstance(loaded, dict):
            raise typer.BadParameter("preference patch 顶层必须是 JSON object")
        patch.update(loaded)
    for assignment in assignments:
        key, value = parse_view_preference_assignment(assignment)
        patch[key] = value
    if not patch:
        raise typer.BadParameter("至少提供一个 --set 或 --patch-file")
    return patch


config_app = typer.Typer(no_args_is_help=True, help="管理本地认证配置。")
auth_app = typer.Typer(no_args_is_help=True, help="登录或修复 Linear 认证。")
team_app = typer.Typer(no_args_is_help=True, help="查询和管理 Team。")
team_automation_app = typer.Typer(no_args_is_help=True, help="查询和管理 Team 自动化。")
issue_app = typer.Typer(no_args_is_help=True, help="查询和管理 Issue。")
label_app = typer.Typer(no_args_is_help=True, help="查询和管理 Issue Label。")
workflow_state_app = typer.Typer(
    no_args_is_help=True, help="查询和管理 workflow state。"
)
issue_comment_app = typer.Typer(no_args_is_help=True, help="查询和创建 Issue 评论。")
issue_relation_app = typer.Typer(no_args_is_help=True, help="管理 Issue 关系。")
view_app = typer.Typer(no_args_is_help=True, help="查询和管理 Custom View。")
view_preferences_app = typer.Typer(
    no_args_is_help=True, help="查询和管理 Custom View 的个人展示偏好。"
)
api_app = typer.Typer(no_args_is_help=True, help="调用尚未封装的 Linear GraphQL API。")
app.add_typer(config_app, name="config")
app.add_typer(auth_app, name="auth")
app.add_typer(team_app, name="team")
team_app.add_typer(team_automation_app, name="automation")
app.add_typer(issue_app, name="issue")
app.add_typer(label_app, name="label")
app.add_typer(workflow_state_app, name="workflow-state")
issue_app.add_typer(issue_comment_app, name="comment")
issue_app.add_typer(issue_relation_app, name="relation")
app.add_typer(view_app, name="view")
view_app.add_typer(view_preferences_app, name="preferences")
app.add_typer(api_app, name="api")


@api_app.command("graphql")
def api_graphql(
    query_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    variables_file: Annotated[
        Path | None, typer.Option("--variables-file", exists=True, dir_okay=False)
    ] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    allow_mutation: Annotated[bool, typer.Option("--allow-mutation")] = False,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """执行文件中的单个 GraphQL operation；mutation 需要双重确认。"""
    try:
        query = query_file.read_text(encoding="utf-8")
    except OSError as error:
        raise LinearError(f"无法读取 GraphQL 文件 {query_file}：{error}") from error
    try:
        document = parse(query)
    except GraphQLError as error:
        raise LinearError(f"Linear GraphQL 文档错误：{error}") from error
    operations = [
        definition
        for definition in document.definitions
        if isinstance(definition, OperationDefinitionNode)
    ]
    if len(operations) != 1:
        raise typer.BadParameter("GraphQL 文件必须且只能包含一个 operation")
    operation = operations[0].operation
    if operation is OperationType.SUBSCRIPTION:
        raise typer.BadParameter("不支持 GraphQL subscription")
    if operation is OperationType.MUTATION and not (allow_mutation and yes):
        raise typer.BadParameter(
            "GraphQL mutation 必须同时提供 --allow-mutation 和 --yes"
        )

    variables: dict[str, Any] = {}
    if variables_file is not None:
        try:
            loaded_variables = json.loads(variables_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LinearError(
                f"无法读取 variables JSON {variables_file}：{error}"
            ) from error
        if not isinstance(loaded_variables, dict):
            raise typer.BadParameter("variables JSON 顶层必须是 object")
        variables = loaded_variables
    emit(get_client(endpoint).query(query, variables))


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
    update_config({"auth_type": auth_type, "token": token}, path)
    emit({"authType": auth_type, "config": str(path), "saved": True})


@config_app.command("set-default-team")
def config_set_default_team(
    team: Annotated[str, typer.Argument()],
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """验证并保存默认 Team key。"""
    team = team.strip()
    if not team:
        raise typer.BadParameter("默认 Team 不能为空")
    path = config_path.expanduser()
    resolved = resolve_team(get_client(endpoint, path), team)
    update_config({"default_team": resolved["key"]}, path)
    emit({"config": str(path), "defaultTeam": resolved, "saved": True})


@config_app.command("clear-default-team")
def config_clear_default_team(
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    """清除可选默认 Team，保留认证配置。"""
    path = config_path.expanduser()
    config = load_config(path)
    removed = config.pop("default_team", None) is not None
    save_config(config, path)
    emit({"config": str(path), "cleared": removed})


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
    update_config({"auth_type": "api-key", "token": token}, path)
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
    update_config(
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


def read_comment(client: LinearClient, comment_id: str) -> dict[str, Any]:
    """按 UUID 回读 Comment。"""
    data = client.query(
        f"query Comment($id: String!) {{ comment(id: $id) {{ {COMMENT_FIELDS} }} }}",
        {"id": comment_id},
    )
    comment = data.get("comment")
    if not comment:
        raise LinearError(f"找不到 Linear Comment {comment_id}")
    return comment


@app.command("doctor")
def doctor(
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    team: Annotated[str | None, typer.Option("--team")] = None,
) -> None:
    """验证认证、workspace 与目标 Team 的只读能力。"""
    client = get_client(endpoint)
    data = read_identity(client)
    selected_team = (
        team.strip() if team and team.strip() else default_team_from_config()
    )
    if selected_team:
        data["team"] = resolve_team(client, selected_team)
    emit(data)


@team_app.command("show")
def team_show(
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """读取 Team 的状态、Cycle、Label 与 Project 候选。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
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


@workflow_state_app.command("list")
def workflow_state_list(
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """列出目标 Team 的 workflow states。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    emit(list_workflow_states(client, resolved["id"]))


@workflow_state_app.command("create")
def workflow_state_create(
    name: Annotated[str, typer.Option("--name")],
    state_type: Annotated[
        Literal["backlog", "unstarted", "started", "completed", "canceled"],
        typer.Option("--type"),
    ],
    team: Annotated[str | None, typer.Option("--team")] = None,
    color: Annotated[str, typer.Option("--color")] = "#95a2b3",
    description: Annotated[str | None, typer.Option("--description")] = None,
    position: Annotated[float | None, typer.Option("--position")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或创建 Team workflow state，并在写入后回读。"""
    name = name.strip()
    if not name:
        raise typer.BadParameter("--name 不能为空")
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    existing = [
        state
        for state in list_workflow_states(client, resolved["id"])
        if state["name"] == name
    ]
    if existing:
        raise LinearError(f"Workflow state {name!r} 已存在于 Team {resolved['key']}")
    fields = compact_input(
        {
            "name": name,
            "type": state_type,
            "teamId": resolved["id"],
            "color": color,
            "description": description,
            "position": position,
        }
    )
    if not yes:
        emit({"action": "workflowStateCreate", "input": fields, "preview": True})
        return
    result = client.query(
        """
        mutation CreateWorkflowState($input: WorkflowStateCreateInput!) {
          workflowStateCreate(input: $input) {
            success
            workflowState { id }
          }
        }
        """,
        {"input": fields},
    )["workflowStateCreate"]
    if not result["success"]:
        raise LinearError("workflowStateCreate 返回 success=false")
    emit(resolve_workflow_state(client, resolved["id"], result["workflowState"]["id"]))


@workflow_state_app.command("update")
def workflow_state_update(
    state: Annotated[str, typer.Argument()],
    team: Annotated[str | None, typer.Option("--team")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    color: Annotated[str | None, typer.Option("--color")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    clear_description: Annotated[bool, typer.Option("--clear-description")] = False,
    position: Annotated[float | None, typer.Option("--position")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或更新 Team workflow state，并在写入后回读。"""
    if description is not None and clear_description:
        raise typer.BadParameter("--description 与 --clear-description 不能同时使用")
    if name is not None:
        name = name.strip()
        if not name:
            raise typer.BadParameter("--name 不能为空")
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    before = resolve_workflow_state(client, resolved["id"], state)
    if before["type"] == "duplicate":
        raise LinearError("Linear 保留的 Duplicate workflow state 不支持更新")
    fields = compact_input(
        {
            "name": name,
            "color": color,
            "description": None if clear_description else description,
            "position": position,
        }
    )
    if clear_description:
        fields["description"] = None
    if not fields:
        raise typer.BadParameter("至少提供一个 workflow state 更新字段")
    if not yes:
        emit(
            {
                "action": "workflowStateUpdate",
                "before": before,
                "input": fields,
                "preview": True,
            }
        )
        return
    result = client.query(
        """
        mutation UpdateWorkflowState(
          $id: String!
          $input: WorkflowStateUpdateInput!
        ) {
          workflowStateUpdate(id: $id, input: $input) {
            success
            workflowState { id }
          }
        }
        """,
        {"id": before["id"], "input": fields},
    )["workflowStateUpdate"]
    if not result["success"]:
        raise LinearError("workflowStateUpdate 返回 success=false")
    emit(resolve_workflow_state(client, resolved["id"], before["id"]))


@label_app.command("list")
def label_list(
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """列出目标 Team 可用的 Team 与 workspace Labels。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    labels = [
        label
        for label in list_labels(client)
        if label.get("team") is None or label["team"]["id"] == resolved["id"]
    ]
    emit(labels)


@label_app.command("get")
def label_get(
    label: Annotated[str, typer.Argument()],
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """按 UUID 或名称精确回读 Label。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    emit(resolve_label(client, label, resolved["id"]))


@label_app.command("create")
def label_create(
    name: Annotated[str, typer.Option("--name")],
    team: Annotated[str | None, typer.Option("--team")] = None,
    workspace: Annotated[bool, typer.Option("--workspace")] = False,
    description: Annotated[str | None, typer.Option("--description")] = None,
    color: Annotated[str | None, typer.Option("--color")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或创建 Team 或 workspace Label，并在写入后回读。"""
    name = name.strip()
    if not name:
        raise typer.BadParameter("--name 不能为空")
    if workspace and team is not None:
        raise typer.BadParameter("--workspace 与 --team 不能同时使用")
    client = get_client(endpoint)
    resolved = None if workspace else resolve_team(client, select_team(team))
    team_id = resolved["id"] if resolved else None
    existing = [
        label
        for label in list_labels(client)
        if label["name"] == name
        and (
            (workspace and label.get("team") is None)
            or (
                resolved is not None
                and label.get("team") is not None
                and label["team"]["id"] == team_id
            )
        )
    ]
    if existing:
        scope = "workspace" if workspace else f"Team {resolved['key']}"
        raise LinearError(f"Issue Label {name!r} 已存在于 {scope}")
    fields = compact_input(
        {
            "name": name,
            "teamId": team_id,
            "description": description,
            "color": color,
        }
    )
    if not yes:
        emit({"action": "issueLabelCreate", "input": fields, "preview": True})
        return
    result = client.query(
        """
        mutation CreateIssueLabel($input: IssueLabelCreateInput!) {
          issueLabelCreate(input: $input) { success issueLabel { id } }
        }
        """,
        {"input": fields},
    )["issueLabelCreate"]
    if not result["success"]:
        raise LinearError("issueLabelCreate 返回 success=false")
    emit(resolve_label(client, result["issueLabel"]["id"], team_id))


@label_app.command("update")
def label_update(
    label: Annotated[str, typer.Argument()],
    team: Annotated[str | None, typer.Option("--team")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    clear_description: Annotated[bool, typer.Option("--clear-description")] = False,
    color: Annotated[str | None, typer.Option("--color")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或更新 Label，并在写入后回读。"""
    if description is not None and clear_description:
        raise typer.BadParameter("--description 与 --clear-description 不能同时使用")
    if name is not None:
        name = name.strip()
        if not name:
            raise typer.BadParameter("--name 不能为空")
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    before = resolve_label(client, label, resolved["id"])
    fields = compact_input(
        {
            "name": name,
            "description": None if clear_description else description,
            "color": color,
        }
    )
    if clear_description:
        fields["description"] = None
    if not fields:
        raise typer.BadParameter("至少提供一个 Label 更新字段")
    if not yes:
        emit(
            {
                "action": "issueLabelUpdate",
                "before": before,
                "input": fields,
                "preview": True,
            }
        )
        return
    result = client.query(
        """
        mutation UpdateIssueLabel($id: String!, $input: IssueLabelUpdateInput!) {
          issueLabelUpdate(id: $id, input: $input) { success issueLabel { id } }
        }
        """,
        {"id": before["id"], "input": fields},
    )["issueLabelUpdate"]
    if not result["success"]:
        raise LinearError("issueLabelUpdate 返回 success=false")
    emit(resolve_label(client, before["id"], resolved["id"]))


@label_app.command("delete")
def label_delete(
    label: Annotated[str, typer.Argument()],
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或删除 Label；删除会同时移除已有 Issue 关联。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    before = resolve_label(client, label, resolved["id"])
    if not yes:
        emit(
            {
                "action": "issueLabelDelete",
                "before": before,
                "preview": True,
            }
        )
        return
    result = client.query(
        """
        mutation DeleteIssueLabel($id: String!) {
          issueLabelDelete(id: $id) { success }
        }
        """,
        {"id": before["id"]},
    )["issueLabelDelete"]
    if not result["success"]:
        raise LinearError("issueLabelDelete 返回 success=false")
    remaining = [item for item in list_labels(client) if item["id"] == before["id"]]
    if remaining:
        raise LinearError("Label 删除后仍可回读")
    emit({"deleted": True, "label": before})


@team_automation_app.command("show")
def team_automation_show(
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """读取 Team 的自动关闭与自动归档设置。"""
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    emit(read_team_automations(client, resolved["id"]))


@team_automation_app.command("update")
def team_automation_update(
    team: Annotated[str | None, typer.Option("--team")] = None,
    auto_archive_months: Annotated[
        float | None, typer.Option("--auto-archive-months", min=1)
    ] = None,
    disable_auto_archive: Annotated[
        bool, typer.Option("--disable-auto-archive")
    ] = False,
    auto_close_months: Annotated[
        float | None, typer.Option("--auto-close-months", min=1)
    ] = None,
    disable_auto_close: Annotated[bool, typer.Option("--disable-auto-close")] = False,
    auto_close_state: Annotated[str | None, typer.Option("--auto-close-state")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或更新 Team 的自动关闭与自动归档设置，并回读。"""
    if auto_archive_months is not None and disable_auto_archive:
        raise typer.BadParameter(
            "--auto-archive-months 与 --disable-auto-archive 不能同时使用"
        )
    if auto_close_months is not None and disable_auto_close:
        raise typer.BadParameter(
            "--auto-close-months 与 --disable-auto-close 不能同时使用"
        )
    if auto_close_state is not None and disable_auto_close:
        raise typer.BadParameter(
            "--auto-close-state 与 --disable-auto-close 不能同时使用"
        )

    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    before = read_team_automations(client, resolved["id"])
    fields: dict[str, Any] = {}
    if auto_archive_months is not None or disable_auto_archive:
        fields["autoArchivePeriod"] = (
            None if disable_auto_archive else auto_archive_months
        )
    if auto_close_months is not None or disable_auto_close:
        fields["autoClosePeriod"] = None if disable_auto_close else auto_close_months
    if auto_close_state is not None:
        state = resolve_team_state(client, resolved["id"], auto_close_state)
        fields["autoCloseStateId"] = state["id"]
    if not fields:
        raise typer.BadParameter("至少提供一个自动化更新字段")
    if not yes:
        emit(
            {
                "action": "teamUpdate",
                "before": before,
                "input": fields,
                "preview": True,
            }
        )
        return
    result = client.query(
        """
        mutation UpdateTeamAutomations($id: String!, $input: TeamUpdateInput!) {
          teamUpdate(id: $id, input: $input) { success team { id } }
        }
        """,
        {"id": resolved["id"], "input": fields},
    )["teamUpdate"]
    if not result["success"]:
        raise LinearError("teamUpdate 返回 success=false")
    emit(read_team_automations(client, resolved["id"]))


@issue_app.command("get")
def issue_get(
    issue_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """回读一个 Issue。"""
    emit(read_issue(get_client(endpoint), issue_id))


@issue_app.command("list")
def issue_list(
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    first: Annotated[int, typer.Option(min=1, max=250)] = 100,
    fields: Annotated[
        str | None,
        typer.Option(
            "--fields",
            help=(
                "逗号分隔的 Issue 字段；省略时返回完整默认字段。支持："
                + ", ".join(ISSUE_FIELD_SELECTIONS)
            ),
        ),
    ] = None,
) -> None:
    """列出目标 Team 的近期 Issue。"""
    selected_fields = select_issue_fields(fields)
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    data = client.query(
        f"""
        query Issues($id: ID!, $first: Int!) {{
          issues(
            filter: {{ team: {{ id: {{ eq: $id }} }} }}
            first: $first
            orderBy: updatedAt
          ) {{ nodes {{ {selected_fields} }} }}
        }}
        """,
        {"id": resolved["id"], "first": first},
    )
    emit(data["issues"]["nodes"])


@issue_app.command("search")
def issue_search(
    term: Annotated[str, typer.Argument()],
    team: Annotated[str | None, typer.Option("--team")] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    first: Annotated[int, typer.Option(min=1, max=250)] = 50,
    after: Annotated[str | None, typer.Option()] = None,
    include_comments: Annotated[
        bool, typer.Option("--include-comments/--no-include-comments")
    ] = True,
    include_archived: Annotated[bool, typer.Option("--include-archived")] = False,
) -> None:
    """在目标 Team 的 Issue 标题、描述和可选评论中搜索。"""
    term = term.strip()
    if not term:
        raise typer.BadParameter("搜索词不能为空")
    client = get_client(endpoint)
    resolved = resolve_team(client, select_team(team))
    data = client.query(
        f"""
        query SearchIssues(
          $term: String!
          $filter: IssueFilter
          $first: Int!
          $after: String
          $includeComments: Boolean!
          $includeArchived: Boolean!
        ) {{
          searchIssues(
            term: $term
            filter: $filter
            first: $first
            after: $after
            includeComments: $includeComments
            includeArchived: $includeArchived
          ) {{
            totalCount
            pageInfo {{ hasNextPage endCursor }}
            nodes {{ {ISSUE_FIELDS} }}
          }}
        }}
        """,
        {
            "term": term,
            "filter": {"team": {"id": {"eq": resolved["id"]}}},
            "first": first,
            "after": after,
            "includeComments": include_comments,
            "includeArchived": include_archived,
        },
    )
    emit(data["searchIssues"])


@issue_comment_app.command("list")
def comment_list(
    issue_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    first: Annotated[int, typer.Option(min=1, max=250)] = 100,
) -> None:
    """按创建时间正序列出 Issue 的 Comments。"""
    client = get_client(endpoint)
    issue = read_issue(client, issue_id)
    data = client.query(
        f"""
        query Comments($id: String!, $first: Int!) {{
          issue(id: $id) {{
            id identifier
            comments(first: $first) {{ nodes {{ {COMMENT_FIELDS} }} }}
          }}
        }}
        """,
        {"id": issue["id"], "first": first},
    )
    resolved = data.get("issue")
    if not resolved:
        raise LinearError(f"找不到 Linear Issue {issue_id}")
    comments = sorted(
        resolved["comments"]["nodes"], key=lambda comment: comment["createdAt"]
    )
    emit(
        {
            "issue": {"id": resolved["id"], "identifier": resolved["identifier"]},
            "comments": comments,
        }
    )


@issue_comment_app.command("create")
def comment_create(
    issue_id: Annotated[str, typer.Argument()],
    body_file: Annotated[Path, typer.Option("--body-file")],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    codex_resume: Annotated[
        bool, typer.Option("--codex-resume/--no-codex-resume")
    ] = True,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """从 UTF-8 文件预览或创建 Comment，默认附上 Codex 恢复入口。"""
    try:
        body = body_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise typer.BadParameter(
            f"无法读取 --body-file {body_file}：{error}"
        ) from error
    if not body:
        raise typer.BadParameter("--body-file 内容不能为空")
    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if codex_resume and thread_id:
        footer = CODEX_RESUME_FOOTER_TEMPLATE.format(thread_id=thread_id)
        if footer not in body:
            body = f"{body}\n\n{footer}"

    client = get_client(endpoint)
    issue = read_issue(client, issue_id)
    fields = {"issueId": issue["id"], "body": body}
    if not yes:
        emit(
            {
                "action": "commentCreate",
                "issue": {
                    "id": issue["id"],
                    "identifier": issue["identifier"],
                    "title": issue["title"],
                },
                "input": fields,
                "preview": True,
            }
        )
        return
    data = client.query(
        """
        mutation CreateComment($input: CommentCreateInput!) {
          commentCreate(input: $input) { success comment { id } }
        }
        """,
        {"input": fields},
    )["commentCreate"]
    if not data["success"]:
        raise LinearError("commentCreate 返回 success=false")
    emit(
        {
            "issue": {
                "id": issue["id"],
                "identifier": issue["identifier"],
                "title": issue["title"],
            },
            "comment": read_comment(client, data["comment"]["id"]),
        }
    )


def compact_input(values: dict[str, Any]) -> dict[str, Any]:
    """移除 CLI 未提供的可选字段。"""
    return {key: value for key, value in values.items() if value is not None}


def load_description(
    description: str | None, description_file: Path | None
) -> str | None:
    """读取内联或文件形式的 Issue 描述，并拒绝同时指定。"""
    if description is not None and description_file is not None:
        raise typer.BadParameter("--description 与 --description-file 不能同时使用")
    if description_file is None:
        return description
    try:
        return description_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise typer.BadParameter(
            f"无法读取 --description-file {description_file}：{error}"
        ) from error


def validate_create_due_date(due_date: str | None, no_due_date: bool) -> str | None:
    """校验创建 Issue 时必须显式选择截止日期或无截止日期。"""
    if due_date is not None and no_due_date:
        raise typer.BadParameter("--due-date 与 --no-due-date 不能同时使用")
    if due_date is None and not no_due_date:
        raise typer.BadParameter("必须提供 --due-date 或显式使用 --no-due-date")
    if due_date is not None:
        try:
            parsed = date.fromisoformat(due_date)
        except ValueError as error:
            raise typer.BadParameter("--due-date 必须使用 YYYY-MM-DD 格式") from error
        if parsed.isoformat() != due_date:
            raise typer.BadParameter("--due-date 必须使用 YYYY-MM-DD 格式")
    return due_date


def resolve_create_assignee(
    client: LinearClient,
    assignee_id: str | None,
    no_assignee: bool,
) -> str | None:
    """创建 Issue 时默认使用当前用户，并支持显式不分配。"""
    if assignee_id is not None and no_assignee:
        raise typer.BadParameter("--assignee-id 与 --no-assignee 不能同时使用")
    if no_assignee:
        return None
    if assignee_id is not None:
        return assignee_id
    return read_identity(client)["viewer"]["id"]


@issue_app.command("create")
def issue_create(
    title: Annotated[str, typer.Option()],
    team: Annotated[str | None, typer.Option("--team")] = None,
    description: Annotated[str | None, typer.Option()] = None,
    description_file: Annotated[
        Path | None,
        typer.Option("--description-file", exists=True, dir_okay=False),
    ] = None,
    state_id: Annotated[str | None, typer.Option()] = None,
    priority: Annotated[int | None, typer.Option(min=0, max=4)] = None,
    cycle_id: Annotated[str | None, typer.Option()] = None,
    project_id: Annotated[str | None, typer.Option()] = None,
    parent_id: Annotated[str | None, typer.Option()] = None,
    due_date: Annotated[str | None, typer.Option()] = None,
    no_due_date: Annotated[bool, typer.Option("--no-due-date")] = False,
    label_id: Annotated[list[str] | None, typer.Option()] = None,
    assignee_id: Annotated[str | None, typer.Option()] = None,
    no_assignee: Annotated[bool, typer.Option("--no-assignee")] = False,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或创建 Issue，并在写入后回读。"""
    description = load_description(description, description_file)
    due_date = validate_create_due_date(due_date, no_due_date)
    client = get_client(endpoint)
    assignee_id = resolve_create_assignee(client, assignee_id, no_assignee)
    resolved = resolve_team(client, select_team(team))
    if state_id is None:
        state_id = resolve_workflow_state(client, resolved["id"], "Todo")["id"]
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


@issue_app.command("update")
def issue_update(
    issue_id: Annotated[str, typer.Argument()],
    title: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str | None, typer.Option()] = None,
    description_file: Annotated[
        Path | None,
        typer.Option("--description-file", exists=True, dir_okay=False),
    ] = None,
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
    description = load_description(description, description_file)
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


@issue_app.command("archive")
def issue_archive(
    issue_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或归档 Issue，并在写入后回读。"""
    client = get_client(endpoint)
    before = read_issue(client, issue_id)
    if not yes:
        emit({"action": "issueArchive", "before": before, "preview": True})
        return
    result = client.query(
        """
        mutation ArchiveIssue($id: String!) {
          issueArchive(id: $id) { success }
        }
        """,
        {"id": before["id"]},
    )["issueArchive"]
    if not result["success"]:
        raise LinearError("issueArchive 返回 success=false")
    emit(read_issue(client, before["id"]))


@issue_app.command("restore")
def issue_restore(
    issue_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或恢复已归档或最近删除的 Issue，并回读。"""
    client = get_client(endpoint)
    before = read_issue(client, issue_id)
    if not yes:
        emit({"action": "issueUnarchive", "before": before, "preview": True})
        return
    result = client.query(
        """
        mutation RestoreIssue($id: String!) {
          issueUnarchive(id: $id) { success }
        }
        """,
        {"id": before["id"]},
    )["issueUnarchive"]
    if not result["success"]:
        raise LinearError("issueUnarchive 返回 success=false")
    emit(read_issue(client, before["id"]))


@issue_app.command("delete")
def issue_delete(
    issue_id: Annotated[str, typer.Argument()],
    permanent: Annotated[bool, typer.Option("--permanent")] = False,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """预览或删除 Issue；默认可恢复 30 天，永久删除需要管理员权限。"""
    client = get_client(endpoint)
    before = read_issue(client, issue_id)
    if not yes:
        emit(
            {
                "action": "issueDelete",
                "before": before,
                "permanent": permanent,
                "preview": True,
            }
        )
        return
    result = client.query(
        """
        mutation DeleteIssue($id: String!, $permanentlyDelete: Boolean) {
          issueDelete(id: $id, permanentlyDelete: $permanentlyDelete) { success }
        }
        """,
        {"id": before["id"], "permanentlyDelete": permanent},
    )["issueDelete"]
    if not result["success"]:
        raise LinearError("issueDelete 返回 success=false")
    emit(
        {
            "deleted": True,
            "issue": before,
            "permanent": permanent,
            "recoverableForDays": 0 if permanent else 30,
        }
    )


@issue_relation_app.command("create")
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


@view_preferences_app.command("get")
def view_preferences_get(
    view_id: Annotated[str, typer.Argument()],
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
) -> None:
    """读取当前用户在一个 Issue Custom View 上的显式与有效偏好。"""
    emit(read_view_preferences(get_client(endpoint), view_id))


@view_preferences_app.command("update")
def view_preferences_update(
    view_id: Annotated[str, typer.Argument()],
    set_values: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            help="可重复的 KEY=JSON_VALUE；null 删除显式覆盖。",
        ),
    ] = None,
    patch_file: Annotated[
        Path | None,
        typer.Option(
            "--patch-file",
            exists=True,
            dir_okay=False,
            help="JSON object patch；同名 --set 值优先。",
        ),
    ] = None,
    endpoint: Annotated[str, typer.Option()] = DEFAULT_ENDPOINT,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """合并更新当前用户的 View preferences；null 删除显式覆盖。"""
    client = get_client(endpoint)
    schema = read_view_preference_schema(client)
    patch = load_view_preference_patch(set_values or [], patch_file)
    validate_view_preference_patch(patch, schema)
    before = read_view_preferences(client, view_id, schema)
    after = dict(before["explicit"])
    for key, value in patch.items():
        if value is None:
            after.pop(key, None)
        else:
            after[key] = value
    action = (
        "viewPreferencesUpdate" if before["preferenceId"] else "viewPreferencesCreate"
    )
    preview = {
        "action": action,
        "view": before["view"],
        "before": before["explicit"],
        "patch": patch,
        "after": after,
        "preview": True,
    }
    if not yes:
        emit(preview)
        return
    if before["preferenceId"]:
        result = client.query(
            """
            mutation UpdateViewPreferences(
              $id: String!, $input: ViewPreferencesUpdateInput!
            ) {
              viewPreferencesUpdate(id: $id, input: $input) {
                success viewPreferences { id }
              }
            }
            """,
            {
                "id": before["preferenceId"],
                "input": {"preferences": after},
            },
        )["viewPreferencesUpdate"]
    else:
        result = client.query(
            """
            mutation CreateViewPreferences($input: ViewPreferencesCreateInput!) {
              viewPreferencesCreate(input: $input) {
                success viewPreferences { id }
              }
            }
            """,
            {
                "input": {
                    "type": "user",
                    "viewType": "customView",
                    "customViewId": before["view"]["id"],
                    "preferences": after,
                }
            },
        )["viewPreferencesCreate"]
    if not result["success"]:
        raise LinearError(f"{action} 返回 success=false")
    emit(read_view_preferences(client, before["view"]["id"], schema))


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
              id identifier title priority dueDate completedAt canceledAt url
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

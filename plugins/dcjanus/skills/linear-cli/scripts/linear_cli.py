#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.28,<1",
#     "tomli-w>=1.2.0",
#     "typer>=0.16,<1",
# ]
# ///

"""通过 Linear 官方 GraphQL API 管理 Linear 资源。"""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import tomli_w
import tomllib
import typer

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
DEFAULT_ENDPOINT = "https://api.linear.app/graphql"
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


def settings_from_env(endpoint: str) -> Settings:
    """从环境变量或 XDG 配置读取认证信息。"""
    api_key = os.environ.get("LINEAR_API_KEY")
    access_token = os.environ.get("LINEAR_ACCESS_TOKEN")
    if api_key and access_token:
        raise LinearError("LINEAR_API_KEY 与 LINEAR_ACCESS_TOKEN 只能设置一个")
    if access_token:
        return Settings(endpoint, access_token, True)
    if api_key:
        return Settings(endpoint, api_key, False)
    config_path = Path(
        os.environ.get("LINEAR_CONFIG", DEFAULT_CONFIG_PATH)
    ).expanduser()
    if config_path.exists():
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise LinearError(f"无法读取配置 {config_path}：{error}") from error
        token = config.get("token")
        auth_type = config.get("auth_type", "api-key")
        if token and auth_type in {"api-key", "oauth"}:
            return Settings(endpoint, str(token), auth_type == "oauth")
    raise LinearError("缺少 Linear 凭据；设置环境变量或运行 config set --prompt-token")


class LinearClient:
    """最小 Linear GraphQL 客户端。"""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        authorization = f"Bearer {settings.token}" if settings.oauth else settings.token
        self.client = httpx.Client(
            headers={"Authorization": authorization},
            timeout=30,
            transport=transport,
        )
        self.endpoint = settings.endpoint

    def query(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        """执行 GraphQL 请求并拒绝部分成功响应。"""
        try:
            response = self.client.post(
                self.endpoint,
                json={"query": query, "variables": variables or {}},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise LinearError(f"Linear 请求失败：{error}") from error
        if payload.get("errors"):
            messages = "; ".join(
                str(item.get("message", item)) for item in payload["errors"]
            )
            raise LinearError(f"Linear GraphQL 错误：{messages}")
        if "data" not in payload:
            raise LinearError("Linear 响应缺少 data")
        return payload["data"]


def emit(payload: Any) -> None:
    """输出稳定 UTF-8 JSON。"""
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def get_client(endpoint: str) -> LinearClient:
    """创建命令行客户端。"""
    return LinearClient(settings_from_env(endpoint))


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
view_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(view_app, name="view")


@config_app.command("set")
def config_set(
    auth_type: Annotated[Literal["api-key", "oauth"], typer.Option()] = "api-key",
    prompt_token: Annotated[bool, typer.Option("--prompt-token")] = False,
    config_path: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG_PATH,
) -> None:
    """安全保存 API key 或已获取的 OAuth access token。"""
    if not prompt_token:
        raise typer.BadParameter(
            "必须使用 --prompt-token，避免 token 进入 shell history"
        )
    token = getpass.getpass("Linear token: ").strip()
    if not token:
        raise typer.BadParameter("token 不能为空")
    path = config_path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(tomli_w.dumps({"auth_type": auth_type, "token": token}))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)
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
    if data.get("token"):
        data["token"] = "********"
    emit({"config": str(path), "exists": True, **data})


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
    data = client.query(
        """
        query Doctor {
          viewer { id name email }
          organization { id name urlKey }
        }
        """
    )
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

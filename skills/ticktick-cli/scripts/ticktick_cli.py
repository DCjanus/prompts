#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpxyz>=0.28.2",
#     "typer>=0.20.1",
#     "pydantic>=2.12.5",
#     "rich>=14.2.0",
# ]
# ///

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

ENV_TIMEOUT = "TICKTICK_TIMEOUT"
# 该脚本主要提供给 AI Agent 调用，人类 CLI 使用只是顺带支持。
SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ticktick_api_client import (  # noqa: E402
    DEFAULT_BASE_URL,
    ChecklistItem,
    ProjectCreate,
    ProjectUpdate,
    TaskCreate,
    TaskUpdate,
    TicktickApiClient,
    TicktickApiError,
)
from ticktick_auth import (  # noqa: E402
    ENV_TOKEN_FILE,
    AuthError,
    default_token_file,
    load_token_payload,
    login,
    remove_stored_token,
    token_expiry_info,
)

app = typer.Typer(no_args_is_help=True)
auth_app = typer.Typer(no_args_is_help=True, help="认证相关操作。")
project_app = typer.Typer(no_args_is_help=True, help="项目相关操作。")
task_app = typer.Typer(no_args_is_help=True, help="任务相关操作。")
console = Console()


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AppState(BaseModel):
    timeout: str
    json_output: bool


class TicktickRegion(str, Enum):
    dida365 = "dida365"
    ticktick = "ticktick"


def api_base_url_for_region(region: TicktickRegion) -> str:
    if region is TicktickRegion.ticktick:
        return "https://api.ticktick.com/open/v1"
    return DEFAULT_BASE_URL


def region_for_api_base_url(base_url: str) -> str:
    return "ticktick" if "api.ticktick.com" in base_url.lower() else "dida365"


def resolve_auth(ctx: typer.Context) -> tuple[str, str, str, dict[str, Any] | None]:
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("Client config not initialized.")
    payload = load_token_payload()
    if payload is None:
        raise ApiError(
            "缺少本地 token。请先运行 `./scripts/ticktick_cli.py auth login`。"
        )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ApiError(f"Invalid token file payload: {default_token_file()}")
    base_url = payload.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        base_url = DEFAULT_BASE_URL
    return token, base_url, region_for_api_base_url(base_url), payload


def get_client(ctx: typer.Context) -> TicktickApiClient:
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("Client config not initialized.")
    token, base_url, _, _ = resolve_auth(ctx)
    timeout_raw = state.timeout
    timeout_seconds = parse_timeout(str(timeout_raw))
    if timeout_seconds <= 0:
        raise ApiError("Timeout must be greater than 0.")
    return TicktickApiClient(
        token=token,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def render_payload(payload: Any) -> None:
    if isinstance(payload, list):
        data = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in payload
        ]
        console.print_json(data=data)
        return
    if hasattr(payload, "model_dump"):
        console.print_json(data=payload.model_dump())
        return
    console.print_json(data=payload)


def render_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def render_kv_table(title: str, data: dict[str, Any]) -> None:
    rows = [[key, "" if value is None else str(value)] for key, value in data.items()]
    render_table(title, ["field", "value"], rows)


def render_project_list(projects: list[Any]) -> None:
    rows = []
    for project in projects:
        data = project.model_dump() if hasattr(project, "model_dump") else project
        rows.append(
            [
                str(data.get("id", "")),
                str(data.get("name", "")),
                str(data.get("color", "")),
                str(data.get("closed", "")),
                str(data.get("groupId", "")),
                str(data.get("viewMode", "")),
                str(data.get("kind", "")),
                str(data.get("sortOrder", "")),
            ]
        )
    render_table(
        "Projects",
        ["id", "name", "color", "closed", "groupId", "viewMode", "kind", "sortOrder"],
        rows,
    )


def render_task_list(tasks: list[Any]) -> None:
    rows = []
    for task in tasks:
        data = task.model_dump() if hasattr(task, "model_dump") else task
        rows.append(
            [
                str(data.get("id", "")),
                str(data.get("title", "")),
                str(data.get("status", "")),
                str(data.get("priority", "")),
                str(data.get("dueDate", "")),
                str(data.get("projectId", "")),
            ]
        )
    render_table(
        "Tasks",
        ["id", "title", "status", "priority", "dueDate", "projectId"],
        rows,
    )


def render_columns_list(columns: list[Any]) -> None:
    rows = []
    for column in columns:
        data = column.model_dump() if hasattr(column, "model_dump") else column
        rows.append(
            [
                str(data.get("id", "")),
                str(data.get("name", "")),
                str(data.get("sortOrder", "")),
            ]
        )
    render_table("Columns", ["id", "name", "sortOrder"], rows)


def parse_timeout(raw: str) -> float:
    value = raw.strip().lower()
    if not value:
        raise ApiError("Timeout cannot be empty.")
    multipliers = [
        ("seconds", 1),
        ("second", 1),
        ("secs", 1),
        ("sec", 1),
        ("s", 1),
        ("minutes", 60),
        ("minute", 60),
        ("mins", 60),
        ("min", 60),
        ("m", 60),
        ("hours", 3600),
        ("hour", 3600),
        ("hrs", 3600),
        ("hr", 3600),
        ("h", 3600),
    ]
    for unit, multiplier in multipliers:
        if value.endswith(unit):
            number = value[: -len(unit)].strip()
            try:
                return float(number) * multiplier
            except ValueError as exc:
                raise ApiError(f"Invalid timeout: {raw}") from exc
    try:
        return float(value)
    except ValueError as exc:
        raise ApiError(f"Invalid timeout: {raw}") from exc


def parse_checklist_items(
    item: list[str] | None,
    item_json: str | None,
) -> list[ChecklistItem] | None:
    if item and item_json:
        raise ApiError("Use --item or --item-json, not both.")
    if item_json:
        raw = item_json
        if raw.startswith("@"):
            path = Path(raw[1:]).expanduser()
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ApiError(f"Failed to read items JSON: {path}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError("Invalid JSON for --item-json.") from exc
        if not isinstance(payload, list):
            raise ApiError("--item-json must be a JSON array.")
        items: list[ChecklistItem] = []
        for entry in payload:
            if isinstance(entry, str):
                items.append(ChecklistItem(title=entry))
                continue
            if not isinstance(entry, dict):
                raise ApiError("Each item in --item-json must be an object or string.")
            items.append(ChecklistItem.model_validate(entry))
        return items or None
    if item:
        return [ChecklistItem(title=item_title) for item_title in item]
    return None


@app.callback()
def main(
    ctx: typer.Context,
    timeout: str = typer.Option(
        "30s",
        "--timeout",
        envvar=ENV_TIMEOUT,
        help="Request timeout (e.g. 20s, 1m).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="输出 JSON 格式。",
    ),
) -> None:
    if ctx.resilient_parsing:
        return
    ctx.obj = AppState(
        timeout=timeout,
        json_output=json_output,
    )


@auth_app.command("login", help="使用官方 Dynamic OAuth 完成本地登录。")
def auth_login(
    ctx: typer.Context,
    region: TicktickRegion = typer.Option(
        TicktickRegion.dida365,
        "--region",
        help="账号区域：dida365 为中国区，ticktick 为国际版。",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="自动打开浏览器授权页。",
    ),
    timeout_seconds: int = typer.Option(
        300,
        "--timeout-seconds",
        min=30,
        help="等待浏览器授权回调的秒数；默认 5 分钟，请尽快完成登录。",
    ),
) -> None:
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("Client config not initialized.")
    base_url = api_base_url_for_region(region)
    path = login(
        base_url=base_url,
        open_browser=open_browser,
        timeout_seconds=timeout_seconds,
    )
    console.print(f"Saved token to {path}")
    payload = load_token_payload(base_url)
    if payload is not None:
        expiry = token_expiry_info(payload)
        if expiry["expires_at"]:
            console.print(f"Token expires at {expiry['expires_at']}")


@auth_app.command("doctor", help="检查当前认证配置是否可用。")
def auth_doctor(ctx: typer.Context) -> None:
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("Client config not initialized.")
    token_source = str(default_token_file())
    try:
        token, base_url, region, token_payload = resolve_auth(ctx)
    except ApiError as exc:
        raise ApiError(
            "No token found. Run `./scripts/ticktick_cli.py auth login`, "
            f"or set {ENV_TOKEN_FILE}."
        ) from exc
    client = TicktickApiClient(
        token=token,
        base_url=base_url,
        timeout_seconds=parse_timeout(state.timeout),
    )
    projects = client.list_projects()
    payload = {
        "ok": True,
        "region": region,
        "base_url": base_url,
        "token_source": token_source,
        "project_count": len(projects),
    }
    if token_payload is not None:
        payload.update(token_expiry_info(token_payload))
    if state.json_output:
        render_payload(payload)
        return
    render_kv_table("Auth", payload)


@auth_app.command("logout", help="删除本地保存的 OAuth token。")
def auth_logout() -> None:
    removed = remove_stored_token()
    console.print("Removed stored token." if removed else "No stored token found.")


@project_app.command("list", help="列出当前账号的项目。")
def project_list(ctx: typer.Context) -> None:
    client = get_client(ctx)
    projects = client.list_projects()
    if ctx.obj.json_output:
        render_payload(projects)
        return
    render_project_list(projects)


@project_app.command("get", help="根据项目 ID 获取项目详情。")
def project_get(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id"),
) -> None:
    client = get_client(ctx)
    project = client.get_project(project_id)
    if ctx.obj.json_output:
        render_payload(project)
        return
    render_kv_table("Project", project.model_dump())


@project_app.command("data", help="获取项目详情（包含未完成任务与列）。")
def project_data(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id"),
) -> None:
    client = get_client(ctx)
    data = client.get_project_data(project_id)
    if ctx.obj.json_output:
        render_payload(data)
        return
    project = data.project.model_dump() if data.project else {}
    render_kv_table("Project", project)
    render_task_list(data.tasks or [])
    render_columns_list(data.columns or [])


@project_app.command("create", help="创建项目。")
def project_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name"),
    color: str | None = typer.Option(None, "--color"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    view_mode: str | None = typer.Option(None, "--view-mode"),
    kind: str | None = typer.Option(None, "--kind"),
) -> None:
    client = get_client(ctx)
    project = client.create_project(
        ProjectCreate(
            name=name,
            color=color,
            sortOrder=sort_order,
            viewMode=view_mode,
            kind=kind,
        )
    )
    if ctx.obj.json_output:
        render_payload(project)
        return
    render_kv_table("Project", project.model_dump())


@project_app.command("update", help="更新项目。")
def project_update(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id"),
    name: str | None = typer.Option(None, "--name"),
    color: str | None = typer.Option(None, "--color"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    view_mode: str | None = typer.Option(None, "--view-mode"),
    kind: str | None = typer.Option(None, "--kind"),
) -> None:
    if not any([name, color, sort_order, view_mode, kind]):
        raise ApiError("No update fields provided.")
    client = get_client(ctx)
    project = client.update_project(
        project_id,
        ProjectUpdate(
            name=name,
            color=color,
            sortOrder=sort_order,
            viewMode=view_mode,
            kind=kind,
        ),
    )
    if ctx.obj.json_output:
        render_payload(project)
        return
    render_kv_table("Project", project.model_dump())


@project_app.command("delete", help="删除项目。")
def project_delete(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id"),
) -> None:
    client = get_client(ctx)
    client.delete_project(project_id)
    console.print("OK")


@task_app.command("get", help="根据项目 ID 与任务 ID 获取任务。")
def task_get(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id"),
    task_id: str = typer.Option(..., "--task-id"),
) -> None:
    client = get_client(ctx)
    task = client.get_task(project_id, task_id)
    if ctx.obj.json_output:
        render_payload(task)
        return
    render_kv_table("Task", task.model_dump())


@task_app.command("create", help="创建任务。")
def task_create(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title"),
    project_id: str = typer.Option(..., "--project-id"),
    content: str | None = typer.Option(None, "--content"),
    desc: str | None = typer.Option(None, "--desc"),
    is_all_day: bool | None = typer.Option(None, "--all-day"),
    start_date: str | None = typer.Option(None, "--start-date"),
    due_date: str | None = typer.Option(None, "--due-date"),
    time_zone: str | None = typer.Option(None, "--time-zone"),
    reminder: list[str] | None = typer.Option(None, "--reminder"),
    repeat_flag: str | None = typer.Option(None, "--repeat"),
    priority: int | None = typer.Option(None, "--priority"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    item: list[str] | None = typer.Option(None, "--item"),
    item_json: str | None = typer.Option(
        None,
        "--item-json",
        help="JSON array string or @path to JSON file for checklist items.",
    ),
) -> None:
    client = get_client(ctx)
    items = parse_checklist_items(item, item_json)
    task = client.create_task(
        TaskCreate(
            title=title,
            projectId=project_id,
            content=content,
            desc=desc,
            isAllDay=is_all_day,
            startDate=start_date,
            dueDate=due_date,
            timeZone=time_zone,
            reminders=reminder or None,
            repeatFlag=repeat_flag,
            priority=priority,
            sortOrder=sort_order,
            items=items or None,
        )
    )
    if ctx.obj.json_output:
        render_payload(task)
        return
    render_kv_table("Task", task.model_dump())


@task_app.command("update", help="更新任务。")
def task_update(
    ctx: typer.Context,
    task_id: str = typer.Option(..., "--task-id"),
    project_id: str = typer.Option(..., "--project-id"),
    title: str | None = typer.Option(None, "--title"),
    content: str | None = typer.Option(None, "--content"),
    desc: str | None = typer.Option(None, "--desc"),
    is_all_day: bool | None = typer.Option(None, "--all-day"),
    start_date: str | None = typer.Option(None, "--start-date"),
    due_date: str | None = typer.Option(None, "--due-date"),
    time_zone: str | None = typer.Option(None, "--time-zone"),
    reminder: list[str] | None = typer.Option(None, "--reminder"),
    repeat_flag: str | None = typer.Option(None, "--repeat"),
    priority: int | None = typer.Option(None, "--priority"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    item: list[str] | None = typer.Option(None, "--item"),
    item_json: str | None = typer.Option(
        None,
        "--item-json",
        help="JSON array string or @path to JSON file for checklist items.",
    ),
) -> None:
    if not any(
        [
            title,
            content,
            desc,
            is_all_day is not None,
            start_date,
            due_date,
            time_zone,
            reminder,
            repeat_flag,
            priority,
            sort_order,
            item,
            item_json,
        ]
    ):
        raise ApiError("No update fields provided.")
    client = get_client(ctx)
    items = parse_checklist_items(item, item_json)
    task = client.update_task(
        task_id,
        TaskUpdate(
            id=task_id,
            projectId=project_id,
            title=title,
            content=content,
            desc=desc,
            isAllDay=is_all_day,
            startDate=start_date,
            dueDate=due_date,
            timeZone=time_zone,
            reminders=reminder or None,
            repeatFlag=repeat_flag,
            priority=priority,
            sortOrder=sort_order,
            items=items or None,
        ),
    )
    if ctx.obj.json_output:
        render_payload(task)
        return
    render_kv_table("Task", task.model_dump())


@task_app.command("complete", help="完成指定任务。")
def task_complete(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id"),
    task_id: str = typer.Option(..., "--task-id"),
) -> None:
    client = get_client(ctx)
    client.complete_task(project_id, task_id)
    console.print("OK")


@task_app.command("delete", help="删除任务。")
def task_delete(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id"),
    task_id: str = typer.Option(..., "--task-id"),
) -> None:
    client = get_client(ctx)
    client.delete_task(project_id, task_id)
    console.print("OK")


app.add_typer(auth_app, name="auth")
app.add_typer(project_app, name="project")
app.add_typer(task_app, name="task")


def run() -> None:
    try:
        app()
    except (ApiError, AuthError, TicktickApiError) as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code:
            console.print(f"[red]Error:[/red] {exc} (status {status_code})")
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    run()

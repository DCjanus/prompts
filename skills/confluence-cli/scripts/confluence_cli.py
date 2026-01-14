#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "atlassian-python-api",
#     "pydantic>=2.12.5",
#     "rich",
#     "typer",
# ]
# ///
"""Confluence CLI 工具入口。"""

from __future__ import annotations

import sys
from pathlib import Path
from enum import Enum
from typing import Any, Callable

import typer
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from confluence_api_client import ConfluenceApiClient, ConfluenceConfig  # noqa: E402

app = typer.Typer(no_args_is_help=True)
space_app = typer.Typer(no_args_is_help=True, help="空间相关操作。")
page_app = typer.Typer(no_args_is_help=True, help="页面相关操作。")
console = Console()

ENV_BASE_URL = "CONFLUENCE_BASE_URL"
ENV_USERNAME = "CONFLUENCE_USERNAME"
ENV_TOKEN = "CONFLUENCE_API_TOKEN"
ENV_TIMEOUT = "CONFLUENCE_TIMEOUT"
ENV_CLOUD = "CONFLUENCE_CLOUD"
ENV_VERIFY_SSL = "CONFLUENCE_VERIFY_SSL"


class ApiError(RuntimeError):
    """CLI 运行时错误。"""


class AppState(BaseModel):
    """CLI 运行时配置。"""

    base_url: str
    username: str | None
    token: str
    timeout: str
    cloud: bool | None
    verify_ssl: bool
    json_output: bool


class BodyFormat(str, Enum):
    """Confluence body 格式枚举。"""

    storage = "storage"
    view = "view"
    export_view = "export_view"
    styled_view = "styled_view"
    editor = "editor"
    anonymous_export_view = "anonymous_export_view"


def parse_timeout(raw: str) -> float:
    """解析超时字符串为秒数。"""
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


def normalize_results(payload: Any) -> list[Any]:
    """规范化列表结果字段。"""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "results" in payload:
        results = payload.get("results")
        if isinstance(results, list):
            return results
    return []


def render_json(payload: Any) -> None:
    """渲染 JSON 输出。"""
    console.print_json(data=payload)


def render_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    """渲染表格输出。"""
    table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def render_space_list(payload: Any) -> None:
    """渲染空间列表。"""
    rows = []
    for item in normalize_results(payload):
        rows.append(
            [
                str(item.get("key", "")),
                str(item.get("name", "")),
                str(item.get("type", "")),
                str(item.get("status", "")),
            ]
        )
    render_table("Spaces", ["key", "name", "type", "status"], rows)


def render_page_list(payload: Any, title: str = "Pages") -> None:
    """渲染页面列表。"""
    rows = []
    for item in normalize_results(payload):
        space = item.get("space") or {}
        rows.append(
            [
                str(item.get("id", "")),
                str(item.get("title", "")),
                str(space.get("key", "")),
                str(item.get("type", "")),
            ]
        )
    render_table(title, ["id", "title", "space", "type"], rows)


def ensure_json_output(
    payload: Any,
    json_output: bool,
    fallback: Callable[[Any], None] | None = None,
) -> None:
    """按需输出 JSON 或表格。"""
    if json_output:
        render_json(payload)
        return
    if fallback:
        fallback(payload)
        return
    console.print(payload)


def build_expand(body_format: BodyFormat | None, expand: str | None) -> str | None:
    """构建 expand 参数。"""
    if expand:
        return expand
    if body_format:
        return f"body.{body_format.value},version,space"
    return None


def get_client(state: AppState) -> ConfluenceApiClient:
    """构建 Confluence API 客户端。"""
    timeout_seconds = parse_timeout(state.timeout)
    if timeout_seconds <= 0:
        raise ApiError("Timeout must be greater than 0.")
    return ConfluenceApiClient(
        ConfluenceConfig(
            base_url=state.base_url,
            username=state.username,
            token=state.token,
            timeout_seconds=timeout_seconds,
            cloud=state.cloud,
            verify_ssl=state.verify_ssl,
        )
    )


@app.callback()
def main(
    ctx: typer.Context,
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar=ENV_BASE_URL,
        help="Confluence 基础地址，例如 https://your-domain.atlassian.net/wiki。",
    ),
    username: str | None = typer.Option(
        None,
        "--username",
        envvar=ENV_USERNAME,
        help="登录用户名或邮箱（Cloud 常用邮箱）。",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        envvar=ENV_TOKEN,
        help="API Token 或 PAT。",
    ),
    timeout: str = typer.Option(
        "30s",
        "--timeout",
        envvar=ENV_TIMEOUT,
        help="请求超时，支持 30s/2m 等格式。",
    ),
    cloud: bool | None = typer.Option(
        None,
        "--cloud/--no-cloud",
        envvar=ENV_CLOUD,
        help="强制启用/关闭 Cloud 模式（默认自动）。",
    ),
    verify_ssl: bool | None = typer.Option(
        None,
        "--verify-ssl/--no-verify-ssl",
        envvar=ENV_VERIFY_SSL,
        help="是否校验证书（默认 True）。",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="以 JSON 输出结果。",
    ),
) -> None:
    """初始化 CLI 全局参数。"""
    if not base_url:
        raise ApiError(f"缺少 base_url，请通过 --base-url 或环境变量 {ENV_BASE_URL} 提供。")
    if not token:
        raise ApiError(f"缺少 token，请通过 --token 或环境变量 {ENV_TOKEN} 提供。")
    if cloud is None:
        cloud = True if "atlassian.net" in base_url else None
    verify_ssl_value = True if verify_ssl is None else verify_ssl
    ctx.obj = AppState(
        base_url=base_url,
        username=username,
        token=token,
        timeout=timeout,
        cloud=cloud,
        verify_ssl=verify_ssl_value,
        json_output=json_output,
    )


@space_app.command("list")
def list_spaces(
    ctx: typer.Context,
    start: int = typer.Option(0, "--start", help="分页起始索引。"),
    limit: int = typer.Option(25, "--limit", help="分页大小。"),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """列出 Confluence 空间。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    payload = client.list_spaces(start=start, limit=limit, expand=expand)
    ensure_json_output(payload, state.json_output, render_space_list)


@space_app.command("get")
def get_space(
    ctx: typer.Context,
    space_key: str = typer.Option(..., "--space-key", help="空间 key。"),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """获取空间详情。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    payload = client.get_space(space_key, expand=expand)
    ensure_json_output(payload, state.json_output)


@page_app.command("get")
def get_page(
    ctx: typer.Context,
    page_id: str = typer.Option(..., "--page-id", help="页面 ID。"),
    body_format: BodyFormat | None = typer.Option(
        None,
        "--body-format",
        help="页面正文格式。",
    ),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """按页面 ID 获取页面。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    payload = client.get_page(page_id, expand=build_expand(body_format, expand))
    ensure_json_output(payload, state.json_output)


@page_app.command("by-title")
def get_page_by_title(
    ctx: typer.Context,
    space_key: str = typer.Option(..., "--space-key", help="空间 key。"),
    title: str = typer.Option(..., "--title", help="页面标题。"),
    body_format: BodyFormat | None = typer.Option(
        None,
        "--body-format",
        help="页面正文格式。",
    ),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """按标题获取页面。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    payload = client.get_page_by_title(
        space_key,
        title,
        expand=build_expand(body_format, expand),
    )
    ensure_json_output(payload, state.json_output)


@page_app.command("children")
def get_page_children(
    ctx: typer.Context,
    page_id: str = typer.Option(..., "--page-id", help="页面 ID。"),
    start: int = typer.Option(0, "--start", help="分页起始索引。"),
    limit: int = typer.Option(25, "--limit", help="分页大小。"),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """获取子页面列表。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    payload = client.get_page_children(page_id, start=start, limit=limit, expand=expand)
    ensure_json_output(payload, state.json_output, render_page_list)


@app.command("search")
def search_cql(
    ctx: typer.Context,
    cql: str = typer.Option(..., "--cql", help="CQL 查询语句。"),
    start: int = typer.Option(0, "--start", help="分页起始索引。"),
    limit: int = typer.Option(25, "--limit", help="分页大小。"),
    body_format: BodyFormat | None = typer.Option(
        None,
        "--body-format",
        help="页面正文格式。",
    ),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """执行 CQL 搜索。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    payload = client.search_cql(
        cql,
        start=start,
        limit=limit,
        expand=build_expand(body_format, expand),
    )
    ensure_json_output(payload, state.json_output, render_page_list)


app.add_typer(space_app, name="space")
app.add_typer(page_app, name="page")


def main_entry() -> None:
    """CLI 入口。"""
    try:
        app()
    except ApiError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Unhandled error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    main_entry()

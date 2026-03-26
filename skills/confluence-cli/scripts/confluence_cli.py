#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.28.1",
#     "markdown-it-py>=4.0.0",
#     "pydantic>=2.12.5",
#     "rich>=14.1.0",
#     "typer>=0.17.4",
# ]
# ///
"""Confluence CLI 工具入口。"""

from __future__ import annotations

import base64
import html
import re
import sys
import urllib.parse
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from markdown_it import MarkdownIt
from markdown_it.token import Token
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
attachment_app = typer.Typer(no_args_is_help=True, help="附件相关操作。")
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


def render_attachment_list(payload: Any, title: str = "Attachments") -> None:
    """渲染附件列表。"""
    rows = []
    for item in normalize_results(payload):
        metadata = item.get("metadata") or {}
        extensions = item.get("extensions") or {}
        rows.append(
            [
                str(item.get("id", "")),
                str(item.get("title", "")),
                str(metadata.get("mediaType", "")),
                str(extensions.get("fileSize", "")),
            ]
        )
    render_table(title, ["id", "title", "mediaType", "fileSize"], rows)


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


MARKDOWN_PARSER = MarkdownIt("commonmark", {"html": True}).enable("table")

SUPPORTED_BLOCK_OPEN_TOKENS = {
    "blockquote_open",
    "bullet_list_open",
    "heading_open",
    "list_item_open",
    "ordered_list_open",
    "paragraph_open",
    "table_open",
    "tbody_open",
    "td_open",
    "th_open",
    "thead_open",
    "tr_open",
}

SUPPORTED_INLINE_CONTAINER_TOKENS = {
    "em_open",
    "strong_open",
}

ALLOWED_TOKEN_ATTRIBUTES = {
    "image": {"alt", "src", "title"},
    "link_open": {"href", "title"},
    "ordered_list_open": {"start"},
}


def escape_text(text: str) -> str:
    """转义普通文本。"""
    return html.escape(text, quote=False)


def strip_leading_title_heading(markdown: str) -> str:
    """移除文首第一个 ATX H1，避免与 Confluence 页面标题重复。"""
    lines = markdown.splitlines()
    first_non_empty = next((idx for idx, line in enumerate(lines) if line.strip()), None)
    if first_non_empty is None:
        return markdown
    if re.match(r"^#\s+.+$", lines[first_non_empty].strip()):
        del lines[first_non_empty]
        while first_non_empty < len(lines) and not lines[first_non_empty].strip():
            del lines[first_non_empty]
    return "\n".join(lines)


def normalize_local_attachment_target(target: str) -> str | None:
    """识别 Markdown 中的本地附件/文档链接。"""
    if target.startswith("#"):
        return None
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if target.startswith("/"):
        raise ApiError(f"Unsupported Markdown absolute path link: {target}")
    if parsed.params or parsed.query or parsed.fragment:
        raise ApiError(f"Unsupported Markdown local link with query/fragment: {target}")
    normalized_path = urllib.parse.unquote(parsed.path)
    if not normalized_path:
        raise ApiError(f"Unsupported Markdown empty local link target: {target}")
    return normalized_path


def register_attachment_reference(attachment_map: dict[str, str], raw_target: str) -> str:
    """记录 Markdown 中引用到的本地附件，并检查重名冲突。"""
    normalized_target = normalize_local_attachment_target(raw_target)
    if normalized_target is None:
        raise ApiError(f"Expected a local attachment target, got: {raw_target}")
    filename = Path(normalized_target).name
    if not filename:
        raise ApiError(f"Unsupported Markdown attachment target: {raw_target}")
    existing = attachment_map.get(filename)
    if existing is not None and existing != normalized_target:
        raise ApiError(
            f"Markdown 引用了多个同名本地附件 `{filename}`：`{existing}` 与 `{normalized_target}`。"
        )
    attachment_map[filename] = normalized_target
    return filename


def build_attachment_href(base_url: str, page_id: str, filename: str) -> str:
    """构造页面附件下载链接。"""
    encoded_filename = urllib.parse.quote(filename)
    return f"{base_url.rstrip('/')}/download/attachments/{page_id}/{encoded_filename}"


def get_token_attrs(token: Token) -> dict[str, str]:
    """读取 token 属性。"""
    return dict(token.attrs or {})


def validate_token_attributes(token: Token) -> dict[str, str]:
    """校验 token 属性，避免未处理的 Markdown 语义被静默忽略。"""
    attrs = get_token_attrs(token)
    allowed = ALLOWED_TOKEN_ATTRIBUTES.get(token.type, set())
    unsupported = sorted(set(attrs) - allowed)
    if unsupported:
        attrs = ", ".join(unsupported)
        raise ApiError(f"Unsupported Markdown attributes on token `{token.type}`: {attrs}")
    return attrs


def render_image_token(
    token: Token,
    attachment_map: dict[str, str],
    *,
    page_id: str | None,
    base_url: str | None,
) -> str:
    """渲染图片 token。"""
    attrs = validate_token_attributes(token)
    src = attrs.get("src", "")
    alt = token.content or ""
    local_target = normalize_local_attachment_target(src)
    if local_target is not None:
        filename = register_attachment_reference(attachment_map, src)
        return (
            f'<ac:image ac:alt="{html.escape(alt)}">'
            f'<ri:attachment ri:filename="{html.escape(filename)}" /></ac:image>'
        )
    rendered_attrs = [f'src="{html.escape(src)}"']
    if alt:
        rendered_attrs.append(f'alt="{html.escape(alt)}"')
    title = attrs.get("title")
    if title:
        rendered_attrs.append(f'title="{html.escape(title)}"')
    return f"<img {' '.join(rendered_attrs)} />"


def render_inline_tokens(
    tokens: list[Token],
    attachment_map: dict[str, str],
    *,
    page_id: str | None,
    base_url: str | None,
    stop_type: str | None = None,
    start_index: int = 0,
) -> tuple[str, int]:
    """将 inline token 序列转换为 storage。"""
    parts: list[str] = []
    index = start_index
    while index < len(tokens):
        token = tokens[index]
        if stop_type is not None and token.type == stop_type:
            return "".join(parts), index + 1
        if token.type == "text":
            parts.append(escape_text(token.content))
            index += 1
            continue
        if token.type == "code_inline":
            parts.append(f"<code>{escape_text(token.content)}</code>")
            index += 1
            continue
        if token.type == "softbreak":
            parts.append("\n")
            index += 1
            continue
        if token.type == "hardbreak":
            parts.append("<br />")
            index += 1
            continue
        if token.type == "image":
            parts.append(
                render_image_token(
                    token,
                    attachment_map,
                    page_id=page_id,
                    base_url=base_url,
                )
            )
            index += 1
            continue
        if token.type in SUPPORTED_INLINE_CONTAINER_TOKENS:
            tag = "em" if token.type == "em_open" else "strong"
            inner, index = render_inline_tokens(
                tokens,
                attachment_map,
                page_id=page_id,
                base_url=base_url,
                stop_type=token.type.replace("_open", "_close"),
                start_index=index + 1,
            )
            parts.append(f"<{tag}>{inner}</{tag}>")
            continue
        if token.type == "link_open":
            attrs = validate_token_attributes(token)
            href = attrs.get("href", "")
            local_target = normalize_local_attachment_target(href)
            if local_target is not None:
                filename = register_attachment_reference(attachment_map, href)
                if page_id is None or base_url is None:
                    href = "#"
                else:
                    href = build_attachment_href(base_url, page_id, filename)
            inner, index = render_inline_tokens(
                tokens,
                attachment_map,
                page_id=page_id,
                base_url=base_url,
                stop_type="link_close",
                start_index=index + 1,
            )
            rendered_attrs = [f'href="{html.escape(href)}"']
            title = attrs.get("title")
            if title:
                rendered_attrs.append(f'title="{html.escape(title)}"')
            parts.append(f"<a {' '.join(rendered_attrs)}>{inner}</a>")
            continue
        if token.type in {"html_inline", "html_block"}:
            raise ApiError("Unsupported Markdown raw HTML.")
        raise ApiError(f"Unsupported Markdown inline token: {token.type}")

    if stop_type is not None:
        raise ApiError(f"Malformed Markdown: missing closing token `{stop_type}`.")
    return "".join(parts), index


def render_fence_token(token: Token) -> str:
    """渲染围栏代码块。"""
    info = token.info.strip()
    language = info.split(None, 1)[0] if info else ""
    language_attr = f' class="language-{html.escape(language)}"' if language else ""
    return f"<pre><code{language_attr}>{escape_text(token.content)}</code></pre>"


def render_block_tokens(
    tokens: list[Token],
    attachment_map: dict[str, str],
    *,
    page_id: str | None,
    base_url: str | None,
    stop_type: str | None = None,
    start_index: int = 0,
) -> tuple[str, int]:
    """将 block token 序列转换为 storage。"""
    parts: list[str] = []
    index = start_index
    while index < len(tokens):
        token = tokens[index]
        if stop_type is not None and token.type == stop_type:
            return "".join(parts), index + 1
        if token.type == "inline":
            rendered, _ = render_inline_tokens(
                token.children or [],
                attachment_map,
                page_id=page_id,
                base_url=base_url,
            )
            parts.append(rendered)
            index += 1
            continue
        if token.type in SUPPORTED_BLOCK_OPEN_TOKENS:
            attrs = validate_token_attributes(token)
            tag = token.tag
            rendered_attrs = ""
            if token.type == "ordered_list_open" and "start" in attrs:
                rendered_attrs = f' start="{html.escape(attrs["start"])}"'
            inner, index = render_block_tokens(
                tokens,
                attachment_map,
                page_id=page_id,
                base_url=base_url,
                stop_type=token.type.replace("_open", "_close"),
                start_index=index + 1,
            )
            parts.append(f"<{tag}{rendered_attrs}>{inner}</{tag}>")
            continue
        if token.type == "fence":
            parts.append(render_fence_token(token))
            index += 1
            continue
        if token.type == "code_block":
            parts.append(f"<pre><code>{escape_text(token.content)}</code></pre>")
            index += 1
            continue
        if token.type == "hr":
            parts.append("<hr />")
            index += 1
            continue
        if token.type in {"html_inline", "html_block"}:
            raise ApiError("Unsupported Markdown raw HTML.")
        raise ApiError(f"Unsupported Markdown block token: {token.type}")

    if stop_type is not None:
        raise ApiError(f"Malformed Markdown: missing closing token `{stop_type}`.")
    return "\n".join(parts), index


def markdown_to_storage(
    markdown: str,
    attachment_map: dict[str, str],
    *,
    page_id: str | None = None,
    base_url: str | None = None,
) -> str:
    """将 Markdown 解析为 Confluence storage。

    Markdown 语法解析完全交给 markdown-it-py；
    这里只负责把已识别 token 严格映射到 Confluence storage。
    若遇到未覆盖 token，则立即报错退出，避免静默发布错误内容。
    """
    tokens = MARKDOWN_PARSER.parse(markdown)
    rendered, _ = render_block_tokens(
        tokens,
        attachment_map,
        page_id=page_id,
        base_url=base_url,
    )
    return rendered


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


def resolve_parent_space_key(client: ConfluenceApiClient, parent_id: str) -> str:
    """从父页面获取 space key。"""
    parent = client.get_page(parent_id, expand="space")
    space = parent.get("space") if isinstance(parent, dict) else {}
    if not isinstance(space, dict) or not space.get("key"):
        raise ApiError(f"Failed to resolve space key from parent page {parent_id}")
    return str(space.get("key"))


def find_child_page_id(client: ConfluenceApiClient, parent_id: str, title: str) -> str | None:
    """在父页面下查找同名子页面。"""
    start = 0
    limit = 50
    while True:
        payload = client.get_page_children(parent_id, start=start, limit=limit, expand="space")
        results = normalize_results(payload)
        for item in results:
            if str(item.get("title", "")) == title:
                return str(item.get("id", ""))
        if not isinstance(payload, dict):
            break
        if payload.get("size", 0) < limit:
            break
        start += limit
    return None


def upload_attachments(
    client: ConfluenceApiClient,
    page_id: str,
    markdown_path: Path,
    attachment_map: dict[str, str],
) -> None:
    """上传 Markdown 引用的附件。"""
    base_dir = markdown_path.parent
    for filename, raw_path in attachment_map.items():
        path = Path(raw_path)
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            raise ApiError(f"Attachment not found: {path}")
        client.attach_file(page_id=page_id, file_path=str(path), title=filename)


def build_auth_headers(state: AppState) -> dict[str, str]:
    """构造 Confluence API 认证头。"""
    if state.username:
        raw = f"{state.username}:{state.token}".encode("utf-8")
        encoded = base64.b64encode(raw).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}
    return {"Authorization": f"Bearer {state.token}"}


def collect_attachments(
    client: ConfluenceApiClient,
    page_id: str,
    start: int,
    limit: int,
    expand: str | None,
    fetch_all: bool,
) -> list[dict[str, Any]]:
    """分页拉取附件列表。"""
    attachments: list[dict[str, Any]] = []
    current_start = start
    while True:
        payload = client.get_page_attachments(
            page_id,
            start=current_start,
            limit=limit,
            expand=expand,
        )
        items = normalize_results(payload)
        for item in items:
            if isinstance(item, dict):
                attachments.append(item)
        if not fetch_all:
            break
        links = payload.get("_links") if isinstance(payload, dict) else None
        if not isinstance(links, dict) or not links.get("next"):
            break
        current_start += limit
    return attachments


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


@attachment_app.command("list")
def list_attachments(
    ctx: typer.Context,
    page_id: str = typer.Option(..., "--page-id", help="页面 ID。"),
    start: int = typer.Option(0, "--start", help="分页起始索引。"),
    limit: int = typer.Option(25, "--limit", help="分页大小。"),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """列出页面附件。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    payload = client.get_page_attachments(page_id, start=start, limit=limit, expand=expand)
    ensure_json_output(payload, state.json_output, render_attachment_list)


@attachment_app.command("download")
def download_attachments(
    ctx: typer.Context,
    page_id: str = typer.Option(..., "--page-id", help="页面 ID。"),
    output_dir: Path = typer.Option(
        Path("attachments"),
        "--output-dir",
        help="下载目录（默认 ./attachments）。",
    ),
    names: list[str] | None = typer.Option(
        None,
        "--name",
        help="仅下载指定附件，可重复传入。",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        help="使用正则匹配附件名。",
    ),
    fetch_all: bool = typer.Option(
        False,
        "--all",
        help="下载全部附件（自动分页）。",
    ),
    start: int = typer.Option(0, "--start", help="分页起始索引。"),
    limit: int = typer.Option(25, "--limit", help="分页大小。"),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """下载页面附件。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    client = get_client(state)
    attachments = collect_attachments(
        client,
        page_id=page_id,
        start=start,
        limit=limit,
        expand=expand,
        fetch_all=fetch_all,
    )
    if names:
        name_set = set(names)
        attachments_map = {item.get("title"): item for item in attachments}
        attachments = [
            attachments_map[name]
            for name in names
            if name in attachments_map and isinstance(attachments_map[name], dict)
        ]
        missing = [name for name in names if name not in attachments_map]
    else:
        missing = []
    if name_filter:
        pattern = re.compile(name_filter)
        attachments = [
            item
            for item in attachments
            if isinstance(item, dict) and pattern.search(str(item.get("title", "")))
        ]
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = build_auth_headers(state)
    timeout_seconds = parse_timeout(state.timeout)
    downloaded: list[str] = []
    skipped: list[str] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", ""))
        download_link = (item.get("_links") or {}).get("download")
        if not download_link:
            skipped.append(title)
            continue
        target_url = f"{state.base_url.rstrip('/')}{download_link}"
        target_path = output_dir / title
        request = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            with target_path.open("wb") as f:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        downloaded.append(title)
    summary = {
        "output_dir": str(output_dir),
        "downloaded": downloaded,
        "skipped": skipped,
        "missing": missing,
    }
    ensure_json_output(summary, state.json_output)


@page_app.command("publish-markdown")
def publish_markdown(
    ctx: typer.Context,
    parent_id: str = typer.Option(..., "--parent-id", help="父页面 ID。"),
    title: str = typer.Option(..., "--title", help="页面标题。"),
    markdown_path: Path = typer.Option(..., "--markdown-path", exists=True, help="Markdown 文件路径。"),
    body_format: BodyFormat = typer.Option(BodyFormat.storage, "--body-format", help="内容格式。"),
    update_if_exists: bool = typer.Option(True, "--update-if-exists", help="存在同名子页面时更新。"),
    expand: str | None = typer.Option(None, "--expand", help="扩展字段。"),
) -> None:
    """发布 Markdown 到 Confluence（以 storage 写入，自动上传附件）。"""
    state = ctx.obj
    if not isinstance(state, AppState):
        raise ApiError("App config not initialized.")
    if body_format is not BodyFormat.storage:
        raise ApiError("publish-markdown 仅支持 storage。")

    client = get_client(state)
    space_key = resolve_parent_space_key(client, parent_id)

    # 当前内部 Confluence 实例按 Data Center / Server 能力处理。
    # 这类实例对 atlas_doc_format 的 REST 写入不稳定，实测会出现请求成功但页面内容不更新。
    # 因此这里统一收敛为生成 storage 内容，保证发布结果可预期。
    page_id = None
    if update_if_exists:
        page_id = find_child_page_id(client, parent_id, title)

    markdown_content = strip_leading_title_heading(markdown_path.read_text(encoding="utf-8"))
    attachment_map: dict[str, str] = {}
    body = markdown_to_storage(
        markdown_content,
        attachment_map,
        page_id=page_id,
        base_url=state.base_url if page_id else None,
    )

    if page_id:
        result = client.update_page(
            page_id=page_id,
            title=title,
            body=body,
            parent_id=parent_id,
            representation=body_format.value,
            always_update=True,
        )
    else:
        result = client.create_page(
            space_key=space_key,
            title=title,
            body=body,
            parent_id=parent_id,
            representation=body_format.value,
        )
        page_id = str(result.get("id")) if isinstance(result, dict) else None

    if not page_id:
        raise ApiError("Failed to resolve page id after publish.")

    if attachment_map:
        upload_attachments(client, page_id, markdown_path, attachment_map)

        final_body = markdown_to_storage(
            markdown_content,
            attachment_map,
            page_id=page_id,
            base_url=state.base_url,
        )
        if final_body != body:
            result = client.update_page(
                page_id=page_id,
                title=title,
                body=final_body,
                parent_id=parent_id,
                representation=body_format.value,
                always_update=True,
            )

    ensure_json_output(result, state.json_output)


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
app.add_typer(attachment_app, name="attachment")


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

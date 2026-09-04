#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "google-api-python-client>=2.200.0",
#     "google-auth-httplib2>=0.4.2",
#     "google-auth-oauthlib>=1.4.1",
#     "rich>=15.0.0",
#     "typer>=0.27.2",
# ]
# ///

"""面向 Codex skill 的 Google Calendar API 命令行工具。"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from rich.console import Console
from rich.pretty import Pretty

APP_NAME = "google-calendar-cli"
CLIENT_SECRET_ENV = "GOOGLE_WORKSPACE_CLIENT_SECRET"
CLIENT_SECRET_FILENAME = "client_secret.json"
TOKEN_FILENAME = "token.json"
AUTH_DOC = "references/google-workspace-oauth.md"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
]

app = typer.Typer(no_args_is_help=True)
auth_app = typer.Typer(no_args_is_help=True, help="认证相关操作。")
calendars_app = typer.Typer(no_args_is_help=True, help="查看已订阅的日历。")
events_app = typer.Typer(no_args_is_help=True, help="读取和管理日历事件。")
freebusy_app = typer.Typer(no_args_is_help=True, help="查询日历空闲/忙碌时间。")
console = Console()


class CliError(RuntimeError):
    """面向用户展示的 CLI 错误。"""


class SendUpdates(str, Enum):
    """Google Calendar 参会人通知范围。"""

    none = "none"
    all = "all"
    external_only = "externalOnly"


class EventOrder(str, Enum):
    """事件列表排序方式。"""

    start_time = "startTime"
    updated = "updated"


def xdg_config_home() -> Path:
    """返回 XDG 配置目录。"""
    value = os.environ.get("XDG_CONFIG_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".config"


def config_dir() -> Path:
    """返回 Calendar token 的独立配置目录。"""
    return xdg_config_home() / APP_NAME


def client_secret_candidates() -> list[Path]:
    """按优先级返回可复用的 Desktop OAuth client secret 路径。"""
    candidates: list[Path] = []
    configured = os.environ.get(CLIENT_SECRET_ENV)
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            xdg_config_home() / "google-workspace-cli" / CLIENT_SECRET_FILENAME,
            xdg_config_home() / "google-sheets-cli" / CLIENT_SECRET_FILENAME,
        ]
    )
    return candidates


def client_secret_path() -> Path:
    """返回明确配置的或第一个存在的 client secret。"""
    candidates = client_secret_candidates()
    if os.environ.get(CLIENT_SECRET_ENV):
        return candidates[0]
    return next((path for path in candidates if path.exists()), candidates[0])


def token_path() -> Path:
    """返回 Calendar 专用 token 路径。"""
    return config_dir() / TOKEN_FILENAME


def credential_paths_payload() -> dict[str, Any]:
    """返回不包含凭据内容的认证路径信息。"""
    selected = client_secret_path()
    return {
        "config_dir": str(config_dir()),
        "client_secret": str(selected),
        "client_secret_source": (
            "environment"
            if os.environ.get(CLIENT_SECRET_ENV)
            else "first_existing_candidate"
        ),
        "client_secret_candidates": [
            {"path": str(path), "exists": path.exists()}
            for path in client_secret_candidates()
        ],
        "token": str(token_path()),
    }


def missing_client_secret_message(path: Path) -> str:
    """生成可执行的 client secret 缺失提示。"""
    return f"""缺少 Google OAuth Desktop client secret：{path}

可选处理方式：
1. 把共享凭据保存到 ~/.config/google-workspace-cli/client_secret.json；或
2. 直接复用 ~/.config/google-sheets-cli/client_secret.json；或
3. 设置 {CLIENT_SECRET_ENV} 指向已有 JSON 文件。

然后运行：./scripts/google_calendar_cli.py auth login
详细配置见 {AUTH_DOC}。"""


def missing_token_message(path: Path) -> str:
    """生成可执行的 Calendar token 缺失提示。"""
    return f"""缺少 Google Calendar OAuth token：{path}

运行：./scripts/google_calendar_cli.py auth login
Calendar token 与 Gmail、Sheets token 分开保存，不能直接复制复用。
详细配置见 {AUTH_DOC}。"""


def ensure_client_secret_exists() -> Path:
    """确认 Desktop OAuth client secret 存在。"""
    path = client_secret_path()
    if not path.exists():
        raise CliError(missing_client_secret_message(path))
    return path


def missing_scopes(credentials: Credentials) -> list[str]:
    """返回 token 尚未授权的必要 scope。"""
    return [scope for scope in SCOPES if not credentials.has_scopes([scope])]


def write_token(credentials: Credentials) -> None:
    """以仅当前用户可读写的方式原子保存 token。"""
    directory = config_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    destination = token_path()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".token-",
            suffix=".json",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(credentials.to_json())
        temporary.chmod(0o600)
        temporary.replace(destination)
        destination.chmod(0o600)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_credentials() -> Credentials:
    """读取、校验并按需刷新 Calendar OAuth token。"""
    ensure_client_secret_exists()
    path = token_path()
    if not path.exists():
        raise CliError(missing_token_message(path))
    try:
        credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, GoogleAuthError) as exc:
        raise CliError(
            f"Calendar token 无法读取或格式不正确：{path}\n"
            "请执行 auth logout 后重新执行 auth login。"
        ) from exc
    missing = missing_scopes(credentials)
    if missing:
        raise CliError(
            "Calendar token 缺少必要 scope：\n- "
            + "\n- ".join(missing)
            + "\nDesktop app 不支持增量授权，请执行 auth logout 后重新登录。"
        )
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except GoogleAuthError as exc:
            raise CliError(
                "Calendar token 刷新失败，可能是授权被撤销、scope 变化或 "
                "Workspace 策略阻止。请重新执行 auth login。"
            ) from exc
        write_token(credentials)
        return credentials
    raise CliError("Calendar token 无效且无法刷新，请重新执行 auth login。")


def get_service() -> Any:
    """构造 Google Calendar API v3 client。"""
    return build(
        "calendar", "v3", credentials=load_credentials(), cache_discovery=False
    )


def render_output(ctx: typer.Context, payload: Any) -> None:
    """根据全局参数输出 JSON 或人类可读结构。"""
    if ctx.obj and ctx.obj.get("json_output"):
        console.print_json(data=payload)
        return
    console.print(Pretty(payload, expand_all=True))


def execute(request: Any) -> Any:
    """执行 Google API 请求并转换常见 HTTP 错误。"""
    try:
        return request.execute()
    except HttpError as exc:
        status = getattr(exc.resp, "status", "unknown")
        reason = getattr(exc, "reason", None) or str(exc)
        raise CliError(
            f"Google Calendar API 请求失败（HTTP {status}）：{reason}"
        ) from exc


def load_json_arg(raw: str, option_name: str) -> Any:
    """读取内联 JSON 或 @path 指向的 UTF-8 JSON 文件。"""
    source = raw
    if raw.startswith("@"):
        path = Path(raw[1:]).expanduser()
        if not path.exists():
            raise CliError(f"{option_name} 指向的文件不存在：{path}")
        source = path.read_text(encoding="utf-8")
    try:
        return json.loads(source)
    except json.JSONDecodeError as exc:
        raise CliError(f"{option_name} 不是合法 JSON：{exc}") from exc


def require_confirmation(value: bool, option: str, operation: str) -> None:
    """要求调用方对写操作提供显式确认。"""
    if not value:
        raise CliError(f"{operation}会修改 Google Calendar；确认后添加 {option}。")


def parse_rfc3339(value: str, option_name: str) -> datetime:
    """解析带时区的 RFC3339 时间。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CliError(f"{option_name} 必须是合法 RFC3339 时间：{value}") from exc
    if parsed.utcoffset() is None:
        raise CliError(f"{option_name} 必须包含时区偏移或 Z：{value}")
    return parsed


def ensure_time_window(time_min: str | None, time_max: str | None) -> None:
    """校验可选 RFC3339 时间窗口。"""
    start = parse_rfc3339(time_min, "--time-min") if time_min else None
    end = parse_rfc3339(time_max, "--time-max") if time_max else None
    if start is not None and end is not None and end <= start:
        raise CliError("--time-max 必须晚于 --time-min。")


def _event_endpoint(value: Any, field: str, option_name: str) -> tuple[str, Any]:
    """校验事件 start/end 端点并返回类型和值。"""
    if not isinstance(value, dict):
        raise CliError(f"{option_name}.{field} 必须是对象。")
    present = [name for name in ("date", "dateTime") if name in value]
    if len(present) != 1 or not isinstance(value[present[0]], str):
        raise CliError(f"{option_name}.{field} 必须且只能包含字符串 date 或 dateTime。")
    kind = present[0]
    raw = value[kind]
    if kind == "date":
        try:
            return kind, date.fromisoformat(raw)
        except ValueError as exc:
            raise CliError(f"{option_name}.{field}.date 必须是 YYYY-MM-DD。") from exc
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CliError(
            f"{option_name}.{field}.dateTime 必须是合法 RFC3339 时间。"
        ) from exc
    if parsed.utcoffset() is not None:
        return kind, parsed
    time_zone = value.get("timeZone")
    if not isinstance(time_zone, str) or not time_zone:
        raise CliError(
            f"{option_name}.{field}.dateTime 不带偏移时必须同时提供 timeZone。"
        )
    try:
        return kind, parsed.replace(tzinfo=ZoneInfo(time_zone))
    except ZoneInfoNotFoundError as exc:
        raise CliError(
            f"{option_name}.{field}.timeZone 不是已知 IANA 时区：{time_zone}"
        ) from exc


def validate_event_body(
    value: Any, option_name: str, *, create: bool
) -> dict[str, Any]:
    """校验 create/patch 使用的事件 JSON 基本契约。"""
    if not isinstance(value, dict) or not value:
        raise CliError(f"{option_name} 必须是非空 JSON 对象。")
    if not create:
        return value
    missing = [field for field in ("start", "end") if field not in value]
    if missing:
        raise CliError(f"{option_name} 创建事件时缺少字段：{', '.join(missing)}。")
    start_kind, start = _event_endpoint(value["start"], "start", option_name)
    end_kind, end = _event_endpoint(value["end"], "end", option_name)
    if start_kind != end_kind:
        raise CliError(f"{option_name}.start 和 end 必须同时使用 date 或 dateTime。")
    if end <= start:
        raise CliError(
            f"{option_name}.end 必须晚于 start；全天事件的 end 日期不包含在内。"
        )
    return value


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json", help="输出 JSON，方便 Agent 解析。"
    ),
) -> None:
    """初始化全局输出选项。"""
    ctx.obj = {"json_output": json_output}


@auth_app.command("paths", help="显示凭据候选路径，不读取凭据内容。")
def auth_paths(ctx: typer.Context) -> None:
    """显示认证路径。"""
    payload = credential_paths_payload()
    payload["client_secret_exists"] = client_secret_path().exists()
    payload["token_exists"] = token_path().exists()
    render_output(ctx, payload)


@auth_app.command("doctor", help="检查 OAuth client、token 和 scopes。")
def auth_doctor(ctx: typer.Context) -> None:
    """检查认证状态。"""
    payload = credential_paths_payload()
    if not client_secret_path().exists():
        payload.update(
            status="missing_client_secret",
            next_step=missing_client_secret_message(client_secret_path()),
        )
        render_output(ctx, payload)
        return
    if not token_path().exists():
        payload.update(
            status="missing_token", next_step=missing_token_message(token_path())
        )
        render_output(ctx, payload)
        return
    credentials = load_credentials()
    payload.update(
        status="ok" if credentials.valid else "invalid",
        scopes=list(credentials.scopes or SCOPES),
        expiry=credentials.expiry.isoformat() if credentials.expiry else None,
    )
    render_output(ctx, payload)


@auth_app.command("login", help="执行 Desktop OAuth 登录并保存 Calendar token。")
def auth_login(
    ctx: typer.Context,
    open_browser: bool = typer.Option(
        True, "--open-browser/--no-open-browser", help="是否自动打开系统浏览器。"
    ),
) -> None:
    """执行完整 Calendar scopes 授权。"""
    secret = ensure_client_secret_exists()
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    credentials = flow.run_local_server(
        port=0, open_browser=open_browser, access_type="offline", prompt="consent"
    )
    missing = missing_scopes(credentials)
    if missing:
        raise CliError("用户未授予必要 scope：" + ", ".join(missing))
    write_token(credentials)
    render_output(
        ctx,
        {
            "status": "ok",
            "token": str(token_path()),
            "scopes": list(credentials.scopes or SCOPES),
        },
    )


@auth_app.command("logout", help="删除本机 Calendar token，不删除共享 client secret。")
def auth_logout(ctx: typer.Context) -> None:
    """删除 Calendar token。"""
    path = token_path()
    existed = path.exists()
    if existed:
        path.unlink()
    render_output(ctx, {"status": "ok", "removed": existed, "token": str(path)})


@calendars_app.command("list", help="列出当前账号订阅的日历。")
def calendars_list(
    ctx: typer.Context,
    max_results: int = typer.Option(100, "--max-results", min=1, max=250),
    page_token: str | None = typer.Option(None, "--page-token"),
    show_hidden: bool = typer.Option(False, "--show-hidden"),
    show_deleted: bool = typer.Option(False, "--show-deleted"),
) -> None:
    """列出 CalendarList 中的日历。"""
    kwargs: dict[str, Any] = {
        "maxResults": max_results,
        "showHidden": show_hidden,
        "showDeleted": show_deleted,
    }
    if page_token:
        kwargs["pageToken"] = page_token
    render_output(ctx, execute(get_service().calendarList().list(**kwargs)))


@calendars_app.command("get", help="读取一个已订阅日历的元数据。")
def calendars_get(
    ctx: typer.Context,
    calendar_id: str = typer.Option("primary", "--calendar-id"),
) -> None:
    """读取 CalendarList entry。"""
    result = execute(get_service().calendarList().get(calendarId=calendar_id))
    render_output(ctx, result)


@events_app.command("list", help="按时间窗口或关键词列出事件。")
def events_list(
    ctx: typer.Context,
    calendar_id: str = typer.Option("primary", "--calendar-id"),
    time_min: str | None = typer.Option(None, "--time-min"),
    time_max: str | None = typer.Option(None, "--time-max"),
    query: str | None = typer.Option(None, "--query", "-q"),
    max_results: int = typer.Option(50, "--max-results", min=1, max=2500),
    page_token: str | None = typer.Option(None, "--page-token"),
    single_events: bool = typer.Option(
        True, "--single-events/--series", help="展开实例或返回重复事件系列。"
    ),
    order_by: EventOrder | None = typer.Option(EventOrder.start_time, "--order-by"),
    show_deleted: bool = typer.Option(False, "--show-deleted"),
) -> None:
    """列出单个日历的事件。"""
    ensure_time_window(time_min, time_max)
    if order_by is EventOrder.start_time and not single_events:
        raise CliError("--order-by startTime 只能和 --single-events 一起使用。")
    kwargs: dict[str, Any] = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": single_events,
        "showDeleted": show_deleted,
    }
    for key, value in (
        ("timeMin", time_min),
        ("timeMax", time_max),
        ("q", query),
        ("pageToken", page_token),
        ("orderBy", order_by.value if order_by else None),
    ):
        if value is not None:
            kwargs[key] = value
    render_output(ctx, execute(get_service().events().list(**kwargs)))


@events_app.command("get", help="按 event ID 读取事件。")
def events_get(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--event-id"),
    calendar_id: str = typer.Option("primary", "--calendar-id"),
) -> None:
    """读取一个事件。"""
    result = execute(
        get_service().events().get(calendarId=calendar_id, eventId=event_id)
    )
    render_output(ctx, result)


@events_app.command("instances", help="列出重复事件系列的实例。")
def events_instances(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--event-id"),
    calendar_id: str = typer.Option("primary", "--calendar-id"),
    time_min: str | None = typer.Option(None, "--time-min"),
    time_max: str | None = typer.Option(None, "--time-max"),
    max_results: int = typer.Option(50, "--max-results", min=1, max=2500),
    page_token: str | None = typer.Option(None, "--page-token"),
    show_deleted: bool = typer.Option(False, "--show-deleted"),
) -> None:
    """列出重复事件的具体实例。"""
    ensure_time_window(time_min, time_max)
    kwargs: dict[str, Any] = {
        "calendarId": calendar_id,
        "eventId": event_id,
        "maxResults": max_results,
        "showDeleted": show_deleted,
    }
    for key, value in (
        ("timeMin", time_min),
        ("timeMax", time_max),
        ("pageToken", page_token),
    ):
        if value is not None:
            kwargs[key] = value
    render_output(ctx, execute(get_service().events().instances(**kwargs)))


@events_app.command("create", help="从 Google Event JSON 创建事件。")
def events_create(
    ctx: typer.Context,
    event_json: str = typer.Option(..., "--event-json"),
    calendar_id: str = typer.Option("primary", "--calendar-id"),
    send_updates: SendUpdates = typer.Option(SendUpdates.none, "--send-updates"),
    conference_data_version: int = typer.Option(
        0, "--conference-data-version", min=0, max=1
    ),
    confirm_create: bool = typer.Option(False, "--confirm-create"),
) -> None:
    """创建事件，并显式控制参会人通知。"""
    require_confirmation(confirm_create, "--confirm-create", "创建事件")
    body = validate_event_body(
        load_json_arg(event_json, "--event-json"), "--event-json", create=True
    )
    result = execute(
        get_service()
        .events()
        .insert(
            calendarId=calendar_id,
            body=body,
            sendUpdates=send_updates.value,
            conferenceDataVersion=conference_data_version,
        )
    )
    render_output(ctx, result)


@events_app.command("patch", help="从 Google Event JSON 局部更新事件。")
def events_patch(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--event-id"),
    event_json: str = typer.Option(..., "--event-json"),
    calendar_id: str = typer.Option("primary", "--calendar-id"),
    send_updates: SendUpdates = typer.Option(SendUpdates.none, "--send-updates"),
    conference_data_version: int = typer.Option(
        0, "--conference-data-version", min=0, max=1
    ),
    confirm_update: bool = typer.Option(False, "--confirm-update"),
) -> None:
    """局部更新事件，并显式控制参会人通知。"""
    require_confirmation(confirm_update, "--confirm-update", "更新事件")
    body = validate_event_body(
        load_json_arg(event_json, "--event-json"), "--event-json", create=False
    )
    result = execute(
        get_service()
        .events()
        .patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=body,
            sendUpdates=send_updates.value,
            conferenceDataVersion=conference_data_version,
        )
    )
    render_output(ctx, result)


@events_app.command("delete", help="删除事件或重复事件实例。")
def events_delete(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--event-id"),
    calendar_id: str = typer.Option("primary", "--calendar-id"),
    send_updates: SendUpdates = typer.Option(SendUpdates.none, "--send-updates"),
    confirm_delete: bool = typer.Option(False, "--confirm-delete"),
) -> None:
    """删除事件，并显式控制参会人通知。"""
    require_confirmation(confirm_delete, "--confirm-delete", "删除事件")
    execute(
        get_service()
        .events()
        .delete(
            calendarId=calendar_id,
            eventId=event_id,
            sendUpdates=send_updates.value,
        )
    )
    render_output(
        ctx,
        {
            "status": "ok",
            "calendarId": calendar_id,
            "deleted": event_id,
            "sendUpdates": send_updates.value,
        },
    )


@freebusy_app.command("query", help="查询一个或多个日历的忙碌时间段。")
def freebusy_query(
    ctx: typer.Context,
    calendar_ids: list[str] = typer.Option(..., "--calendar-id"),
    time_min: str = typer.Option(..., "--time-min"),
    time_max: str = typer.Option(..., "--time-max"),
    time_zone: str | None = typer.Option(None, "--time-zone"),
    group_expansion_max: int = typer.Option(
        100, "--group-expansion-max", min=1, max=100
    ),
    calendar_expansion_max: int = typer.Option(
        50, "--calendar-expansion-max", min=1, max=50
    ),
) -> None:
    """查询 RFC3339 时间窗口中的 busy 区间。"""
    ensure_time_window(time_min, time_max)
    if not calendar_ids or any(not item.strip() for item in calendar_ids):
        raise CliError("至少需要一个非空 --calendar-id。")
    body: dict[str, Any] = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": item} for item in calendar_ids],
        "groupExpansionMax": group_expansion_max,
        "calendarExpansionMax": calendar_expansion_max,
    }
    if time_zone:
        body["timeZone"] = time_zone
    render_output(ctx, execute(get_service().freebusy().query(body=body)))


app.add_typer(auth_app, name="auth")
app.add_typer(calendars_app, name="calendars")
app.add_typer(events_app, name="events")
app.add_typer(freebusy_app, name="freebusy")


def run() -> None:
    """运行 CLI 并以简洁方式展示预期错误。"""
    try:
        app()
    except CliError as exc:
        console.print(f"[red]错误：[/red]{exc}", markup=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()

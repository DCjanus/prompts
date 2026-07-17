#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "google-api-python-client>=2.198.0",
#     "google-auth-httplib2>=0.4.0",
#     "google-auth-oauthlib>=1.4.0",
#     "rich>=15.0.0",
#     "typer>=0.27.0",
# ]
# ///
"""Google Sheets CLI for Codex skills."""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from rich.console import Console
from rich.table import Table

APP_NAME = "google-sheets-cli"
CLIENT_SECRET_FILENAME = "client_secret.json"
TOKEN_FILENAME = "token.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
AUTH_DOC = "references/google-workspace-oauth.md"

app = typer.Typer(no_args_is_help=True)
auth_app = typer.Typer(no_args_is_help=True, help="认证相关操作。")
spreadsheet_app = typer.Typer(no_args_is_help=True, help="Spreadsheet 元数据操作。")
values_app = typer.Typer(no_args_is_help=True, help="单元格值读写操作。")
console = Console()


class CliError(RuntimeError):
    """Human-readable CLI error."""


class ValueInputOption(str, Enum):
    raw = "RAW"
    user_entered = "USER_ENTERED"


class InsertDataOption(str, Enum):
    overwrite = "OVERWRITE"
    insert_rows = "INSERT_ROWS"


def xdg_config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".config"


def config_dir() -> Path:
    return xdg_config_home() / APP_NAME


def client_secret_path() -> Path:
    return config_dir() / CLIENT_SECRET_FILENAME


def token_path() -> Path:
    return config_dir() / TOKEN_FILENAME


def credential_paths_payload() -> dict[str, str]:
    return {
        "config_dir": str(config_dir()),
        "client_secret": str(client_secret_path()),
        "token": str(token_path()),
    }


def missing_client_secret_message(path: Path) -> str:
    return f"""缺少 Google OAuth client secret 文件：{path}

处理方式：
1. 先阅读 {AUTH_DOC}，创建 Google OAuth Desktop app client。
2. 把下载的 JSON 保存为：{path}
3. 设置权限：chmod 700 {path.parent} && chmod 600 {path}
4. 运行：./scripts/gsheets_cli.py auth login

该 JSON 应包含 installed.client_id 和 installed.client_secret 字段。"""


def missing_token_message(path: Path) -> str:
    return f"""缺少本地 Google OAuth token：{path}

处理方式：
1. 运行：./scripts/gsheets_cli.py auth login
2. 如果登录环境、远程 callback 或 Workspace 策略有问题，阅读 {AUTH_DOC}。"""


def ensure_client_secret_exists() -> Path:
    path = client_secret_path()
    if not path.exists():
        raise CliError(missing_client_secret_message(path))
    return path


def load_json_arg(raw: str, option_name: str) -> Any:
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


def ensure_2d_values(value: Any, option_name: str) -> list[list[Any]]:
    if not isinstance(value, list) or any(not isinstance(row, list) for row in value):
        raise CliError(f'{option_name} 必须是二维 JSON 数组，例如 [["A", "B"]]。')
    return value


def ensure_batch_updates(value: Any, option_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CliError(
            f"{option_name} 必须是数组，例如 "
            '[{"range":"Sheet1!A1","values":[["DONE"]]}]。'
        )
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise CliError(f"{option_name}[{index}] 必须是对象。")
        cell_range = item.get("range")
        values = item.get("values")
        if not isinstance(cell_range, str) or not cell_range:
            raise CliError(f"{option_name}[{index}].range 必须是非空字符串。")
        normalized.append(
            {
                "range": cell_range,
                "values": ensure_2d_values(values, f"{option_name}[{index}].values"),
            }
        )
    return normalized


def ensure_links(value: Any, option_name: str, text: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CliError(
            f'{option_name} 必须是数组，例如 [{{"text":"MR !96","url":"https://..."}}]。'
        )
    if not value:
        raise CliError(f"{option_name} 至少需要包含一个链接。")
    links: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise CliError(f"{option_name}[{index}] 必须是对象。")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            raise CliError(f"{option_name}[{index}].url 必须是非空字符串。")
        if "start" in item or "end" in item:
            start = item.get("start")
            end = item.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                raise CliError(f"{option_name}[{index}].start/end 必须是整数。")
            if start < 0 or end <= start or end > len(text):
                raise CliError(f"{option_name}[{index}].start/end 超出文本范围。")
            link_text = text[start:end]
        else:
            link_text = item.get("text")
            if not isinstance(link_text, str) or not link_text:
                raise CliError(f"{option_name}[{index}].text 必须是非空字符串。")
            start = text.find(link_text)
            if start < 0:
                raise CliError(f"{option_name}[{index}].text 在 --text 中不存在。")
            if text.find(link_text, start + 1) >= 0:
                raise CliError(
                    f"{option_name}[{index}].text 在 --text 中出现多次；"
                    "请改用 start/end 明确位置。"
                )
            end = start + len(link_text)
        links.append({"start": start, "end": end, "url": url, "text": link_text})
    links.sort(key=lambda link: link["start"])
    previous_end = 0
    for link in links:
        if link["start"] < previous_end:
            raise CliError(f"{option_name} 中的链接范围不能重叠。")
        previous_end = link["end"]
    return links


A1_SINGLE_CELL_RE = re.compile(
    r"^(?:(?P<sheet>'(?:[^']|'')+'|[^'!]+)!)?(?P<col>[A-Za-z]+)(?P<row>[1-9][0-9]*)$"
)


def unquote_sheet_name(value: str) -> str:
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def column_index(column: str) -> int:
    index = 0
    for char in column.upper():
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def parse_single_cell_range(range_: str) -> tuple[str, int, int]:
    match = A1_SINGLE_CELL_RE.match(range_)
    if not match or not match.group("sheet"):
        raise CliError("--range 必须是带 sheet 名的单个单元格，例如 'Sheet1'!I10。")
    return (
        unquote_sheet_name(match.group("sheet")),
        int(match.group("row")) - 1,
        column_index(match.group("col")),
    )


def sheet_id_for_title(service: Any, spreadsheet_id: str, title: str) -> int:
    metadata = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title))",
        )
        .execute()
    )
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == title:
            return properties["sheetId"]
    raise CliError(f"找不到名为 {title!r} 的 sheet。")


def utf16_index(text: str, codepoint_index: int) -> int:
    return len(text[:codepoint_index].encode("utf-16-le")) // 2


def text_format_runs(links: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = [{"startIndex": 0, "format": {}}]
    for link in links:
        runs.append(
            {
                "startIndex": utf16_index(text, link["start"]),
                "format": {
                    "link": {"uri": link["url"]},
                    "foregroundColor": {
                        "red": 0.06666667,
                        "green": 0.33333334,
                        "blue": 0.8,
                    },
                    "underline": True,
                },
            }
        )
        if link["end"] < len(text):
            runs.append({"startIndex": utf16_index(text, link["end"]), "format": {}})
    deduplicated: list[dict[str, Any]] = []
    for run in runs:
        if deduplicated and deduplicated[-1]["startIndex"] == run["startIndex"]:
            deduplicated[-1] = run
        else:
            deduplicated.append(run)
    return deduplicated


def load_credentials() -> Credentials:
    ensure_client_secret_exists()
    path = token_path()
    if not path.exists():
        raise CliError(missing_token_message(path))
    try:
        credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, GoogleAuthError) as exc:
        raise CliError(
            f"本地 token 文件无法读取或格式不正确：{path}\n"
            "请运行 `./scripts/gsheets_cli.py auth logout` 后重新执行 "
            "`./scripts/gsheets_cli.py auth login`。\n"
            f"更多处理方式见 {AUTH_DOC}。"
        ) from exc
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            raise CliError(
                "Google OAuth token 刷新失败，可能是授权被撤销、scope 变化或公司策略阻止。\n"
                "请运行：\n"
                "  ./scripts/gsheets_cli.py auth login\n"
                f"更多处理方式见 {AUTH_DOC}。"
            ) from exc
        write_token(credentials)
        return credentials
    raise CliError(
        "本地 Google OAuth token 无效且无法刷新。\n"
        "请运行：\n"
        "  ./scripts/gsheets_cli.py auth login\n"
        f"更多处理方式见 {AUTH_DOC}。"
    )


def write_token(credentials: Credentials) -> None:
    directory = config_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = token_path()
    path.write_text(credentials.to_json(), encoding="utf-8")
    path.chmod(0o600)


def get_service() -> Any:
    credentials = load_credentials()
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def render_json(payload: Any) -> None:
    console.print_json(data=payload)


def render_kv_table(title: str, data: dict[str, Any]) -> None:
    table = Table(title=title)
    table.add_column("field")
    table.add_column("value")
    for key, value in data.items():
        table.add_row(str(key), "" if value is None else str(value))
    console.print(table)


def render_output(ctx: typer.Context, payload: Any, title: str | None = None) -> None:
    if ctx.obj and ctx.obj.get("json_output"):
        render_json(payload)
        return
    if isinstance(payload, dict):
        render_kv_table(title or "Result", payload)
        return
    console.print(payload)


def handle_http_error(exc: HttpError) -> CliError:
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        message = payload.get("error", {}).get("message")
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        message = str(exc)
    hint = ""
    if status in {401, 403}:
        hint = (
            "\n\n请确认：\n"
            "1. 当前 Google 账号有访问该 Spreadsheet 的权限。\n"
            "2. OAuth client 已被公司 Workspace 策略允许。\n"
            "3. token scope 包含 https://www.googleapis.com/auth/spreadsheets；"
            "必要时重新运行 auth login。\n"
            f"更多处理方式见 {AUTH_DOC}。"
        )
    if status == 404:
        hint = "\n\n请确认 spreadsheet id 和 range 是否正确，且当前账号有权限访问。"
    return CliError(f"Google Sheets API 请求失败（status {status}）：{message}{hint}")


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json", help="输出 JSON，方便 Agent 解析。"
    ),
) -> None:
    ctx.obj = {"json_output": json_output}


@auth_app.command("paths", help="显示 XDG 凭据路径。")
def auth_paths(ctx: typer.Context) -> None:
    payload: dict[str, Any] = credential_paths_payload()
    payload["client_secret_exists"] = client_secret_path().exists()
    payload["token_exists"] = token_path().exists()
    render_output(ctx, payload, "Credential paths")


@auth_app.command("doctor", help="检查本地凭据与 token 状态。")
def auth_doctor(ctx: typer.Context) -> None:
    payload: dict[str, Any] = credential_paths_payload()
    payload["client_secret_exists"] = client_secret_path().exists()
    payload["token_exists"] = token_path().exists()
    if not client_secret_path().exists():
        payload["status"] = "missing_client_secret"
        payload["next_step"] = missing_client_secret_message(client_secret_path())
        render_output(ctx, payload, "Auth doctor")
        return
    if not token_path().exists():
        payload["status"] = "missing_token"
        payload["next_step"] = missing_token_message(token_path())
        render_output(ctx, payload, "Auth doctor")
        return
    credentials = load_credentials()
    payload["status"] = "ok" if credentials.valid else "invalid"
    payload["scopes"] = list(credentials.scopes or SCOPES)
    payload["expiry"] = credentials.expiry.isoformat() if credentials.expiry else None
    render_output(ctx, payload, "Auth doctor")


@auth_app.command("login", help="执行 OAuth 登录并保存 token。")
def auth_login(
    ctx: typer.Context,
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-open-browser",
        help="是否自动打开浏览器。",
    ),
) -> None:
    secret = ensure_client_secret_exists()
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    credentials = flow.run_local_server(port=0, open_browser=open_browser)
    write_token(credentials)
    render_output(
        ctx,
        {
            "status": "ok",
            "token": str(token_path()),
            "scopes": list(credentials.scopes or SCOPES),
        },
        "Auth login",
    )


@auth_app.command("logout", help="删除本地 token。")
def auth_logout(ctx: typer.Context) -> None:
    path = token_path()
    existed = path.exists()
    if existed:
        path.unlink()
    render_output(ctx, {"status": "ok", "removed": existed, "token": str(path)})


@spreadsheet_app.command("get", help="读取 spreadsheet 元数据。")
def spreadsheet_get(
    ctx: typer.Context,
    spreadsheet_id: str = typer.Option(..., "--spreadsheet-id"),
    include_grid_data: bool = typer.Option(False, "--include-grid-data"),
) -> None:
    try:
        payload = (
            get_service()
            .spreadsheets()
            .get(spreadsheetId=spreadsheet_id, includeGridData=include_grid_data)
            .execute()
        )
    except HttpError as exc:
        raise handle_http_error(exc) from exc
    render_output(ctx, payload, "Spreadsheet")


@values_app.command("get", help="读取一个 A1 range 的值。")
def values_get(
    ctx: typer.Context,
    spreadsheet_id: str = typer.Option(..., "--spreadsheet-id"),
    range_: str = typer.Option(..., "--range", help="A1 notation range."),
) -> None:
    try:
        payload = (
            get_service()
            .spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_)
            .execute()
        )
    except HttpError as exc:
        raise handle_http_error(exc) from exc
    render_output(ctx, payload, "Values")


@values_app.command("update", help="写入一个 A1 range 的值。")
def values_update(
    ctx: typer.Context,
    spreadsheet_id: str = typer.Option(..., "--spreadsheet-id"),
    range_: str = typer.Option(..., "--range", help="A1 notation range."),
    values_json: str = typer.Option(
        ..., "--values-json", help="二维 JSON 数组或 @path。"
    ),
    value_input_option: ValueInputOption = typer.Option(
        ValueInputOption.user_entered,
        "--value-input-option",
    ),
) -> None:
    values = ensure_2d_values(
        load_json_arg(values_json, "--values-json"), "--values-json"
    )
    try:
        payload = (
            get_service()
            .spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption=value_input_option.value,
                body={"values": values},
            )
            .execute()
        )
    except HttpError as exc:
        raise handle_http_error(exc) from exc
    render_output(ctx, payload, "Update")


@values_app.command("batch-update", help="批量写入多个 A1 range 的值。")
def values_batch_update(
    ctx: typer.Context,
    spreadsheet_id: str = typer.Option(..., "--spreadsheet-id"),
    updates_json: str = typer.Option(
        ..., "--updates-json", help="更新数组 JSON 或 @path。"
    ),
    value_input_option: ValueInputOption = typer.Option(
        ValueInputOption.user_entered,
        "--value-input-option",
    ),
) -> None:
    updates = ensure_batch_updates(
        load_json_arg(updates_json, "--updates-json"),
        "--updates-json",
    )
    try:
        payload = (
            get_service()
            .spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": value_input_option.value, "data": updates},
            )
            .execute()
        )
    except HttpError as exc:
        raise handle_http_error(exc) from exc
    render_output(ctx, payload, "Batch update")


@values_app.command("append", help="追加值到一个 A1 range 检测到的表格末尾。")
def values_append(
    ctx: typer.Context,
    spreadsheet_id: str = typer.Option(..., "--spreadsheet-id"),
    range_: str = typer.Option(..., "--range", help="A1 notation range."),
    values_json: str = typer.Option(
        ..., "--values-json", help="二维 JSON 数组或 @path。"
    ),
    value_input_option: ValueInputOption = typer.Option(
        ValueInputOption.user_entered,
        "--value-input-option",
    ),
    insert_data_option: InsertDataOption = typer.Option(
        InsertDataOption.insert_rows,
        "--insert-data-option",
    ),
) -> None:
    values = ensure_2d_values(
        load_json_arg(values_json, "--values-json"), "--values-json"
    )
    try:
        payload = (
            get_service()
            .spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption=value_input_option.value,
                insertDataOption=insert_data_option.value,
                body={"values": values},
            )
            .execute()
        )
    except HttpError as exc:
        raise handle_http_error(exc) from exc
    render_output(ctx, payload, "Append")


@values_app.command("clear", help="清空一个 A1 range 的值；格式和数据验证会保留。")
def values_clear(
    ctx: typer.Context,
    spreadsheet_id: str = typer.Option(..., "--spreadsheet-id"),
    range_: str = typer.Option(..., "--range", help="A1 notation range."),
) -> None:
    try:
        payload = (
            get_service()
            .spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheet_id, range=range_, body={})
            .execute()
        )
    except HttpError as exc:
        raise handle_http_error(exc) from exc
    render_output(ctx, payload, "Clear")


@values_app.command("update-rich-text", help="写入单个单元格，并给部分文字添加链接。")
def values_update_rich_text(
    ctx: typer.Context,
    spreadsheet_id: str = typer.Option(..., "--spreadsheet-id"),
    range_: str = typer.Option(..., "--range", help="带 sheet 名的单个 A1 单元格。"),
    text: str = typer.Option(..., "--text", help="单元格完整文本。"),
    links_json: str = typer.Option(
        ...,
        "--links-json",
        help='链接数组 JSON 或 @path，例如 [{"text":"MR !96","url":"https://..."}]。',
    ),
) -> None:
    links = ensure_links(
        load_json_arg(links_json, "--links-json"), "--links-json", text
    )
    sheet_title, row_index, col_index = parse_single_cell_range(range_)
    service = get_service()
    try:
        sheet_id = sheet_id_for_title(service, spreadsheet_id, sheet_title)
        payload = (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateCells": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": row_index,
                                    "endRowIndex": row_index + 1,
                                    "startColumnIndex": col_index,
                                    "endColumnIndex": col_index + 1,
                                },
                                "rows": [
                                    {
                                        "values": [
                                            {
                                                "userEnteredValue": {
                                                    "stringValue": text
                                                },
                                                "textFormatRuns": text_format_runs(
                                                    links, text
                                                ),
                                            }
                                        ]
                                    }
                                ],
                                "fields": "userEnteredValue,textFormatRuns",
                            }
                        }
                    ]
                },
            )
            .execute()
        )
    except HttpError as exc:
        raise handle_http_error(exc) from exc
    render_output(ctx, payload, "Update rich text")


app.add_typer(auth_app, name="auth")
app.add_typer(spreadsheet_app, name="spreadsheet")
app.add_typer(values_app, name="values")


def run() -> None:
    try:
        app()
    except CliError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    run()

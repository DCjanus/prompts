#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "google-api-python-client>=2.196.0",
#     "google-auth>=2.52.0",
#     "pydantic>=2.13.4",
#     "rich>=15.0.0",
#     "typer>=0.25.1",
# ]
# ///

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Annotated, Any

import google.auth
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table
import typer

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

console = Console()
app = typer.Typer(help="Google Sheets CLI backed by gcloud ADC.")
auth_app = typer.Typer(help="Diagnose gcloud ADC credentials.")
spreadsheet_app = typer.Typer(help="Spreadsheet metadata operations.")
values_app = typer.Typer(help="Read and write cell values.")
sheet_app = typer.Typer(help="Sheet/tab structure operations.")
table_app = typer.Typer(help="Native Google Sheets table operations.")
format_app = typer.Typer(help="Cell and sheet formatting operations.")
validation_app = typer.Typer(help="Data validation operations.")
batch_app = typer.Typer(help="Raw batchUpdate helpers.")

app.add_typer(auth_app, name="auth")
app.add_typer(spreadsheet_app, name="spreadsheet")
app.add_typer(values_app, name="values")
app.add_typer(sheet_app, name="sheet")
app.add_typer(table_app, name="table")
app.add_typer(format_app, name="format")
app.add_typer(validation_app, name="validation")
app.add_typer(batch_app, name="batch")

OUTPUT_JSON = False


class BatchSpec(BaseModel):
    """声明式 batchUpdate 输入。"""

    requests: list[dict[str, Any]] = Field(default_factory=list)


def fail(message: str, *, exit_code: int = 1) -> None:
    """输出错误并退出。"""
    if OUTPUT_JSON:
        console.print_json(data={"ok": False, "error": message})
    else:
        console.print(f"[red]Error:[/red] {message}", stderr=True)
    raise typer.Exit(exit_code)


def emit(data: Any, *, human: str | None = None) -> None:
    """按当前输出模式打印结果。"""
    if OUTPUT_JSON:
        console.print_json(data=data)
    elif human:
        console.print(human)
    else:
        console.print(data)


def read_json(path: Path) -> Any:
    """读取 JSON 文件。"""
    try:
        return json.loads(path.read_text())
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")


def api_error(exc: HttpError) -> str:
    """提取 Google API 错误。"""
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        return payload.get("error", {}).get("message") or str(exc)
    except Exception:
        return str(exc)


def sheets_service() -> Any:
    """创建 Sheets API service。"""
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        if not creds.valid:
            creds.refresh(Request())
        return build("sheets", "v4", credentials=creds, cache_discovery=False)
    except Exception as exc:
        fail(
            "cannot load Google ADC credentials. Run "
            "`gcloud auth application-default login "
            "--scopes=https://www.googleapis.com/auth/spreadsheets` first. "
            f"Details: {exc}"
        )


def sheet_metadata(service: Any, spreadsheet_id: str) -> dict[str, Any]:
    """读取 spreadsheet 元数据。"""
    return (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            includeGridData=False,
            fields="spreadsheetId,properties.title,spreadsheetUrl,sheets(properties,tables)",
        )
        .execute()
    )


def resolve_sheet_id(
    service: Any, spreadsheet_id: str, sheet: str | None, sheet_id: int | None
) -> int:
    """根据 sheet name 或 id 找到 sheetId。"""
    if sheet_id is not None:
        return sheet_id
    if not sheet:
        fail("pass --sheet or --sheet-id")
    meta = sheet_metadata(service, spreadsheet_id)
    for item in meta.get("sheets", []):
        props = item.get("properties", {})
        if props.get("title") == sheet:
            return int(props["sheetId"])
    fail(f"sheet not found: {sheet}")


def col_to_index(col: str) -> int:
    """把 A1 列名转成 0-based index。"""
    value = 0
    for char in col.upper():
        if not ("A" <= char <= "Z"):
            fail(f"invalid column: {col}")
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def parse_a1_range(service: Any, spreadsheet_id: str, a1_range: str) -> dict[str, int]:
    """解析常见 A1 range 为 GridRange。"""
    if "!" not in a1_range:
        fail("range must include sheet name, for example `Sheet1!A1:C10`")
    sheet_name, cells = a1_range.split("!", 1)
    sheet_name = sheet_name.strip("'")
    match = re.fullmatch(r"([A-Za-z]+)(\d+)?(?::([A-Za-z]+)(\d+)?)?", cells)
    if not match:
        fail(f"unsupported A1 range: {a1_range}")
    start_col, start_row, end_col, end_row = match.groups()
    grid_range: dict[str, int] = {
        "sheetId": resolve_sheet_id(service, spreadsheet_id, sheet_name, None),
        "startColumnIndex": col_to_index(start_col),
    }
    grid_range["endColumnIndex"] = col_to_index(end_col or start_col) + 1
    if start_row:
        grid_range["startRowIndex"] = int(start_row) - 1
    if end_row:
        grid_range["endRowIndex"] = int(end_row)
    elif start_row:
        grid_range["endRowIndex"] = int(start_row)
    return grid_range


def color_style(hex_color: str) -> dict[str, Any]:
    """把 #RRGGBB 转为 ColorStyle。"""
    raw = hex_color.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        fail(f"invalid color: {hex_color}")
    red = int(raw[0:2], 16) / 255
    green = int(raw[2:4], 16) / 255
    blue = int(raw[4:6], 16) / 255
    return {"rgbColor": {"red": red, "green": green, "blue": blue}}


def batch_update(
    service: Any, spreadsheet_id: str, requests: list[dict[str, Any]]
) -> dict[str, Any]:
    """执行 spreadsheets.batchUpdate。"""
    try:
        return (
            service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
            .execute()
        )
    except HttpError as exc:
        fail(api_error(exc))


@app.callback()
def main(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Google Sheets CLI backed by gcloud ADC."""
    global OUTPUT_JSON
    OUTPUT_JSON = json_output


@auth_app.command("doctor")
def auth_doctor() -> None:
    """检查 ADC 是否可用。"""
    sheets_service()
    emit(
        {"ok": True, "api": "sheets", "scopes": list(SCOPES)},
        human="ADC credentials are usable.",
    )


@auth_app.command("scopes")
def auth_scopes() -> None:
    """读取当前 access token 信息。"""
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        creds.refresh(Request())
        url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode(
            {"access_token": creds.token}
        )
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        fail(f"cannot inspect token scopes: {exc}")
    emit(payload)


@auth_app.command("whoami")
def auth_whoami() -> None:
    """读取当前 ADC token 的账号线索。"""
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        creds.refresh(Request())
        url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode(
            {"access_token": creds.token}
        )
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        fail(f"cannot inspect token identity: {exc}")
    identity = {
        "email": payload.get("email"),
        "scope": payload.get("scope"),
        "expires_in": payload.get("expires_in"),
        "note": "email may be null when the ADC token does not include an identity scope",
    }
    emit(identity)


@spreadsheet_app.command("info")
def spreadsheet_info(spreadsheet_id: str) -> None:
    """读取 spreadsheet 元信息。"""
    service = sheets_service()
    try:
        meta = sheet_metadata(service, spreadsheet_id)
    except HttpError as exc:
        fail(api_error(exc))
    if OUTPUT_JSON:
        emit(meta)
        return
    table = Table(title=meta.get("properties", {}).get("title", spreadsheet_id))
    table.add_column("Title")
    table.add_column("Sheet ID")
    table.add_column("Rows")
    table.add_column("Columns")
    for item in meta.get("sheets", []):
        props = item.get("properties", {})
        grid = props.get("gridProperties", {})
        table.add_row(
            str(props.get("title", "")),
            str(props.get("sheetId", "")),
            str(grid.get("rowCount", "")),
            str(grid.get("columnCount", "")),
        )
    console.print(table)


@values_app.command("get")
def values_get(
    spreadsheet_id: str, range_: Annotated[str, typer.Argument(help="A1 range")]
) -> None:
    """读取一个 A1 range。"""
    service = sheets_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_)
            .execute()
        )
    except HttpError as exc:
        fail(api_error(exc))
    emit(result)


@values_app.command("batch-get")
def values_batch_get(
    spreadsheet_id: str,
    ranges: Annotated[list[str], typer.Option("--range", help="A1 range, repeatable.")],
) -> None:
    """一次读取多个 range。"""
    service = sheets_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .batchGet(spreadsheetId=spreadsheet_id, ranges=ranges)
            .execute()
        )
    except HttpError as exc:
        fail(api_error(exc))
    emit(result)


@values_app.command("update")
def values_update(
    spreadsheet_id: str,
    range_: Annotated[str, typer.Argument(help="A1 range")],
    input_path: Annotated[
        Path, typer.Option("--input", "-i", exists=True, readable=True)
    ],
    value_input_option: Annotated[
        str, typer.Option("--value-input-option", help="RAW or USER_ENTERED")
    ] = "USER_ENTERED",
) -> None:
    """覆盖写入 values JSON。"""
    values = read_json(input_path)
    body = values if isinstance(values, dict) else {"values": values}
    service = sheets_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute()
        )
    except HttpError as exc:
        fail(api_error(exc))
    emit(result)


@values_app.command("batch-update")
def values_batch_update(
    spreadsheet_id: str,
    input_path: Annotated[
        Path, typer.Option("--input", "-i", exists=True, readable=True)
    ],
    value_input_option: Annotated[
        str, typer.Option("--value-input-option")
    ] = "USER_ENTERED",
) -> None:
    """批量写入 values JSON。"""
    payload = read_json(input_path)
    if isinstance(payload, list):
        body = {"data": payload}
    elif isinstance(payload, dict):
        body = payload
    else:
        fail("batch-update input must be an object or array")
    body.setdefault("valueInputOption", value_input_option)
    service = sheets_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=body)
            .execute()
        )
    except HttpError as exc:
        fail(api_error(exc))
    emit(result)


@values_app.command("append")
def values_append(
    spreadsheet_id: str,
    range_: Annotated[str, typer.Argument(help="A1 range")],
    input_path: Annotated[
        Path, typer.Option("--input", "-i", exists=True, readable=True)
    ],
    value_input_option: Annotated[
        str, typer.Option("--value-input-option")
    ] = "USER_ENTERED",
) -> None:
    """追加 values JSON。"""
    values = read_json(input_path)
    body = values if isinstance(values, dict) else {"values": values}
    service = sheets_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption=value_input_option,
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )
    except HttpError as exc:
        fail(api_error(exc))
    emit(result)


@values_app.command("clear")
def values_clear(
    spreadsheet_id: str, range_: Annotated[str, typer.Argument(help="A1 range")]
) -> None:
    """清空一个 range。"""
    service = sheets_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheet_id, range=range_, body={})
            .execute()
        )
    except HttpError as exc:
        fail(api_error(exc))
    emit(result)


@sheet_app.command("add")
def sheet_add(
    spreadsheet_id: str, title: str, rows: int = 1000, columns: int = 26
) -> None:
    """新增 sheet/tab。"""
    service = sheets_service()
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "addSheet": {
                    "properties": {
                        "title": title,
                        "gridProperties": {"rowCount": rows, "columnCount": columns},
                    }
                }
            }
        ],
    )
    emit(result)


@sheet_app.command("rename")
def sheet_rename(
    spreadsheet_id: str,
    title: str,
    sheet: Annotated[str | None, typer.Option("--sheet")] = None,
    sheet_id: Annotated[int | None, typer.Option("--sheet-id")] = None,
) -> None:
    """重命名 sheet/tab。"""
    service = sheets_service()
    sid = resolve_sheet_id(service, spreadsheet_id, sheet, sheet_id)
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sid, "title": title},
                    "fields": "title",
                }
            }
        ],
    )
    emit(result)


@sheet_app.command("resize")
def sheet_resize(
    spreadsheet_id: str,
    rows: int,
    columns: int,
    sheet: Annotated[str | None, typer.Option("--sheet")] = None,
    sheet_id: Annotated[int | None, typer.Option("--sheet-id")] = None,
) -> None:
    """调整 sheet 行列规模。"""
    service = sheets_service()
    sid = resolve_sheet_id(service, spreadsheet_id, sheet, sheet_id)
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sid,
                        "gridProperties": {"rowCount": rows, "columnCount": columns},
                    },
                    "fields": "gridProperties(rowCount,columnCount)",
                }
            }
        ],
    )
    emit(result)


@sheet_app.command("delete")
def sheet_delete(
    spreadsheet_id: str,
    sheet: Annotated[str | None, typer.Option("--sheet")] = None,
    sheet_id: Annotated[int | None, typer.Option("--sheet-id")] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm deletion.")] = False,
) -> None:
    """删除 sheet/tab。"""
    if not yes:
        fail("deleting a sheet requires --yes")
    service = sheets_service()
    sid = resolve_sheet_id(service, spreadsheet_id, sheet, sheet_id)
    result = batch_update(service, spreadsheet_id, [{"deleteSheet": {"sheetId": sid}}])
    emit(result)


@table_app.command("create")
def table_create(
    spreadsheet_id: str,
    range_: Annotated[str, typer.Argument(help="A1 range")],
    name: Annotated[str | None, typer.Option("--name")] = None,
) -> None:
    """从 range 创建原生 table。"""
    service = sheets_service()
    table_body: dict[str, Any] = {
        "range": parse_a1_range(service, spreadsheet_id, range_)
    }
    if name:
        table_body["name"] = name
    result = batch_update(
        service, spreadsheet_id, [{"addTable": {"table": table_body}}]
    )
    emit(result)


@table_app.command("delete")
def table_delete(spreadsheet_id: str, table_id: str, yes: bool = False) -> None:
    """删除原生 table。"""
    if not yes:
        fail("deleting a table requires --yes")
    service = sheets_service()
    result = batch_update(
        service, spreadsheet_id, [{"deleteTable": {"tableId": table_id}}]
    )
    emit(result)


@table_app.command("set-column")
def table_set_column(
    spreadsheet_id: str,
    table_id: str,
    column_index: int,
    column_type: Annotated[str, typer.Option("--type")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    options: Annotated[list[str] | None, typer.Option("--option")] = None,
) -> None:
    """设置 table 列类型；DROPDOWN 可重复传 --option。"""
    column: dict[str, Any] = {"columnIndex": column_index, "columnType": column_type}
    fields = ["columnProperties.columnType"]
    if name:
        column["columnName"] = name
        fields.append("columnProperties.columnName")
    if options:
        column["dataValidationRule"] = {
            "condition": {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": item} for item in options],
            }
        }
        fields.append("columnProperties.dataValidationRule")
    service = sheets_service()
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "updateTable": {
                    "table": {"tableId": table_id, "columnProperties": [column]},
                    "fields": ",".join(fields),
                }
            }
        ],
    )
    emit(result)


@format_app.command("number")
def format_number(
    spreadsheet_id: str,
    range_: Annotated[str, typer.Argument(help="A1 range")],
    type_: Annotated[
        str, typer.Option("--type", help="NUMBER, PERCENT, CURRENCY, DATE, ...")
    ],
    pattern: Annotated[str | None, typer.Option("--pattern")] = None,
) -> None:
    """设置 range 的数字/日期格式。"""
    service = sheets_service()
    number_format: dict[str, Any] = {"type": type_}
    if pattern:
        number_format["pattern"] = pattern
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "repeatCell": {
                    "range": parse_a1_range(service, spreadsheet_id, range_),
                    "cell": {"userEnteredFormat": {"numberFormat": number_format}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        ],
    )
    emit(result)


@format_app.command("header")
def format_header(
    spreadsheet_id: str,
    range_: Annotated[str, typer.Argument(help="A1 range")],
    background: Annotated[str, typer.Option("--background")] = "#0F9D58",
    foreground: Annotated[str, typer.Option("--foreground")] = "#FFFFFF",
) -> None:
    """设置表头样式。"""
    service = sheets_service()
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "repeatCell": {
                    "range": parse_a1_range(service, spreadsheet_id, range_),
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColorStyle": color_style(background),
                            "textFormat": {
                                "foregroundColorStyle": color_style(foreground),
                                "bold": True,
                            },
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColorStyle,userEnteredFormat.textFormat",
                }
            }
        ],
    )
    emit(result)


@format_app.command("freeze")
def format_freeze(
    spreadsheet_id: str,
    rows: int = 1,
    columns: int = 0,
    sheet: Annotated[str | None, typer.Option("--sheet")] = None,
    sheet_id: Annotated[int | None, typer.Option("--sheet-id")] = None,
) -> None:
    """冻结行列。"""
    service = sheets_service()
    sid = resolve_sheet_id(service, spreadsheet_id, sheet, sheet_id)
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sid,
                        "gridProperties": {
                            "frozenRowCount": rows,
                            "frozenColumnCount": columns,
                        },
                    },
                    "fields": "gridProperties(frozenRowCount,frozenColumnCount)",
                }
            }
        ],
    )
    emit(result)


@format_app.command("autoresize")
def format_autoresize(
    spreadsheet_id: str,
    start_column: int,
    end_column: int,
    sheet: Annotated[str | None, typer.Option("--sheet")] = None,
    sheet_id: Annotated[int | None, typer.Option("--sheet-id")] = None,
) -> None:
    """自动调整列宽；列索引是 0-based，end_column 为开区间。"""
    service = sheets_service()
    sid = resolve_sheet_id(service, spreadsheet_id, sheet, sheet_id)
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": sid,
                        "dimension": "COLUMNS",
                        "startIndex": start_column,
                        "endIndex": end_column,
                    }
                }
            }
        ],
    )
    emit(result)


@format_app.command("value-colors")
def format_value_colors(
    spreadsheet_id: str,
    range_: Annotated[str, typer.Argument(help="A1 range")],
    rules: Annotated[
        list[str],
        typer.Option(
            "--rule", help="VALUE=#RRGGBB, repeatable. Uses conditional formatting."
        ),
    ],
) -> None:
    """按单元格值设置背景色。"""
    service = sheets_service()
    grid_range = parse_a1_range(service, spreadsheet_id, range_)
    requests = []
    for rule in rules:
        if "=" not in rule:
            fail(f"invalid rule: {rule}")
        value, color = rule.split("=", 1)
        requests.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [grid_range],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": value}],
                            },
                            "format": {"backgroundColorStyle": color_style(color)},
                        },
                    },
                    "index": 0,
                }
            }
        )
    result = batch_update(service, spreadsheet_id, requests)
    emit(result)


@validation_app.command("dropdown")
def validation_dropdown(
    spreadsheet_id: str,
    range_: Annotated[str, typer.Argument(help="A1 range")],
    options: Annotated[
        list[str], typer.Option("--option", help="Dropdown option, repeatable.")
    ],
    strict: bool = True,
) -> None:
    """设置普通 range 下拉菜单。"""
    service = sheets_service()
    result = batch_update(
        service,
        spreadsheet_id,
        [
            {
                "setDataValidation": {
                    "range": parse_a1_range(service, spreadsheet_id, range_),
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": item} for item in options],
                        },
                        "strict": strict,
                        "showCustomUi": True,
                    },
                }
            }
        ],
    )
    emit(result)


@batch_app.command("raw")
def batch_raw(
    spreadsheet_id: str,
    input_path: Annotated[
        Path, typer.Option("--input", "-i", exists=True, readable=True)
    ],
) -> None:
    """执行原始 batchUpdate JSON；文件可为 requests 数组或 {requests:[...]}。"""
    payload = read_json(input_path)
    requests = (
        payload.get("requests", payload) if isinstance(payload, dict) else payload
    )
    if not isinstance(requests, list):
        fail("batch input must be a requests array or an object with requests")
    service = sheets_service()
    emit(batch_update(service, spreadsheet_id, requests))


@batch_app.command("apply")
def batch_apply(
    spreadsheet_id: str,
    input_path: Annotated[
        Path, typer.Option("--input", "-i", exists=True, readable=True)
    ],
) -> None:
    """执行声明式 batch spec。"""
    try:
        spec = BatchSpec.model_validate(read_json(input_path))
    except Exception as exc:
        fail(f"invalid batch spec: {exc}")
    service = sheets_service()
    emit(batch_update(service, spreadsheet_id, spec.requests))


if __name__ == "__main__":
    try:
        app()
    except BrokenPipeError:
        sys.exit(1)

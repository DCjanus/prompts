---
name: google-sheets-cli
description: 使用 Python CLI 与 Google Sheets API 交互以读取、更新、批量写入、追加或清空 Google Sheets 在线表格；适用于需要通过 OAuth 授权操作 Google Workspace 表格的场景。
---

# google-sheets-cli

通过本 skill 调用 Google Sheets API。适合读取和编辑 Google Sheets 在线文档中的单元格值。

## 执行约定

先进入 skill 目录，再直接执行脚本：

```bash
cd skills/google-sheets-cli
./scripts/gsheets_cli.py --json values get --spreadsheet-id <spreadsheet-id> --range "Sheet1!A1:D20"
```

- 不要用 `uv run python` 或 `python` 调用脚本；脚本自身带 uv shebang。
- 给 Agent 解析的输出一律加 `--json`，并且全局参数必须放在子命令前。
- 写操作会真实修改在线表格；范围不确定时先读目标 range。
- 参数不确定时先查 `./scripts/gsheets_cli.py <command> --help`。

## 认证

OAuth 通常只需要配置一次；日常任务不要把认证细节加载进上下文。

- 查看当前凭据路径与认证状态：`./scripts/gsheets_cli.py --json auth doctor`。
- 缺少 client secret、token 失效、Workspace 策略阻止等认证问题，按 [google-workspace-oauth.md](references/google-workspace-oauth.md) 处理。

## 日常操作

常用命令族：

- `auth login|doctor|logout|paths`
- `spreadsheet get`
- `values get|update|batch-update|append|clear|update-rich-text`

示例：

```bash
./scripts/gsheets_cli.py --json spreadsheet get --spreadsheet-id <spreadsheet-id>
./scripts/gsheets_cli.py --json values get --spreadsheet-id <spreadsheet-id> --range "Sheet1!A1:D20"
./scripts/gsheets_cli.py --json values update --spreadsheet-id <spreadsheet-id> --range "Sheet1!B2" --values-json '[["DONE"]]'
./scripts/gsheets_cli.py --json values append --spreadsheet-id <spreadsheet-id> --range "Sheet1!A:D" --values-json '[["a","b","c","d"]]'
```

批量写入：

```bash
./scripts/gsheets_cli.py --json values batch-update \
  --spreadsheet-id <spreadsheet-id> \
  --updates-json '[{"range":"Sheet1!B2","values":[["DONE"]]},{"range":"Sheet1!C2","values":[["ok"]]}]'
```

复杂 JSON 可以使用 `@path` 从文件读取：

```bash
./scripts/gsheets_cli.py --json values batch-update \
  --spreadsheet-id <spreadsheet-id> \
  --updates-json @/tmp/sheets-updates.json
```

## 读取格式与 table 元数据

需要确认在线表格的列结构、table 范围、filter、banded row 样式、dropdown 选项、列宽、日期格式等信息时，优先走只读流程：

1. 先读 spreadsheet metadata，不带 grid data：

```bash
./scripts/gsheets_cli.py --json spreadsheet get --spreadsheet-id <spreadsheet-id>
```

metadata 通常足够看到 sheet id、sheet title、`basicFilter`、`bandedRanges`、`tables[].range`、`tables[].columnProperties`，包括 table dropdown 列的选项。

2. 只读单元格内容时，用 `values get` 限定 A1 range：

```bash
./scripts/gsheets_cli.py --json values get \
  --spreadsheet-id <spreadsheet-id> \
  --range "Sheet1!A1:H40"
```

3. 避免直接对大型 workbook 使用 `spreadsheet get --include-grid-data`；它会拉取全量 grid data，可能很慢。需要读取单元格 `effectiveFormat`、列宽、行高、日期格式等精细格式时，复用本 CLI 的 OAuth token，通过 Sheets API 原生 `spreadsheets.get` 指定 `ranges` 和 `fields` 做窄范围只读查询：

```bash
uv run --with google-api-python-client --with google-auth-httplib2 --with google-auth-oauthlib python - <<'PY'
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

spreadsheet_id = "<spreadsheet-id>"
creds = Credentials.from_authorized_user_file(
    str(Path.home() / ".config/google-sheets-cli/token.json"),
    ["https://www.googleapis.com/auth/spreadsheets"],
)
service = build("sheets", "v4", credentials=creds)
resp = service.spreadsheets().get(
    spreadsheetId=spreadsheet_id,
    ranges=["'Sheet1'!A1:H5"],
    includeGridData=True,
    fields="sheets(properties(sheetId,title),data(columnMetadata,rowData(values(formattedValue,effectiveFormat,dataValidation))))",
).execute()
print(resp)
PY
```

## 更新 table / dropdown 的注意事项

- 写线上表格前，先用 `values get` 备份目标范围到 `/tmp/...json`，并把所有写操作限定到目标 sheet/range；不要误动其它 tab。
- `values update` 只改值，不会自动扩展 Google Sheets table 的范围、列名、filter、banded range 或 dropdown metadata。新增列后，如果要保持 table 结构，需要用 Sheets API `spreadsheets.batchUpdate` 调 `updateTable`、`updateBanding`、`setBasicFilter`、`updateDimensionProperties` 等请求，并使用目标 sheet 的 `sheetId` 限定范围。
- Google Sheets API 当前的 `TableColumnDataValidationRule` 只能表达 dropdown 的 `ONE_OF_LIST` 选项，不能表达 Google Sheets UI 里的 dropdown chip 背景色、选项颜色、display style 或 multi-select 等 UI metadata。用 `updateTable` 重写 `columnProperties` 时，原 UI 选项颜色可能丢失。
- 不要尝试用 API 自动“修复” dropdown chip 颜色。已验证 `copyPaste` + `PASTE_DATA_VALIDATION` 不可靠，条件格式也不等价：设置背景色会把整个单元格染色，只设置文字色也只是灰色 chip 内的文字变色，都会偏离原生 chip 视觉。遇到这类需求时，应明确告知这是 Google Sheets API 缺口，保留现状、回退写入，或让用户在 UI/模板中手工维护。
- table dropdown 列不要再对同一范围叠加普通 `setDataValidation`；Google Sheets 会报错类似 `无法对指定类型的列中的单元格进行此操作`。应通过 `updateTable.columnProperties[].dataValidationRule` 维护 table dropdown 选项。

## 链接写入

- Google Sheets 不支持 Markdown 的 `[text](url)` 链接语法；不要把 Markdown 链接直接写进单元格并期待 UI 渲染成链接。
- 只需要整格都是同一个链接时，可用 `values update --value-input-option USER_ENTERED` 写入 `=HYPERLINK("https://example.com", "显示文本")`。注意：这种方式会让整个单元格显示文本都成为同一个链接。
- 只想让单元格中的一小段文字带链接时，不要现场写 Python；优先用 `values update-rich-text`。该命令会用 Sheets API `updateCells` 写 `userEnteredValue.stringValue` 和 `textFormatRuns[].format.link.uri`。

示例：只让备注里的 `knots-frontend !96` 这段文字带链接：

```bash
./scripts/gsheets_cli.py --json values update-rich-text \
  --spreadsheet-id <spreadsheet-id> \
  --range "Sheet1!I10" \
  --text "延期到 7/9：Backup AZ 约束仍在 knots-frontend !96 中。" \
  --links-json '[{"text":"knots-frontend !96","url":"https://git.example.com/group/project/-/merge_requests/96"}]'
```

如果同一段显示文字在单元格中出现多次，改用 `start` / `end` 明确字符位置：`[{"start":18,"end":36,"url":"https://..."}]`。

## 权限范围

CLI 使用 Google Sheets scope：`https://www.googleapis.com/auth/spreadsheets`。

该 scope 可读取和修改用户有权限访问的 Google Sheets。若公司 Workspace 阻止该 OAuth client 访问，需由 Workspace 管理员允许对应 OAuth Client ID。

## 参考

- [gsheets_cli.py](scripts/gsheets_cli.py)
- [google-workspace-oauth.md](references/google-workspace-oauth.md)
- [Google Sheets API](https://developers.google.com/workspace/sheets/api/reference/rest)
- [Read & write cell values](https://developers.google.com/workspace/sheets/api/guides/values)

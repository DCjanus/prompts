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
- `values get|update|batch-update|append|clear`

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

## 权限范围

CLI 使用 Google Sheets scope：`https://www.googleapis.com/auth/spreadsheets`。

该 scope 可读取和修改用户有权限访问的 Google Sheets。若公司 Workspace 阻止该 OAuth client 访问，需由 Workspace 管理员允许对应 OAuth Client ID。

## 参考

- [gsheets_cli.py](scripts/gsheets_cli.py)
- [google-workspace-oauth.md](references/google-workspace-oauth.md)
- [Google Sheets API](https://developers.google.com/workspace/sheets/api/reference/rest)
- [Read & write cell values](https://developers.google.com/workspace/sheets/api/guides/values)

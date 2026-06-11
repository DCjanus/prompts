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

默认凭据目录遵循 XDG：

- OAuth client secret：`$XDG_CONFIG_HOME/google-sheets-cli/client_secret.json`
- OAuth token：`$XDG_CONFIG_HOME/google-sheets-cli/token.json`

若未设置 `XDG_CONFIG_HOME`，默认使用 `~/.config/google-sheets-cli/`。

首次使用前，由用户把 Google Cloud Console 里下载的 OAuth Desktop app JSON 保存为：

```bash
mkdir -p ~/.config/google-sheets-cli
chmod 700 ~/.config/google-sheets-cli
cp /path/to/downloaded-client-secret.json ~/.config/google-sheets-cli/client_secret.json
chmod 600 ~/.config/google-sheets-cli/client_secret.json
```

然后登录：

```bash
./scripts/gsheets_cli.py auth login
```

- 登录会打开本机浏览器并启动 localhost callback。
- 远程 SSH 场景下，浏览器 callback 必须能访问运行 CLI 的机器；必要时在目标机器本地登录，或自行做端口转发。
- 后续命令只读本地 token 文件；token 缺失、失效或权限不足时，脚本会输出中文修复指引。
- 查看当前路径与认证状态：`./scripts/gsheets_cli.py --json auth doctor`。

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
- [Google Sheets API](https://developers.google.com/workspace/sheets/api/reference/rest)
- [Read & write cell values](https://developers.google.com/workspace/sheets/api/guides/values)

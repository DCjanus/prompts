---
name: google-sheets-cli
description: 使用 Google 官方 Sheets API client library 和 gcloud ADC 操作 Google Sheets；适用于 Agent 需要读取、写入、追加、清空、批量更新、创建或管理 sheet/tab、创建原生 table、设置列类型、下拉菜单、数字格式、表头样式、冻结行列、自动列宽、按值上色、或执行 spreadsheets.batchUpdate JSON 的场景。
---

通过本 skill 调用 Google Sheets API。默认只依赖本机 `gcloud` 提供 ADC 授权；脚本不读取 Chrome 登录态，不保存 OAuth client secret。

## 执行约定

说明：以下脚本调用均以当前 `SKILL.md` 所在文件夹为 workdir。

脚本调用方式（必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`）：

```bash
cd skills/google-sheets-cli
./scripts/google_sheets.py --json spreadsheet info <spreadsheet-id>
```

错误示例：

```bash
uv run python skills/google-sheets-cli/scripts/google_sheets.py --help
python skills/google-sheets-cli/scripts/google_sheets.py --help
```

- 给 Agent 解析的输出一律加 `--json`，并且全局参数必须放在子命令前。
- 参数不确定时先查 `./scripts/google_sheets.py <command> --help` 或 `./scripts/google_sheets.py <group> <command> --help`。
- 删除 sheet/table 前必须确认用户意图；脚本要求显式传 `--yes`。

## 认证

默认假设 ADC 已配置，直接执行用户请求的操作。只有命令失败且报错指向 `gcloud`、ADC、token、scope 或权限问题时，再运行：

```bash
./scripts/google_sheets.py --json auth doctor
./scripts/google_sheets.py --json auth scopes
```

如果目标机器还没有安装或初始化 `gcloud`，读取 [gcloud-adc.md](references/gcloud-adc.md)，按其中指引安装并执行 ADC 登录。

## 常用命令

读取元信息：

```bash
./scripts/google_sheets.py --json spreadsheet info <spreadsheet-id>
```

读写 values：

```bash
./scripts/google_sheets.py --json values get <spreadsheet-id> "Sheet1!A1:C10"
./scripts/google_sheets.py --json values batch-get <spreadsheet-id> --range "Sheet1!A1:C10" --range "Sheet2!A1:B5"
./scripts/google_sheets.py --json values update <spreadsheet-id> "Sheet1!A1:C2" --input /path/to/values.json
./scripts/google_sheets.py --json values batch-update <spreadsheet-id> --input /path/to/batch-values.json
./scripts/google_sheets.py --json values append <spreadsheet-id> "Sheet1!A:C" --input /path/to/rows.json
./scripts/google_sheets.py --json values clear <spreadsheet-id> "Sheet1!A2:C"
```

管理 sheet/tab：

```bash
./scripts/google_sheets.py --json sheet add <spreadsheet-id> "Report"
./scripts/google_sheets.py --json sheet rename <spreadsheet-id> --sheet "Report" "Weekly Report"
./scripts/google_sheets.py --json sheet resize <spreadsheet-id> --sheet "Weekly Report" 200 12
./scripts/google_sheets.py --json sheet delete <spreadsheet-id> --sheet "Old Tab" --yes
```

创建 table、设置列类型和下拉：

```bash
./scripts/google_sheets.py --json table create <spreadsheet-id> "Sheet1!A1:F100" --name "Tasks"
./scripts/google_sheets.py --json table set-column <spreadsheet-id> <table-id> 2 --type DOUBLE --name "Score"
./scripts/google_sheets.py --json table set-column <spreadsheet-id> <table-id> 0 --type DROPDOWN --option "Todo" --option "Doing" --option "Done"
```

格式和数据验证：

```bash
./scripts/google_sheets.py --json validation dropdown <spreadsheet-id> "Sheet1!A2:A100" --option "Todo" --option "Doing" --option "Done"
./scripts/google_sheets.py --json format number <spreadsheet-id> "Sheet1!C2:C100" --type NUMBER --pattern "0.00"
./scripts/google_sheets.py --json format header <spreadsheet-id> "Sheet1!A1:F1"
./scripts/google_sheets.py --json format freeze <spreadsheet-id> --sheet "Sheet1" --rows 1
./scripts/google_sheets.py --json format autoresize <spreadsheet-id> --sheet "Sheet1" 0 6
./scripts/google_sheets.py --json format value-colors <spreadsheet-id> "Sheet1!A2:A100" --rule "Todo=#F9AB00" --rule "Doing=#1A73E8" --rule "Done=#0F9D58"
```

低层 batchUpdate：

```bash
./scripts/google_sheets.py --json batch raw <spreadsheet-id> --input /path/to/requests.json
./scripts/google_sheets.py --json batch apply <spreadsheet-id> --input /path/to/spec.json
```

## API 边界

- 官方 API 支持创建原生 table、设置 table column type、普通 range 下拉菜单、table dropdown column、数字格式、条件格式和 batchUpdate。
- Google Sheets 网页 UI 支持给 dropdown chip 的每个选项设置颜色，但当前公开 Sheets API schema 没有 per-option color 字段。不要承诺脚本能设置真实 dropdown option chip color。
- 如需近似视觉效果，使用 `format value-colors` 按单元格值添加 conditional formatting；这会给整个单元格设置背景色，不是给 dropdown option 自身设置颜色。

## 资源

- [google_sheets.py](scripts/google_sheets.py)：主 CLI 入口，使用 Google 官方 Python client library 和 ADC 调用 Sheets API。
- [gcloud-adc.md](references/gcloud-adc.md)：安装 `gcloud`、初始化 ADC 和 scope 选择的参考说明；只有认证环境缺失或用户询问安装方式时才读取。

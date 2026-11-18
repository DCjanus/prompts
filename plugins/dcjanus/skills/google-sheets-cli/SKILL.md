---
name: google-sheets-cli
description: 新建 Google Sheets 在线表格，按范围读取、更新、追加或清空单元格，维护表格格式和富文本链接。
---

# Google Sheets CLI

使用 [gsheets_cli.py](scripts/gsheets_cli.py)。全局 `--json` 放在子命令前，按 `--help` 逐层查询参数。首次配置或认证失败时运行 `--json auth doctor`，按 [Workspace OAuth 指南](references/google-workspace-oauth.md) 处理凭据、scope 和管理员限制。

- 新建表格用 `spreadsheet create`；定位 tab、sheetId 和表结构用 `spreadsheet get`。读取单元格用 `values get --spreadsheet-id … --range …`。
- 写前核对目标 tab 与 A1 范围，并备份将受影响的数据。普通 `values get` 返回显示值。需要恢复公式或富文本时，用 `spreadsheet get --range … --fields …` 保存目标范围的 `userEnteredValue`、`textFormatRuns` 等写入会覆盖的字段；表结构调整还需保留相应元数据。
- 更新、批量更新或追加时，每个值必须是 JSON 标量。对象先转为字符串或拆成多列；复杂输入用 `@path`。仅用同次 shell 的 `&& rm -- <明确文件路径>` 清理成功后不再需要的单次临时输入；失败、用户文件、备份及验证材料都保留。
- 读取格式、调整 table、列宽或 dropdown 时，先看 [表结构、字段掩码与下拉选项](references/table-and-format.md)，尤其留意重写列定义对原生 chip 颜色的影响。
- 写入整格或局部链接时按 [单元格链接](references/cell-links.md) 选择 `HYPERLINK` 或 `values update-rich-text`。

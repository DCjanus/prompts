# 读取格式和维护 Google Sheets table

`spreadsheet get` 默认只返回 metadata，可查看 sheet id、标题、filter、banded ranges 和 table 列定义；只读单元格内容用 `values get --range`。

需要单元格格式、下拉校验、列宽或行高时，通过 `--range`（可重复）和 `--fields` 限定返回内容，避免拉取大型 workbook 的全量 grid data：

```bash
./scripts/gsheets_cli.py --json spreadsheet get \
  --spreadsheet-id <spreadsheet-id> \
  --range "'Sheet1'!A1:H5" \
  --fields 'sheets(properties(sheetId,title),data(columnMetadata,rowMetadata,rowData(values(formattedValue,effectiveFormat,dataValidation))))'
```

`--fields` 使用 [Sheets API 字段掩码](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get)，指定后由掩码决定是否返回 grid data，`--include-grid-data` 不再生效。

## 更新 table / dropdown 的注意事项

- `values update` 只改值，不会自动扩展 Google Sheets table 的范围、列名、filter、banded range 或 dropdown metadata。新增列后，如果要保持 table 结构，需要用 Sheets API `spreadsheets.batchUpdate` 调 `updateTable`、`updateBanding`、`setBasicFilter`、`updateDimensionProperties` 等请求，并使用目标 sheet 的 `sheetId` 限定范围。
- Google Sheets API 当前的 `TableColumnDataValidationRule` 只能表达 dropdown 的 `ONE_OF_LIST` 选项，不能表达 Google Sheets UI 里的 dropdown chip 背景色、选项颜色、display style 或 multi-select 等 UI metadata。用 `updateTable` 重写 `columnProperties` 时，原 UI 选项颜色可能丢失。
- 不要尝试用 API 自动“修复” dropdown chip 颜色。已验证 `copyPaste` + `PASTE_DATA_VALIDATION` 不可靠，条件格式也不等价：设置背景色会把整个单元格染色，只设置文字色也只是灰色 chip 内的文字变色，都会偏离原生 chip 视觉。遇到这类需求时，应明确告知这是 Google Sheets API 缺口，保留现状、回退写入，或让用户在 UI/模板中手工维护。
- table dropdown 列不要再对同一范围叠加普通 `setDataValidation`；Google Sheets 会报错类似 `无法对指定类型的列中的单元格进行此操作`。应通过 `updateTable.columnProperties[].dataValidationRule` 维护 table dropdown 选项。

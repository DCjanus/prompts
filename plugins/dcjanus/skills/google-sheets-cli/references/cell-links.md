# 单元格链接

- Google Sheets 不支持 Markdown 的 `[text](url)` 链接语法；不要把 Markdown 链接直接写进单元格并期待 UI 渲染成链接。
- 只需要整格都是同一个链接时，可用 `values update --value-input-option USER_ENTERED` 写入 `=HYPERLINK("https://example.com", "显示文本")`。注意：这种方式会让整个单元格显示文本都成为同一个链接。
- 只想让单元格中的一小段文字带链接时，不要现场写 Python；优先用 `values update-rich-text`。

示例：只让备注里的 `knots-frontend !96` 这段文字带链接：

```bash
./scripts/gsheets_cli.py --json values update-rich-text \
  --spreadsheet-id <spreadsheet-id> \
  --range "Sheet1!I10" \
  --text "延期到 7/9：Backup AZ 约束仍在 knots-frontend !96 中。" \
  --links-json '[{"text":"knots-frontend !96","url":"https://git.example.com/group/project/-/merge_requests/96"}]'
```

如果同一段显示文字在单元格中出现多次，改用 `start` / `end` 明确字符位置：`[{"start":18,"end":36,"url":"https://..."}]`。

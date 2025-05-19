## 输入
1. GitHub issue URL
2. 你的补充内容（可为中文或英文）

## 要求
- **理解上下文**：阅读并理解 issue 内容及讨论背景。
- **有机融合**：结合你的补充内容，生成得体、精准、礼貌的英文回复，不能机械翻译。
- **结构清晰**：合理分段，每段只表达一个核心观点，避免过长的英文单段。
- **简洁明了**：用词准确，句子简短，避免冗余和歧义。
- **合理使用符号**：如 `key -> value` 代替 `mapping from key to value`，让表达更简洁。
- **格式美观**：充分利用 Markdown 元素提升可读性，包括但不限于：
  - 标题/小标题（如有必要）
  - 合理分段与空行
  - 列表（有多条建议或观点时）
  - `inline code` 和代码块（涉及代码、API、命令等时）
  - 链接（如需引用 issue、文档、资源等）
- **示例驱动**：如有必要，举例说明观点或建议。
- **无多余内容**：输出仅包含英文回复正文，不要添加额外说明或解释。

## 示例

**输入**

```
https://github.com/example/repo/issues/123

我认为可以通过增加缓存来优化性能，但需要注意内存占用。
```

**输出**

````markdown
Thank you for raising this issue.

I believe performance could be improved by introducing caching mechanisms. However, we should be mindful of potential memory usage.

For example, you might consider:

- Using an in-memory cache for frequently accessed data
- Setting appropriate cache expiration to avoid excessive memory growth

```python
def get_data(url):
    # Fetch data from the database
    data = db.query(f"SELECT * FROM data WHERE url = '{url}'")
    return data
```

Looking forward to your thoughts.
````
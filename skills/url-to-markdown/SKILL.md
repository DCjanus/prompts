---
name: url-to-markdown
description: 将网页 URL 转为 Markdown 便于阅读，通过 CloudFlare API 获取；若 URL 已明显是 Markdown 则不使用。
---

# URL 转 Markdown

在当前文件所在目录运行脚本：`./scripts/url_to_markdown.py URL`，URL 只支持 `http` / `https`。

需要先设置环境变量 `CLOUDFLARE_ACCOUNT_ID` 与 `CLOUDFLARE_API_TOKEN`。
其中 `CLOUDFLARE_API_TOKEN` 需要包含 `Browser Rendering - Edit` 权限。

已知限制：当前获取的 Markdown 基于网页整体内容，页眉页脚与广告等会被包含其中，信息过于详细。期望结果是仅正文内容的 Markdown，后续可考虑研究替代实现以提升正文抽取质量。

可选参数：
- `--output`：将 Markdown 写入文件（默认输出到 stdout）。
- `--cache-ttl`：缓存秒数，默认 60，设为 0 表示不缓存。

示例：

```bash
./scripts/url_to_markdown.py https://example.com --output ./page.md --cache-ttl 60
```

Reference：[`scripts/url_to_markdown.py`](scripts/url_to_markdown.py)

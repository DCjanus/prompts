---
name: fetch-url
description: 渲染网页 URL，去噪提取正文并输出为 Markdown（默认）或其他格式/原始 HTML，以减少 Token。
---

在当前文件所在目录运行：`./scripts/fetch_url.py URL`（仅支持 `http` / `https`）。  
说明：必须直接当作可执行文件执行。

脚本调用方式示例（不要用 `uv run python` 或 `python`）：
```bash
cd skills/fetch-url && ./scripts/fetch_url.py https://example.com --output ./page.md
```
错误示例：
```bash
uv run python skills/fetch-url/scripts/fetch_url.py https://example.com --output ./page.md
python skills/fetch-url/scripts/fetch_url.py https://example.com --output ./page.md
```

默认自动探测本地 Chromium 系浏览器路径；未探测到时需安装 Playwright 浏览器：

```bash
uv run playwright install chromium
```

参数：
- `--output`：将输出写入文件（默认 stdout）。
- `--timeout-ms`：Playwright 导航超时（毫秒，默认 60000）。
- `--browser-path`：指定本地 Chromium 系浏览器路径（默认自动探测）。
- `--output-format`：输出格式（默认 `markdown`），支持 `csv`、`html`、`json`、`markdown`、`raw-html`、`txt`、`xml`、`xmltei`；`raw-html` 直接输出渲染后的 HTML（不经 trafilatura）。
- `--disable-twitter-api`：关闭 Twitter/X 的 FxTwitter API 优化路径。

Twitter/X 特化（仅 `markdown`）：
- 当 URL 命中 `x.com`/`twitter.com` 推文链接且未设置 `--disable-twitter-api`，脚本会优先调用 `https://api.fxtwitter.com/2/status/{id}`。
- 输出的 Markdown 首行会包含注释，明确标记内容来自 FxTwitter API，而非直接访问页面。
- 若 FxTwitter API 请求失败，命令会直接报错（不降级到网页抓取）；如需跳过该逻辑，请显式传入 `--disable-twitter-api`。

示例：

```bash
./scripts/fetch_url.py https://example.com --output ./page.md --timeout-ms 60000
./scripts/fetch_url.py https://x.com/jack/status/20 --output-format markdown
./scripts/fetch_url.py https://x.com/jack/status/20 --output-format markdown --disable-twitter-api
```

Reference：[`scripts/fetch_url.py`](scripts/fetch_url.py)

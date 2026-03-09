---
name: fetch-url
description: 获取并提取链接正文（默认 Markdown）；内置 X/Twitter URL 处理，提升受限页面的抓取成功率。
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
- `--fetch-strategy`：仅 `markdown` 可用，支持 `auto`、`agent`、`jina`、`browser`。默认 `auto`。

BREAKING CHANGE
- 已删除 `--disable-twitter-api`。
- 影响范围：原先依赖 `--disable-twitter-api` 关闭 FxTwitter 的调用方式不再可用。
- 迁移方式：改为使用 `--fetch-strategy` 控制抓取路径。只有 `--fetch-strategy auto` 会对 Twitter/X 推文链接优先使用 FxTwitter；如果想跳过 FxTwitter，改用 `agent`、`jina` 或 `browser`。

Markdown 抓取顺序：
- Twitter/X 推文链接：只有 `--fetch-strategy auto` 时才会先走 FxTwitter API。
- 其它 Markdown 请求：`--fetch-strategy auto` 时先尝试原站 `Accept: text/markdown` 协商，再尝试 [Jina Reader](https://r.jina.ai/)，最后回退到本地 Playwright 渲染并提取。
- 如需更明确控制兜底方式，可手工指定：
  - `--fetch-strategy agent`：只尝试原站 Markdown 协商。
  - `--fetch-strategy jina`：只尝试 Jina Reader。
  - `--fetch-strategy browser`：直接走本地 Playwright。

限流或挑战页：
- 当前只会对 Jina Reader 做非常保守的明显限流页识别；只有命中少数高置信度特征时，才会继续回退到后续流程。
- 为避免误伤正常正文，这个判定刻意做得很窄；部分限流页没有被识别出来而直接输出是可接受的。
- 如果明确知道某个 reader 的结果不可用，agent 可以直接切换到更兜底的 `--fetch-strategy browser`。

Jina Reader：
- 脚本会读取环境变量 `JINA_API_KEY`；如果存在，就以 `Authorization: Bearer <token>` 方式传给 Jina Reader。
- 不设置 `JINA_API_KEY` 也能用 Jina Reader，但官方公开配额较低；当前按更保守口径可认为无 Key 时大约 `20 RPM`。
- 如果遇到 Jina Reader 限流，可提示用户配置 `JINA_API_KEY` 以提升配额；当前官方 Reader 产品页给出的普通 API Key 配额是 `500 RPM`，Premium 是 `5000 RPM`。

Twitter/X 特化（仅 `markdown`）：
- 当 URL 命中 `x.com`/`twitter.com` 推文链接且 `--fetch-strategy auto` 时，脚本会优先调用 [FxTwitter API](https://api.fxtwitter.com/)。
- 当 FxTwitter 返回 `thread` 数据时，Markdown 会附加 `## Thread` 小节，按顺序列出 thread 内其它推文（自动去重主推文）。
- 输出的 Markdown 会在元数据列表里标记内容来自 FxTwitter API，而非直接访问页面。
- 若 FxTwitter API 请求失败，命令会直接报错（不降级到网页抓取）；如需跳过该逻辑，请显式传入 `--fetch-strategy agent`、`jina` 或 `browser`。

示例：

```bash
./scripts/fetch_url.py https://example.com --output ./page.md --timeout-ms 60000
./scripts/fetch_url.py https://example.com --fetch-strategy jina
JINA_API_KEY=your-token ./scripts/fetch_url.py https://example.com --fetch-strategy jina
./scripts/fetch_url.py https://example.com --fetch-strategy browser
./scripts/fetch_url.py https://x.com/jack/status/20 --output-format markdown
./scripts/fetch_url.py https://x.com/jack/status/20 --output-format markdown --fetch-strategy browser
```

Reference：[`scripts/fetch_url.py`](scripts/fetch_url.py)

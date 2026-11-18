---
name: fetch-url
description: 提取网页或 X/Twitter 帖子正文，可输出 Markdown 或渲染后的 HTML。GitHub 仓库、Issue 与 PR 优先使用 github-cli。
---

# 网页正文提取

使用 [fetch_url.py](scripts/fetch_url.py) 读取 HTTP(S) URL，默认输出 Markdown 到 stdout。若 `github-cli` 已取得所需的 GitHub 资源内容，直接使用该结果。

```sh
./scripts/fetch_url.py https://example.com --output page.md
```

按 URL 的可见范围选择 Markdown 的 `--fetch-strategy`：

- 公开链接可用默认的 `auto`。X/Twitter 帖子按 ID 查询 FxTwitter；其他页面先向原站请求 Markdown，失败时将完整 URL 交给 Jina Reader，再按需使用本地浏览器。
- 内网、带签名或其他不宜交给第三方的链接，选 `agent` 只向原站协商 Markdown，或选 `browser` 在本地渲染。显式选 `jina` 时直接请求 Jina Reader，可通过环境变量 `JINA_API_KEY` 使用已有凭据。
- 需要原始渲染结果时用 `--output-format raw-html`。浏览器路径默认自动探测，也可用 `--browser-path` 指定；需要渲染且没有可用 Chromium 时，按 Playwright 的安装流程准备浏览器。其他格式、超时及输出参数见 `--help`。

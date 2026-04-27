---
name: confluence-cli
description: 查询、检索与阅读 Confluence 文档/页面。
---

说明：以下调用方式均以当前 `SKILL.md` 文件所在文件夹为 workdir。

脚本调用方式（必须直接执行，不要用 `uv run python` 或 `python`）：
```bash
cd skills/confluence-cli && ./scripts/confluence_cli.py --json page get --page-id 3060336952
```
错误示例：
```bash
uv run python skills/confluence-cli/scripts/confluence_cli.py --json page get --page-id 3060336952
python skills/confluence-cli/scripts/confluence_cli.py --json page get --page-id 3060336952
```

1) 常用子命令（覆盖日常场景）
- `space`
  - `list [--start --limit --expand]`
  - `get --space-key [--expand]`
- `page`
  - `get --page-id [--body-format --expand]`
  - `by-title --space-key --title [--body-format --expand]`
  - `children --page-id [--start --limit --expand]`
  - `publish-markdown --parent-id --title --markdown-path [--update-if-exists --body-format --expand]`
- `attachment`
  - `list --page-id [--start --limit --expand]`
  - `download --page-id [--output-dir --name --filter --all --start --limit --expand]`
- `search`
  - `--cql [--start --limit --body-format --expand]`

2) 输出格式
- 所有调用统一在脚本后、子命令前加 `--json`（示例：`./scripts/confluence_cli.py --json page get --page-id ...`）

3) 冷门参数/字段怎么查
- 运行 `./scripts/confluence_cli.py <command> --help` 查看该命令的参数
- 需要更深入的 Confluence API 字段时，可扩展脚本中的 `expand` 参数

4) 附件下载示例
- 下载指定附件（可重复传入 `--name`）：`./scripts/confluence_cli.py attachment download --page-id 3060336952 --output-dir ./attachments --name a.png --name b.png`
- 下载全部附件（自动分页）：`./scripts/confluence_cli.py attachment download --page-id 3060336952 --all --output-dir ./attachments`
- 过滤下载（正则）：`./scripts/confluence_cli.py attachment download --page-id 3060336952 --filter 'image2026-1-19_.*\\.png' --all --output-dir ./attachments`

5) 发布 Markdown 示例
- 发布到父页面（同名则更新）：`./scripts/confluence_cli.py --json page publish-markdown --parent-id 3061931928 --title "批量重置 Offset 功能测试" --markdown-path /path/to/doc.md`
- 本地图片发布时会按最大展示框自动生成单个 Confluence 尺寸属性：默认最大宽度 `1000`、最大高度 `800`，可用 `--image-max-width` / `--image-max-height` 覆盖；只写触发缩放的 `ac:width` 或 `ac:height`，不修改附件原图。
- 如需覆盖单张图片展示尺寸，可使用 Markdown title：`![图](./a.png "confluence-width=1200")`、`![图](./a.png "confluence-height=600")`、`![图](./a.png "confluence-size=original")`。

## 资源

- [confluence_cli.py](scripts/confluence_cli.py)：主 CLI 入口，负责读取配置并发起 API 调用。
- [confluence_api_client.py](scripts/confluence_api_client.py)：SDK 封装层，收敛常用 API 调用。

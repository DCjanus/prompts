---
name: confluence-cli
description: 查询、检索与阅读 Confluence 文档/页面。
---

说明：以下调用方式均以当前 `SKILL.md` 文件所在文件夹为 workdir。

1) 常用子命令（覆盖日常场景）
- `space`
  - `list [--start --limit --expand]`
  - `get --space-key [--expand]`
- `page`
  - `get --page-id [--body-format --expand]`
  - `by-title --space-key --title [--body-format --expand]`
  - `children --page-id [--start --limit --expand]`
- `search`
  - `--cql [--start --limit --body-format --expand]`

2) 输出格式
- 所有调用统一在脚本后、子命令前加 `--json`（示例：`./scripts/confluence_cli.py --json page get --page-id ...`）

3) 冷门参数/字段怎么查
- 运行 `./scripts/confluence_cli.py <command> --help` 查看该命令的参数
- 需要更深入的 Confluence API 字段时，可扩展脚本中的 `expand` 参数

## 资源

- [confluence_cli.py](scripts/confluence_cli.py)：主 CLI 入口，负责读取配置并发起 API 调用。
- [confluence_api_client.py](scripts/confluence_api_client.py)：SDK 封装层，收敛常用 API 调用。

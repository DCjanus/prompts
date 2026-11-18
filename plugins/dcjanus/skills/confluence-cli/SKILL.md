---
name: confluence-cli
description: 搜索和阅读 Confluence 页面、下载附件、重命名页面或发布 Markdown 到指定父页面。
---

# Confluence CLI

使用 [confluence_cli.py](scripts/confluence_cli.py)。全局 `--json` 放在子命令前；从 `--help` 和目标子命令帮助查询参数。

- 按标题和空间查页面用 `page by-title`，跨页面检索用 `search --cql`。读正文可用 `page get` 的 `--body-format` 和 `--expand`。
- 下载附件用 `attachment download`。重复 `--name` 指定文件；`--all` 自动分页，可配合 `--filter` 按正则筛选。
- 重命名前核对目标 page ID。发布 Markdown 用 `page publish-markdown --parent-id … --title … --markdown-path …`，默认更新该父页下的同名子页面。仅授权新建时先检查是否重名；有重名时保留原页。
- 写后验证正文时，使用 `page get --page-id … --body-format storage --expand body.storage,version --fresh` 绕过缓存。
- 发布成功后，仅用同次 shell 的 `&& rm -- <明确文件路径>` 清理自己为本次发布创建且不再需要的临时 Markdown。失败保留文件，用户文档、仓库文件与图片均保留。

发布支持 Markdown 表格对齐。本地图片的默认展示框为 1000 × 800，原图保留。全篇调整用 `--image-max-width` / `--image-max-height`；单图可用 Markdown title 指定 `confluence-width=1200`、`confluence-height=600` 或 `confluence-size=original`。

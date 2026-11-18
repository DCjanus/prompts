---
name: jira-cli
description: 查询和管理 Jira Server/Data Center 的工作项、Epic、评论、附件、工时、Saved Filter、Board 和 Sprint。
---

# Jira CLI

使用 [jira_cli.py](scripts/jira_cli.py)，契约为 Jira Server/Data Center 8.20.6、REST API v2。全局 `--json` 放在资源名之前，保留原始响应。通过顶层和子命令 `--help` 发现参数，例如 `./scripts/jira_cli.py issue edit --help`。

## 连接与查询

- 首次配置用 `config set --server … --prompt-token`。配置位于 `~/.config/jira-cli/config.toml`，权限为 `0600`；临时 token 用 `JIRA_API_TOKEN`，不放进参数、日志或回复。默认使用 HTTPS 并验证 TLS，只有用户明确要求才放宽。允许 HTTP 会明文传输凭据。
- 查询“我”的工作项或身份字段时，用 `--json user me` 识别当前 Jira 账号；指定其他用户时用 `user search` 核实。仅披露必要的身份信息。
- 用 `issue list --jql` 搜索。未封装的查询可用 `api get`，路径须以 `rest/` 开头。
- `filter favourites` 仅返回当前用户有权访问的收藏项。此版本无公开接口列举用户拥有的全部 Filter；保留这一缺口，不抓内部接口或 HTML。查已知 Filter 用 `filter get`，查其工作项用 `issue list --jql 'filter = FILTER_ID'`。

## 写操作

- 创建工作项须有明确请求，并先查重。修改、流转、删除前读取目标及状态。流转用 `issue transitions` 查实际 workflow 允许的动作。
- Description、Comment 与 Worklog Comment 原样发送 Jira wiki markup。编写正文时查阅 [格式与示例](references/wiki-markup.md)。多行内容用 `--description-file` 或 `--body-file`；额外字段可重复传 `--field KEY=JSON_OR_TEXT`。
- `issue edit` 的 `--set-label`、`--set-component`、`--set-fix-version` 整体替换字段；增减单项时先读取并保留其余值。clone 缺少目标项目必填字段时，用 `--field` 提供。
- Epic 使用配置的 `epic_name_field` 和 `epic_link_field`。移动已有归属须明确使用 `--allow-move`；`epic remove` 的第一个参数是预期的原 Epic。
- 工作项关联用 `link`，外部资源用 `remote-link`。工时默认保留 Remaining Estimate，仅在需要联动估时时选择 `auto`、`new` 或 `manual`；具体配套参数见子命令帮助。
- 删除工作项、评论、附件、关联或 Worklog 须传 `--yes`；仅在明确接受级联删除时加 `--delete-subtasks`。写操作测试只用本次新建且有唯一测试前缀的资源，结束后逆序删除并逐项回查 404。
- 单次临时正文用同次 shell 的 `&& rm -- <明确文件路径>` 在成功后清理；失败、仍需复用或验证时保留。不将变量、通配符、目录、用户文件或附件作为清理目标。

---
name: jira-cli
description: 通过内置 Python CLI 直接调用 Jira Server/Data Center REST API v2，查询、创建、编辑、流转和删除 Issue、Epic、Sub-task、评论、附件、关联、Watcher、Vote 与 Worklog，并查询项目、字段、Board 和 Sprint。适用于需要可控地操作 Jira、保留 Jira wiki markup、避免 smc jira 参数或转义行为影响请求的场景。
---

# Jira CLI

使用本 skill 自带的 `scripts/jira_cli.py`，不要改用 `smc jira`。当前契约面向 Jira Server/Data Center 8.20.6，不支持 Jira Cloud API v3 或 ADF。

## 首次配置

默认配置文件为 `~/.config/jira-cli/config.toml`。已有 `smc jira` 配置时，执行一次迁移：

```bash
cd skills/jira-cli
./scripts/jira_cli.py config import-smc
./scripts/jira_cli.py config show
```

迁移从 `~/.agents/jira_config.json` 读取 server、token、认证方式、默认项目和 Epic 自定义字段，目标 TOML 权限固定为 `0600`。默认不覆盖已有配置；确需覆盖时显式传 `--force`。

使用 `config set` 修改配置：

```bash
./scripts/jira_cli.py config set --default-project SATOS
./scripts/jira_cli.py config set --server https://jira.example --prompt-token
```

环境变量和全局选项可以临时覆盖配置，但不会反写 TOML：

- `JIRA_SERVER`
- `JIRA_API_TOKEN`
- `JIRA_USERNAME`
- `JIRA_AUTH_TYPE`
- `JIRA_TIMEOUT`
- `JIRA_VERIFY_SSL`
- `JIRA_DANGEROUSLY_ALLOW_HTTP`

默认只允许 HTTPS 并校验 TLS。只有用户明确要求时才使用
`--dangerously-allow-http` 或 `--dangerously-disable-tls-verification`；前者会让凭据明文传输。
临时 token 只通过 `JIRA_API_TOKEN` 传入，不接受可能进入 shell history 和进程参数的
`--token`。

## 调用约定

从 skill 目录直接执行；全局选项放在子命令之前：

```bash
./scripts/jira_cli.py --help
./scripts/jira_cli.py --json user me
./scripts/jira_cli.py --json issue get SATOS-261728
```

- `--json` 保留 Jira 原始响应结构，适合 Agent 和脚本处理。
- 普通模式提供 Rich 摘要或表格。
- 复杂正文优先写入临时文件，再用 `--description-file` 或 `--body-file` 传递。
- 额外字段使用重复的 `--field KEY=JSON_OR_TEXT`。

## 常用查询

```bash
./scripts/jira_cli.py server-info
./scripts/jira_cli.py user search jun.fan
./scripts/jira_cli.py project list
./scripts/jira_cli.py project versions SATOS
./scripts/jira_cli.py metadata fields
./scripts/jira_cli.py metadata issue-types
./scripts/jira_cli.py metadata create --project SATOS --type Task
./scripts/jira_cli.py issue list --jql 'assignee = currentUser() ORDER BY updated DESC'
./scripts/jira_cli.py board list --project SATOS
./scripts/jira_cli.py sprint list 12345
```

状态名称依赖真实 Workflow。流转前先查合法 transition，不猜测：

```bash
./scripts/jira_cli.py issue transitions SATOS-261728
./scripts/jira_cli.py issue move SATOS-261728 'Mark as Done' \
  --field 'resolution={"name":"Done"}'
```

未封装的查询可使用只读逃生口；路径必须以 `rest/` 开头，不支持任意写请求：

```bash
./scripts/jira_cli.py api get rest/api/2/priority
./scripts/jira_cli.py api get rest/api/2/search --param 'jql=project = SATOS'
```

## Issue 与 Epic

创建 Task 或 Sub-task：

```bash
./scripts/jira_cli.py issue create \
  --type Task \
  --summary '中文任务标题' \
  --description-file /tmp/description.txt

./scripts/jira_cli.py issue create \
  --type Sub-task \
  --parent SATOS-261716 \
  --summary '中文子任务标题'
```

编辑、指派和 clone：

```bash
./scripts/jira_cli.py issue edit SATOS-261728 --summary '新的标题'
./scripts/jira_cli.py issue assign SATOS-261728 'user@example.com'
./scripts/jira_cli.py issue clone SATOS-261728 --summary '复制后的标题'
```

Epic 使用配置中的 `epic_name_field` 和 `epic_link_field`：

```bash
./scripts/jira_cli.py epic create --summary 'Epic 标题' --epic-name '简短名称'
./scripts/jira_cli.py epic add SATOS-100 SATOS-101 SATOS-102
./scripts/jira_cli.py epic remove SATOS-101 SATOS-102
```

## 评论与链接

评论正文按 Jira wiki markup 原样发送，不做 Markdown 转换或转义。需要简洁且可点击的链接时使用：

```text
[Midgard MR !38|https://git.garena.com/example/-/merge_requests/38]
```

```bash
./scripts/jira_cli.py comment add SATOS-261728 --body-file /tmp/comment.txt
./scripts/jira_cli.py comment edit SATOS-261728 22384028 --body-file /tmp/comment.txt
./scripts/jira_cli.py comment list SATOS-261728
```

Issue link 和外部链接分别使用 `link`、`remote-link`：

```bash
./scripts/jira_cli.py link types
./scripts/jira_cli.py link add SATOS-1 SATOS-2 --type Relates
./scripts/jira_cli.py remote-link add SATOS-1 --title 'MR !38' --url https://git.example/mr/38
./scripts/jira_cli.py remote-link upsert SATOS-1 --global-id mr-38 \
  --title 'MR !38' --url https://git.example/mr/38
```

## 附件、Watcher、Vote 与 Worklog

```bash
./scripts/jira_cli.py attachment add SATOS-1 /tmp/evidence.txt
./scripts/jira_cli.py watcher list SATOS-1
./scripts/jira_cli.py watcher add SATOS-1 'user@example.com'
./scripts/jira_cli.py vote get SATOS-1
./scripts/jira_cli.py worklog add SATOS-1 --time-spent 30m --comment '排查问题'
```

使用各命令的 `--help` 查看完整参数。

## 删除与写操作安全

- 创建 Issue 前先搜索是否已有重复任务；除非用户明确要求，不自行创建 Jira 任务。
- 修改、流转或删除前先回读目标，确认 Issue key 和当前状态。
- Issue、评论、附件、关联和 Worklog 的删除均要求显式 `--yes`。
- 删除存在 Sub-task 的 Issue 默认失败；只有明确接受级联时才加 `--delete-subtasks`。
- 测试写操作只使用本次新建且带唯一测试前缀的临时资源，结束后逆序删除并逐项回查 404。
- 不在命令、日志或回复中输出完整 token；`config show` 只展示遮蔽值。

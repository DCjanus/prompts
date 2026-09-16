---
name: linear-cli
description: 通过内置 Python CLI 直接调用 Linear 官方 GraphQL API，查询和管理 workspace、team、issue、原生关系与 Custom View。适用于需要可控、可回读的 Linear 操作，不包含项目或个人工作流偏好。
---

# Linear CLI

使用 [linear_cli.py](scripts/linear_cli.py) 调用 Linear 官方 GraphQL API。本 Skill 只提供通用平台能力；不决定应该使用哪个 Team、状态、View、负责人或优先级，这些决策由调用它的项目 Skill 或用户请求提供。

## 认证

默认配置位于 `~/.config/linear-cli/config.toml`，文件权限固定为 `0600`。使用交互输入保存 token，不要把 token 放入命令行：

```bash
./scripts/linear_cli.py config set --auth-type api-key --prompt-token
./scripts/linear_cli.py config show
./scripts/linear_cli.py doctor
```

Linear OAuth 需要先注册 OAuth application 并取得 client ID。CLI 可以使用已取得的 OAuth access token：

```bash
./scripts/linear_cli.py config set --auth-type oauth --prompt-token
```

当前不内置共享 OAuth client，避免在公开 Skill 中捆绑 client secret。需要完整的 authorization-code/PKCE 与 refresh-token 流时，先为使用方注册 OAuth app，再扩展本 CLI。

环境变量优先于配置文件，适合 CI 和临时调用：`LINEAR_ACCESS_TOKEN`、`LINEAR_API_KEY`、`LINEAR_CONFIG`。OAuth token 使用 Bearer header，API key 直接作为 Authorization header。

## 调用约定

- 查看全部命令：`./scripts/linear_cli.py --help`。
- 读操作直接执行；写操作默认输出 JSON 预览，明确授权后才加 `--yes`。
- Team 必须通过 `--team` 显式提供，不设业务默认。先使用 `doctor --team KEY` 或 `team-show --team KEY` 解析实际 ID。
- Issue 写入后自动回读。关系写入回读两端。
- Custom View 使用官方 `customViews`、`customViewCreate` 和 `customViewUpdate` GraphQL 字段。`--filter-json` 接受官方 `IssueFilter` JSON object，不自行发明过滤语法。
- 写入前先读取现有 Issue 或 View 并查重；不把预览或 GraphQL HTTP 200 当成写入成功。

## 常用命令

```bash
./scripts/linear_cli.py doctor --team ENG
./scripts/linear_cli.py team-show --team ENG
./scripts/linear_cli.py issue-list --team ENG
./scripts/linear_cli.py issue-get ENG-123
./scripts/linear_cli.py issue-create --team ENG --title '标题'
./scripts/linear_cli.py issue-update ENG-123 --priority 2
./scripts/linear_cli.py relation-create ENG-123 ENG-456 --type related
./scripts/linear_cli.py view list
./scripts/linear_cli.py view get VIEW_ID
./scripts/linear_cli.py view create --name 'My work' --team-id TEAM_UUID \
  --filter-json '{"assignee":{"id":{"eq":"USER_UUID"}}}'
```

复杂正文或过滤器应由调用方先在可审阅的临时文件中准备；当前 CLI 接受内联 JSON，调用方必须注意 shell 引号。

---
name: linear-cli
description: 当需要查询或管理 Linear workspace、team、issue、原生关系或 Custom View 时使用。
---

# Linear CLI

使用 [linear_cli.py](scripts/linear_cli.py) 调用 Linear 官方 GraphQL API。本 Skill 只提供通用平台能力；不决定应该使用哪个 Team、状态、View、负责人或优先级，这些决策由调用它的项目 Skill 或用户请求提供。

GraphQL 客户端使用 `gql[httpx2]`。当前固定到首个支持 HTTPX2 的 `4.4.0b0` 预发布版本；升级前先确认后续稳定版仍保留 `httpx2` transport 行为。

## 认证

默认配置位于 `~/.config/linear-cli/config.toml`，文件权限固定为 `0600`。个人 API key 由用户本人在 Linear 创建，再通过隐藏的交互输入验证并保存；CLI 会先检查公开的 `lin_api_` 前缀与空白字符，再请求 Linear，验证失败不会覆盖已有配置。不要让 agent 接触 key，也不要把 key 放入命令行、剪贴板管道或日志：

```bash
./scripts/linear_cli.py auth login-api-key
./scripts/linear_cli.py config show
./scripts/linear_cli.py doctor
```

若已经保存 key 但服务端拒绝认证，使用 `auth repair` 复用现有凭据测试 API-key 与 Bearer 两种 header；命令只保存通过验证的模式，不显示 token，也不要求重新输入：

```bash
./scripts/linear_cli.py auth repair
```

Linear OAuth 需要先注册 OAuth application，将 `http://127.0.0.1:45831/callback` 加入 redirect URI，然后使用 client ID 执行 PKCE 登录。CLI 会校验 `state`、保存 refresh token，并在 access token 过期后自动刷新：

```bash
./scripts/linear_cli.py auth login --client-id CLIENT_ID
```

不内置共享 OAuth client 或 client secret；每个使用方显式选择自己的 OAuth app 和授权范围。已有 OAuth access token 时，也可用 `config set --auth-type oauth --prompt-token` 导入，但没有 refresh token 时无法自动刷新。

环境变量优先于配置文件，适合 CI 和临时调用：`LINEAR_ACCESS_TOKEN`、`LINEAR_API_KEY`、`LINEAR_CONFIG`。OAuth token 使用 Bearer header，API key 直接作为 Authorization header。

## 调用约定

- 查看全部命令：`./scripts/linear_cli.py --help`。
- 读操作直接执行；写操作默认输出 JSON 预览，明确授权后才加 `--yes`。
- Team 必须通过 `--team` 显式提供，不设业务默认。先使用 `doctor --team KEY` 或 `team-show --team KEY` 解析实际 ID。
- Issue 写入后自动回读。关系写入回读两端。
- Comment 写入必须通过 `--body-file` 传入正文，默认预览，正式写入后按 Comment ID 回读。
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
./scripts/linear_cli.py comment list ENG-123
./scripts/linear_cli.py comment create ENG-123 --body-file /tmp/progress.md
./scripts/linear_cli.py relation-create ENG-123 ENG-456 --type related
./scripts/linear_cli.py view list
./scripts/linear_cli.py view get VIEW_ID
./scripts/linear_cli.py view issues VIEW_ID
./scripts/linear_cli.py view create --name 'My work' --team-id TEAM_UUID \
  --filter-json '{"assignee":{"id":{"eq":"USER_UUID"}}}'
```

复杂 Issue 正文或过滤器应由调用方先在可审阅的临时文件中准备；当前 CLI 接受内联 JSON，调用方必须注意 shell 引号。Comment 正文只从 UTF-8 文件读取，避免多行内容进入 shell 参数。

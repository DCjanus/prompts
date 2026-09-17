---
name: dcjanus-tasklog
description: 当需要使用 DCjanus 的个人任务模型查询或管理 Linear Issue、Comment、Team、Workflow status、原生关系或 Custom View 时使用。
---

# DCjanus Tasklog

把 Linear 作为 DCjanus 的个人任务与注意力索引，并使用 [linear_cli.py](scripts/linear_cli.py) 调用 Linear 官方 GraphQL API。本 Skill 负责个人 Linear 任务模型与平台操作。

## 任务模型

- 一个 Issue 表达一个值得再次投入注意力、能够独立判断结果的目标，不把临时步骤或纯信息机械地建成 Issue。
- Description 保存稳定的任务背景、目标、范围、注意事项、完成条件和初始来源。只有这些稳定信息变化或需要修正事实错误时才改写 Description。
- Comment 按时间记录进展、阶段结论、决策、等待对象、恢复条件、下一步变化、交付证据以及完成或取消原因；不把命令流水账或完整外部记录复制进 Linear。
- 创建 Issue 时默认分配给当前 Linear 登录用户。只有用户明确指定其他负责人或要求不分配时才例外。
- 创建 Issue 未显式指定状态时，读取目标 Team 的实际 `Todo` 状态并在写入时显式传入，不依赖服务端默认值。只有用户明确指定其它状态时才可改用。
- 创建或写入前读取当前对象并查重，让用户审阅预览；写入后回读实际改变的字段。不把预览、HTTP 200 或 mutation 的初步返回当成最终成功。

GraphQL 客户端使用 `gql[httpx2]`。当前固定到首个支持 HTTPX2 的 `4.4.0b0` 预发布版本；升级前先确认后续稳定版仍保留 `httpx2` transport 行为。

## 认证

默认配置位于 `~/.config/linear-cli/config.toml`，文件权限固定为 `0600`。个人 API key 由用户本人在 Linear 创建，再通过隐藏的交互输入验证并保存；CLI 会先检查公开的 `lin_api_` 前缀与空白字符，再请求 Linear，验证失败不会覆盖已有配置。不要让 agent 接触 key，也不要把 key 放入命令行、剪贴板管道或日志：

```bash
./scripts/linear_cli.py auth login-api-key
./scripts/linear_cli.py config set-default-team DCJ
./scripts/linear_cli.py config show
./scripts/linear_cli.py doctor
```

默认 Team 是可选配置。设置后，所有原本接受 `--team` 的命令都可省略该参数；命令行显式传入的 Team 始终优先。需要恢复每次显式指定时，运行 `config clear-default-team`。设置命令会先调用 Linear 精确验证 Team key，并与已有认证配置合并保存，不会覆盖 token。

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

- CLI 按资源分组；从 `./scripts/linear_cli.py --help` 开始，再对 `team`、`issue`、`view` 等逐级使用 `--help`，不要依赖本文件穷举命令。
- 读操作直接执行；写操作默认输出 JSON 预览，明确授权后才加 `--yes`。
- Team 优先取命令显式提供的 `--team`；省略时读取配置中的可选 `default_team`。两者都没有时直接报错，不猜测业务 Team。使用 `config set-default-team KEY` 设置，使用 `config clear-default-team` 清除；可用 `doctor --team KEY` 或 `team show --team KEY` 精确验证。
- 需要按标题、描述或评论查找 Issue 时，使用 `issue search TERM [--team KEY]`，不要先批量导出再在本地过滤。搜索默认包含评论；需要查找归档事项时增加 `--include-archived`，根据返回的 `pageInfo.endCursor` 用 `--after` 继续翻页。
- 批量读取只需部分字段时，使用 `issue list --fields identifier,title,state,...` 传入逗号分隔的字段白名单，让 GraphQL 只返回所需字段；省略时保持完整默认输出。先用 `issue list --help` 查看支持的字段。
- 尚未封装的低频、一次性能力，在用户确认不需要补齐 CLI 后，可用 `api graphql QUERY_FILE --variables-file VARIABLES_JSON` 执行单个 GraphQL operation。query 可直接运行；mutation 必须同时提供 `--allow-mutation --yes`。GraphQL 和 variables 都从文件读取，不把复杂文档、变量或敏感内容拼进命令行。
- CLI 不支持的能力只要可能重复使用、已经进入日常流程，或每次都需要现场构造相同 GraphQL，先提醒用户是否要扩展稳定的资源子命令及测试；不默认用 `api graphql`、浏览器操作，或把内容写入错误字段来绕过缺口。
- Team 自动关闭与自动归档位于 `team automation`。周期单位为月；禁用设置使用对应的 `--disable-*`，自动关闭目标状态可传精确名称或 UUID。
- Workflow status 使用 `workflow-state list/create/update` 管理；创建前精确查重，写入默认预览并在完成后按 ID 回读。创建时的 `--type` 使用 Linear 原生类型，如 `backlog`、`unstarted` 或 `started`；更新支持名称、颜色、描述和位置，但 Linear 保留的 `Duplicate` 状态不可更新。
- Issue 写入后自动回读。关系写入回读两端。
- 复杂 Issue 描述通过 `issue create/update --description-file FILE` 从 UTF-8 Markdown 文件读取；短描述可继续使用 `--description`，两者不能同时指定。
- Issue Label 使用 `label list/get/create/update/delete` 管理；创建、更新和删除默认预览，正式写入后回读。创建默认作用于目标 Team，使用 `label create --workspace` 创建所有 Team 可用的 workspace Label；更新支持名称、颜色和描述，删除会移除已有 Issue 关联。
- Issue 生命周期操作位于 `issue archive/restore/delete`；`delete` 默认进入可恢复 30 天的 Recently deleted，只有管理员明确授权不可恢复删除时才使用 `--permanent --yes`。
- Comment 写入必须通过 `--body-file` 传入正文，默认预览，正式写入后按 Comment ID 回读。
- Custom View 使用官方 `customViews`、`customViewCreate` 和 `customViewUpdate` GraphQL 字段。`--filter-json` 接受官方 `IssueFilter` JSON object，不自行发明过滤语法。个人展示偏好通过 `view preferences get/update` 管理；`update` 用可重复的 `--set KEY=JSON_VALUE` 或 `--patch-file` 合并现有显式值，JSON `null` 删除对应覆盖，不为每个 preference 增加独立参数。

## 入口

```bash
./scripts/linear_cli.py --help
./scripts/linear_cli.py team --help
./scripts/linear_cli.py team automation --help
./scripts/linear_cli.py issue --help
./scripts/linear_cli.py label --help
./scripts/linear_cli.py workflow-state --help
./scripts/linear_cli.py view preferences --help
```

复杂 Issue 正文或过滤器应由调用方先在可审阅的临时文件中准备；Issue 正文使用 `--description-file`，内联 JSON 必须注意 shell 引号。Comment 正文只从 UTF-8 文件读取，避免多行内容进入 shell 参数。

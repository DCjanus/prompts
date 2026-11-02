# 认证与本地配置

首次接入、认证失败，或用户要求调整本机默认团队时读取。普通查询复用现有配置，不为每次任务重新登录或初始化。

## 选择处理路径

| 情况 | 下一步 |
| --- | --- |
| 验证已有接入 | `doctor`；团队相关问题可显式指定 `--team KEY` |
| 配置个人 API key | 由用户本人运行 `auth login-api-key`，在隐藏交互中输入 |
| 已保存 key，但服务端拒绝认证 | 用 `auth repair` 验证现有凭据的鉴权模式，不要求用户重发 key |
| 使用自己的 OAuth app | `auth login --client-id CLIENT_ID`；注册时允许下方本机回调 |
| 查看或设置默认团队 | `config show`、`config set-default-team KEY`、`config clear-default-team` |

具体参数与默认值从对应子命令的 `--help` 获取。

## 凭据与 OAuth

配置默认位于 `~/.config/linear-cli/config.toml`。不要读取或输出配置中的 token，不让用户把 key 发给 Agent，也不要把它放入命令行、剪贴板管道或日志；认证入口由用户自行完成隐藏输入。

OAuth 需要用户自己的 application，默认回调是 `http://127.0.0.1:45831/callback`。使用明确选择的 app 与授权范围，不借用共享 client/secret。已有 access token 可通过 `config set --auth-type oauth --prompt-token` 导入，但未保存 refresh token 时不能自动刷新。

临时调用或 CI 可用 `LINEAR_ACCESS_TOKEN`、`LINEAR_API_KEY`、`LINEAR_CONFIG`，其值优先于本地配置。OAuth token 使用 Bearer，API key 直接作为 Authorization。排障时不要把这些值打印出来。

## 团队选择

不知道团队 key 时用 `team list` 查询并完整翻页；它不受默认团队限制。显式 `--team` 优先于配置的 `default_team`；两者都没有时先确定目标。只在用户需要持久化默认值时更改配置，单次操作优先显式指定团队。

# 配置与认证

需要 `uv` 及能够访问 `https://api.tailscale.com` 的网络，不要求本机运行 tailscaled。
以下配置在用户本机完成，凭据不要通过聊天传递。

## 配置来源

Tailnet 选择优先级为全局 `--tailnet`、`TS_TAILNET`、TOML 的 `tailnet`。
使用明确的 tailnet ID 或名称，不使用 API 的 `-` 隐式别名。

默认配置文件为 `$XDG_CONFIG_HOME/tailscale-cli/config.toml`，
未设置 XDG 时为 `~/.config/tailscale-cli/config.toml`；可用全局 `--config` 指定。
普通调用不会创建或改写配置。配置文件不应纳入 Git；存储凭据时将权限设为 `0600`。

可以只保存 tailnet，再从环境变量提供凭据：

```toml
tailnet = "example.com"
```

## 认证方式

二选一：

| 方式 | 环境变量 | 对应 TOML 字段 |
| --- | --- | --- |
| API access token | `TS_API_KEY` | `api_token` |
| OAuth client credentials | `TS_CLIENT_ID`、`TS_CLIENT_SECRET` | `client_id`、`client_secret` |

只要设置了任意凭据环境变量，就完全使用环境变量认证，不与 TOML 凭据拼接。
同一来源中不能同时设置 API token 和 OAuth。OAuth 在每次命令执行时获取短期访问令牌，
不在磁盘缓存令牌；无需手动续期。

API token 可在后台 [Keys](https://console.tailscale.com/admin/settings/keys) 创建，
有效期为 1～90 天；这是管理 API token，不能使用用于设备入网的 auth key。
长期使用建议在后台 [Trust credentials](https://console.tailscale.com/admin/settings/trust-credentials)
创建 OAuth client，按用途配置权限：

| 用途 | Scopes |
| --- | --- |
| 读取、校验、预览 | `policy_file:read`、`devices:posture_attributes:read`、`devices:core:read` |
| 发布策略 | `policy_file`、`devices:posture_attributes`、`devices:core:read` |

`policy_file` 包含读取权限；旧 scope `acl` 对应当前的 `policy_file`。
401/403 时核对凭据、tailnet 和 scopes，不打印 secret 或完整认证响应。

## 发布契约

读取时可用 `policy get --output <新文件>` 保存原始策略，结果另含 ETag；
保存目标不能已存在，避免覆盖本地编辑。复制后编辑候选文件，将该次读取的 ETag
原样传给 `policy apply` 的 `--if-match`。例如，ETag 为 `"abc123"` 时，
shell 参数应写成 `'"abc123"'`。

默认 apply 只生成 diff 并校验，只有加 `--execute` 才发布。
校验失败以非零退出，即使服务端 HTTP 状态为 200；警告会保留在输出中供判断。
相同原始内容不重复写入。发布使用完整 HuJSON，包含 grants、SSH 等全部字段。
ETag 冲突不会自动合并，也不会自动重试写入。

JSON 模式下结果在 stdout，错误在 stderr，并以非零退出码报告失败。
服务端测试诊断可能包含用户名、地址和规则内容，分享输出前按实际需要脱敏。

参考：[API 与 token](https://tailscale.com/docs/reference/tailscale-api)、
[OAuth](https://tailscale.com/docs/features/oauth-clients)、
[Scopes](https://tailscale.com/docs/reference/trust-credentials)。

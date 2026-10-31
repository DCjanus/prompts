---
name: tailscale-cli
description: 查询 Tailscale 管理后台的设备、用户、DNS、路由、服务、密钥元数据、OAuth apps、Webhook、设置和日志，以及修改 grants、ACL、SSH 权限、groups、tagOwners、校验策略和预览匹配规则。
---

# Tailscale 管理

使用本 skill 的 [tailscale_cli.py](scripts/tailscale_cli.py) 调用官方 API。
从顶层 `--help` 到 `api --help` 或 `policy --help` 逐层探索参数；支持直接执行，
也可使用 `uv run --script`。全局 `--json` 放在子命令之前。

首次接入或认证失败时读取 [配置与认证](references/configuration.md)。
使用 1Password 时，授权只在当前 shell 环境上下文有效；先建立持续运行的交互
shell，在其中完成 `op signin`，并复用同一 shell 执行后续 CLI 调用。
不要为每次调用新建 shell，也不要把用户终端或其他工具会话中的授权视为当前已授权；
更换上下文后重新授权，不通过导出会话令牌或缓存明文凭据绕过此限制。
先运行 `auth check`，验证配置、凭据读取与策略读取权限；失败时按错误所在阶段处理。
`op whoami` 未登录不能单独证明桌面集成不可用，不以此阻止实际条目读取。
普通 `tailscale` CLI 操作本机连接；本 skill 操作 tailnet 的管理 API，
不通过本机登录状态获取管理权限。

## 后台只读查询

使用 `api list` 发现官方 GET 接口，可用 `--search` 按资源筛选；
使用 `api describe <operation>` 查看必填参数、类型与限制，再使用 `api get` 查询。
路径参数通过 `--param NAME=VALUE`、查询参数通过 `--query NAME=VALUE` 传入；
tailnet 使用全局配置。发现和查看接口不需要认证。

展示或区分设备、客户端时优先使用 `name`，保留 `-wsl` 等有区分意义的后缀；
可省略 tailnet 的 DNS 后缀，`hostname` 仅作补充，不能据此将不同设备展示为同名。

结果保留服务端 JSON 和分页信息；需要下一页时显式传回 cursor 等参数。
401/403 需核对权限，套餐不支持或资源不存在时如实报告，不解释为空数据。
部分接口尚处于 alpha/beta，网络流日志等能力还受套餐限制。
密钥及 Webhook 等响应可能包含敏感字段，按实际需要筛选结果再展示，不把完整响应写进仓库或 PR。
对应 scopes 与能力边界见 [配置与认证](references/configuration.md#后台查询权限)。

## 策略编辑

- 明确目标 tailnet，读取线上策略和 ETag，以保存的完整 HuJSON 为编辑基准。
  保留注释、无关配置与现有测试；新网络访问规则优先使用 grants，
  不顺带迁移已有 ACL。
- 按用户意图编辑规则，并按需补充 `tests` 中的允许与拒绝场景。
  使用校验及权限预览确认影响；预览针对指定用户或 IP:端口，不能替代真实连通性验收。
- `policy apply` 默认仅输出 diff 和服务端校验结果。检查 diff、警告及授权范围后，
  才使用 `--execute` 发布；用户已授权该具体变更时不重复询问。
- API 会替换整份策略；`--if-match` 必须使用编辑前读取的 ETag。
  冲突时重新读取并合并，不能换用新 ETag 后直接重发旧文件。
- 发布后以 CLI 的回读结果判断后台状态；请求结果未知或回读失败时先重新查询，
  不自动重试发布。修改网络或 SSH 权限后，按任务要求从相关设备验证允许与拒绝路径，
  区分策略已保存与实际连通性已验证。

只读调查不包含发布授权；创建本 skill 也不包含修改用户 tailnet 的授权。
本机优先将凭据保存在 1Password，以 `op_item` 引用，按配置参考完成接入。
凭据不写入仓库、PR、日志或回复；迁移时先验证保险库读回，再移除本机明文。

## 官方资料

- [策略语法](https://tailscale.com/docs/reference/syntax/policy-file)
- [Grants 语法](https://tailscale.com/docs/reference/syntax/grants)
- [API 文档](https://tailscale.com/api#tag/policyfile)
- [gitops-pusher](https://github.com/tailscale/tailscale/tree/main/cmd/gitops-pusher)：
  用户希望改用仓库及 CI 管理策略时使用，不与直接发布同时维护两个策略来源。

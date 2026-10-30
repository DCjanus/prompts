---
name: tailscale-cli
description: 查询和修改 Tailscale 管理后台的访问控制策略，包括 grants、ACL、SSH 权限、groups 和 tagOwners，以及校验策略和预览用户或目标地址的匹配规则。
---

# Tailscale 管理

使用本 skill 的 [tailscale_cli.py](scripts/tailscale_cli.py) 调用官方 API。
从顶层 `--help`、`policy --help` 到目标子命令逐层探索参数；支持直接执行，
也可使用 `uv run --script`。全局 `--json` 放在子命令之前。

首次接入或认证失败时读取 [配置与认证](references/configuration.md)。
普通 `tailscale` CLI 操作本机连接；本 skill 操作 tailnet 的集中策略，
不通过本机登录状态获取管理权限。

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
凭据在用户本机配置，不写入仓库、PR、日志或回复。

## 官方资料

- [策略语法](https://tailscale.com/docs/reference/syntax/policy-file)
- [Grants 语法](https://tailscale.com/docs/reference/syntax/grants)
- [API 文档](https://tailscale.com/api#tag/policyfile)
- [gitops-pusher](https://github.com/tailscale/tailscale/tree/main/cmd/gitops-pusher)：
  用户希望改用仓库及 CI 管理策略时使用，不与直接发布同时维护两个策略来源。

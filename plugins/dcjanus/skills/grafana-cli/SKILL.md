---
name: grafana-cli
description: 查询和管理 Grafana 的看板、数据源、告警和文件夹，执行 PromQL/LogQL 查询，或维护 Grafana 资源即代码；适用于自托管 OSS、Enterprise 和 Grafana Cloud。
---

# Grafana CLI

使用 Grafana 官方 `gcx`，按[官方操作指南](references/gcx.md)选择资源与查询命令。
自托管与 Cloud 的能力不同；根据目标实例和数据源选择，不能把 Cloud 专属能力当作
OSS 必需依赖。Grafana 随服务端附带的 `grafana cli` 主要管理插件与服务器，不是这里
用于远端资源管理的 CLI；不再新增基于已弃用 `grafanactl` 的流程。

## 工具与官方工作流

先确认 `gcx version`。未安装时按[官方安装指南](https://grafana.com/docs/grafana/latest/as-code/observability-as-code/grafana-cli/gcx/installation/)选择预编译二进制或包管理器；下载 release 时核对官方校验和。不要为安装 CLI 默认引入本机 Go 构建。

按目标逐层发现，不猜命令或展开整个命令库：

```sh
gcx help-tree --depth 1 -o text
gcx help-tree resources -o text
gcx resources get --help
```

遇到创建、维护看板或其它复杂任务，用 `gcx agent skills list` 发现当前版本附带的
官方 workflow，再用 `gcx agent skills get <skill> -o text` 读取。无需把整套官方 skills
再次全局安装，也不要把上游贡献者使用的 `.claude/skills` 当作使用端工作流。
命令与参数以当前二进制的 `--help` 为准；官方参考中的新能力可能尚未随稳定版发布。

## 目标与身份

已知目标时显式传 `--context <name>`，不因每个查询切换全局当前 context。目标不明或
连接失败时，用 `gcx config list-contexts`、`gcx config view` 和 `gcx config check`
排查；`GCX_CONFIG` 可将配置限定在单独文件，避免混入其它层的身份。

自托管配置需要真实 `grafana.org-id`，Cloud 使用 `stack-id`；确认组织后再配置。
启用了匿名访问的实例，可以只配置 `server`、`org-id` 和引用该 stack 的 context，
不设置 token、用户名或密码。用实际资源读取确认匿名权限，不能仅凭健康入口判断。
`config check` 显示 `Auth method: unknown (inferred)` 本身不代表匿名连接失败。

访问 Tailscale 上的实例时，使用用户指定的 tailnet 地址。401/403 时说明缺失的权限或
实例策略，不为让 CLI 工作而伪造 token、开启 Basic Auth、创建密码或扩大匿名角色。
需要认证的实例按[官方认证指南](https://grafana.com/docs/grafana/latest/as-code/observability-as-code/grafana-cli/gcx/authentication/)使用已有身份；OAuth 是 Cloud 能力，不能假定自托管可用。

## 查询与资源修改

- 输出默认用 `-o json`；大列表通过 `--json list` 发现字段，再选择所需字段或 `--jq` 聚合。
- 先列数据源并确认插件类型，按真实信号选择查询命令。Prometheus 数据源只能证明指标可查，不能由此承诺 Grafana 能查独立日志服务。
- 普通发现、查询、排障和看板维护使用直接命令；需要 Grafana Assistant 时沿用用户或项目的明确意图，不因未知指标或空结果自动发起计费 Assistant 工作。
- 资源写入先读取现状，在支持时 dry-run，应用后重新读取确认；删除或批量修改限定在用户授权范围，不把 agent mode 的自动确认当成额外授权。
- 已由仓库 provisioning 或资源代码管理的看板，修改权威配置并走项目发布流程。CLI 用于发现、读取与核验，不用临时远端写入替代受版本管理的来源。
- 专用命令覆盖的能力优先用专用命令；`gcx api` 仅用于当前 CLI 尚未覆盖的端点，不另写一套 REST 包装器。
- 用 `gcx config view` 查看脱敏配置，不读取原始凭据文件，不启用会记录认证正文的调试日志。

# API 能力与扩展

CLI 未覆盖当前需求，或需要核对官方 schema 时读取。先确认原生资源和现有 CLI 能力，再决定一次性调用还是扩展稳定子命令。

## 先核对能力

从 CLI 顶层和相关命令组的 `--help` 查起。没有专用命令或同名 mutation 不等于 API 不支持：核对目标能力是否属于已有原生资源，以及其输入字段和 JSON 数据。

例如周期 Issue 属于 `Template`，通过 `type=recurringIssue` 和 `templateData.schedule` 表达；应进入 [模板与周期事项](templates.md)，而不是另造周期模型、退回浏览器或用本机定时任务代替。

以当前官方文档、schema 和最小必要的现有对象回读为依据。必要时可用只读 GraphQL introspection 核对公开类型和输入，避免仅靠命名或旧记忆断言“不支持”。不要把能读取对象推断为能写入；写能力需要独立证据。

## 决定调用方式

- 会重复使用、已进入日常流程，或每次都要构造相同 GraphQL：先提醒用户是否扩展资源子命令及测试，默认不以 raw GraphQL 或浏览器长期绕过缺口。扩展沿用官方资源模型，避免叠加另一套业务抽象。
- 低频、一次性能力：用户确认不需要补齐 CLI 后，才用 `api graphql` 完成未封装操作。
- API 实际不支持时说明已核对的边界；其它执行方式按用户授权选择，不把替代手段伪装成 API 支持。

## 单次 GraphQL

query 和 variables 分别放入文件，用 `api graphql QUERY_FILE --variables-file VARIABLES_JSON` 读取。query 可直接运行；mutation 需要业务写入授权，并同时传入 `--allow-mutation --yes`。复杂内容不拼入命令行，凭据不写入文件或输出。

写入前预览具体目标与输入，之后按 ID 回读实际结果。请求已发出而响应不明时先查询状态，不直接重复 mutation。API 成功、对象配置正确和业务最终生效分别报告。

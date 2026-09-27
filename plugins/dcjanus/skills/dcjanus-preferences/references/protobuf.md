# Protobuf

- 类型化 RPC 默认优先考虑 Connect 生态，用同一份 `.proto` 生成服务端接口与各语言客户端；选服务端实现时确认所需的 Connect、gRPC 和 gRPC-Web 协议支持情况。Connect 运行时与代码生成插件不负责解析第三方 proto：用 `buf.yaml` 声明模块依赖、`buf.lock` 锁定版本，由 `buf generate` 解析本地及依赖的描述，再交给各语言插件生成代码。部分语言插件若需要依赖消息的生成代码，对该插件启用 `include_imports`，并检查生成包的导入路径。
- 当调用方要求特定 HTTP 方法、路径和 JSON 请求/响应时，可参考 [AIP-127](https://google.aip.dev/127)，用 `google.api.http` 在 proto 中声明 RPC 的 HTTP 映射，并由支持该注解的服务端或网关提供转码；普通 Connect RPC 不必添加映射。
- 表达时间点、固定时长、字段选择或部分更新等通用语义时，优先复用对应的 Protobuf [well-known types](https://protobuf.dev/reference/protobuf/google.protobuf/)（如 `google.protobuf.Timestamp`、`Duration`、`FieldMask`）；空请求或响应可使用 `Empty`，避免用裸字符串、数字或重复定义的消息替代。结构已知时仍定义具体消息；`Any`、`Struct` 仅用于确需动态内容。新 proto3 字段确需标量 presence 时使用 `optional`，不默认使用已过时的 `*Value` 包装类型。
- 新建通用资源部分更新 RPC 时，优先按 [AIP-134](https://google.aip.dev/134) 使用 `google.protobuf.FieldMask update_mask` 声明更新范围；服务端校验路径、明确缺省 mask 的行为，并仅修改选定字段，包括重置为零值，不只凭各字段的 `optional` presence 推断更新范围。`optional` 仍用于字段自身的 presence 语义。存量项目遵循原有契约；已用 `optional` presence 表达部分更新的接口继续沿用，不为统一风格迁移。
- 若调用链原生支持根据更新内容生成 `update_mask`（如 [gRPC-Gateway 的 HTTP PATCH 功能](https://grpc-ecosystem.github.io/grpc-gateway/docs/mapping/patch_feature/)），验证零值、清空与嵌套字段行为后优先使用自动生成；没有这项能力时由调用方显式传入。不要假定 `google.api.http` 注解或 Connect 协议本身会自动生成 mask。
- 服务端入参条件适合表达为 Protovalidate 规则时，优先直接写在 proto 的字段或消息注解中，让调用方从契约看到约束；在服务端边界用成熟拦截器或简短适配层实际执行规则，并把失败映射为 `INVALID_ARGUMENT`。先验证所选语言运行时和消息生成器是否兼容；业务状态、数据库引用和授权等仍由服务方法检查。避免仅写规则却不执行，或为接入校验而改写生成代码。
- Proto3 的 scalar、enum、string 和 bytes 字段，如果业务上不需要区分“未提供”和对应零值，默认省略显式 `optional`，让零值同时表示未指定。枚举应提供语义清楚的零值（例如 `*_UNSPECIFIED`）；查询条件可用空字符串或零值表示不参与筛选。
- 只有当 API 语义确实依赖 presence 时才使用 `optional`，例如必须区分“未提供”和 `0`、`false`、空字符串或零值枚举，或部分更新需要在没有 `FieldMask` 的情况下显式写入零值。
- Proto3 的 singular message 字段本身就有 explicit presence，通常不再添加冗余的 `optional`；`oneof` 也自带 presence。repeated 和 map 不区分未提供与空集合。
- 该偏好有意优先保持契约和生成代码简洁，不把 Protobuf 官方“basic types 总是添加 optional”的迁移建议作为默认；若外部协议、既有客户端、代码生成器、Edition 迁移或明确的 presence 语义提出不同要求，以实际兼容性约束为准。

## 兼容性判断

- Proto3 scalar、enum、string 或 bytes 字段在隐式 presence 与显式 `optional` 之间转换时，字段号和 wire type 不变，因此二进制 wire 格式兼容；但生成代码的字段表示与 presence API 可能变化，显式设置零值时的序列化和 merge 行为也不同，混用新旧客户端还可能丢失 presence。
- 因此，非 `optional` 改为 `optional` 不应笼统称为 wire breaking change，但对已经发布并有生成代码消费者的 API，应按潜在 source/API breaking change 和应用语义变化审查。使用严格 `FILE` 或 `PACKAGE` 类别时，Buf 可能通过 `FIELD_SAME_CARDINALITY` 报告该变化；仍需重新生成代码并检查直接消费者。
- 对 singular message 字段，添加或移除 `optional` 不改变其既有 explicit presence；Buf 也不认为这会改变 cardinality。即使如此，仍应以仓库实际生成器和兼容性检查结果为准。

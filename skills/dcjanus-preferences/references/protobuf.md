# Protobuf

- Proto3 的 scalar、enum、string 和 bytes 字段，如果业务上不需要区分“未提供”和对应零值，默认省略显式 `optional`，让零值同时表示未指定。枚举应提供语义清楚的零值（例如 `*_UNSPECIFIED`）；查询条件可用空字符串或零值表示不参与筛选。
- 只有当 API 语义确实依赖 presence 时才使用 `optional`，例如必须区分“未提供”和 `0`、`false`、空字符串或零值枚举，或部分更新需要在没有 `FieldMask` 的情况下显式写入零值。
- Proto3 的 singular message 字段本身就有 explicit presence，通常不再添加冗余的 `optional`；`oneof` 也自带 presence。repeated 和 map 不区分未提供与空集合。
- 该偏好有意优先保持契约和生成代码简洁，不把 Protobuf 官方“basic types 总是添加 optional”的迁移建议作为默认；若外部协议、既有客户端、代码生成器、Edition 迁移或明确的 presence 语义提出不同要求，以实际兼容性约束为准。

## 兼容性判断

- Proto3 scalar、enum、string 或 bytes 字段在隐式 presence 与显式 `optional` 之间转换时，字段号和 wire type 不变，因此二进制 wire 格式兼容；但生成代码的字段表示与 presence API 可能变化，显式设置零值时的序列化和 merge 行为也不同，混用新旧客户端还可能丢失 presence。
- 因此，非 `optional` 改为 `optional` 不应笼统称为 wire breaking change，但对已经发布并有生成代码消费者的 API，应按潜在 source/API breaking change 和应用语义变化审查。使用严格 `FILE` 或 `PACKAGE` 类别时，Buf 可能通过 `FIELD_SAME_CARDINALITY` 报告该变化；仍需重新生成代码并检查直接消费者。
- 对 singular message 字段，添加或移除 `optional` 不改变其既有 explicit presence；Buf 也不认为这会改变 cardinality。即使如此，仍应以仓库实际生成器和兼容性检查结果为准。

# 无序集合、多重集合与 ECMH 偏好

- 顺序无关、重复次数有意义，并需要增量增删或分片合并时，优先评估 ECMH。一次性集合摘要用规范编码、排序后计算 BLAKE3；顺序有意义时直接哈希有序表示；需要成员证明或差异定位时使用 Merkle tree 等认证数据结构。
- 元素必须使用稳定、无歧义且带域分离的编码。ECMH 允许负数 multiplicity，业务层仍需维护计数并拒绝无效删除。
- 继续增删或合并时保存完整累加器，不能只保存最终 digest。持久化或跨服务使用前固定算法套件、元素编码、状态格式版本和测试向量；“ECMH”这个名称本身不保证互操作。
- ECMH 不提供加密、认证或成员证明。不要自行实现曲线运算；生产选型需结合威胁模型、实现审计和实际 workload。

## Rust 实现参考

- `fastcrypto::hash::EllipticCurveMultisetHash` 使用 Ristretto 累加器，支持 `insert`、`remove` 和 `union`。其 `digest()` 不可组合，Serde 格式也不应直接视为稳定的跨语言协议。

依据：[ECMH 论文](https://arxiv.org/abs/1601.06502)、[fastcrypto 实现](https://github.com/MystenLabs/fastcrypto/blob/main/fastcrypto/src/hash.rs)。

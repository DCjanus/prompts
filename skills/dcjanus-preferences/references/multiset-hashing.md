# 无序集合、多重集合与 ECMH 偏好

## 何时选择 ECMH

- 当数据语义是顺序无关的多重集合、相同元素的重复次数需要影响摘要，并且需要按变更量增删元素，或让多个分片独立计算后合并固定大小的累加器时，优先评估 ECMH（Elliptic Curve Multiset Hash）。典型场景包括大型数据库状态/事务日志的增量一致性校验、流式多重集合相等性比较和分片数据对账。
- 如果只是偶尔对一个可完整读取的集合求摘要，优先将元素做稳定、无歧义编码，按编码字节排序后使用 BLAKE3；这通常更简单，也能沿用通用哈希的成熟工具链。
- 如果顺序本身属于业务语义，直接对规范化的有序表示使用 BLAKE3。只有明确把位置或稳定标识编码进每个元素后，才把有序数据转成 ECMH 的多重集合模型。
- 如果需要定位差异、证明某个元素存在/不存在，选择 Merkle tree、authenticated set/map 或适合该协议的 accumulator；ECMH 只提供整个多重集合的紧凑指纹，不能列出元素或生成成员证明。

## 数据与状态契约

- 先定义元素的规范编码与域分离：至少固定 schema/version、类型或用途标签、字段顺序、长度边界和字节编码。不同业务域不得只拼接裸字段后共用同一输入空间；更新对象时移除旧对象的完整编码，再插入新对象的完整编码。
- ECMH 的代数模型允许负数 multiplicity。若业务只允许普通多重集合，仍需在数据库或状态机中维护计数并拒绝不存在元素的删除；累加器自身不能验证这一约束。
- 需要继续 `insert`、`remove` 或 `union` 时，保存并交换完整累加器状态，不能只保存面向比较/展示的最终 digest。持久化或跨服务协议必须使用带版本的 envelope，至少标明算法套件、曲线/群、hash-to-group 映射、元素编码 schema 与实现格式版本。
- “ECMH” 不是足以互操作的 wire-format 名称。论文原始构造使用二元椭圆曲线，而实现也可以使用 Ristretto 等其它群与不同的 hash-to-group/digest 步骤；跨实现使用前必须固定完整套件、规范序列化和测试向量。

## 安全边界

- ECMH 的目标是碰撞抗性和可组合的多重集合摘要，不提供保密性、来源认证、防篡改权限或成员证明。低熵元素仍可被枚举；需要认证时由经过审查的协议对摘要及其上下文做 MAC 或签名，不把未认证的远端累加器直接当作可信状态。
- 同态结构意味着一次碰撞可导出任意 second preimage；论文因此建议在协议允许时使用 keyed intermediate hash。具体实现若没有 keyed 模式，不要自行拼装密码学构造，应结合威胁模型选择经过审查的方案。
- 不自行实现 hash-to-curve、曲线点验证或群运算。生产使用前检查实现维护状态、安全审计、侧信道性质、反序列化校验、状态格式稳定性、性能和协议兼容性；用目标 workload benchmark，不复用论文中特定 2016 CPU 与曲线实现的吞吐数字作为容量结论。

## Rust 实现参考

- `fastcrypto::hash::EllipticCurveMultisetHash` 是可评估的 Rust 实现：当前公开实现将输入经 SHA-512 映射到 Curve25519 的 Ristretto 群并累加点，支持 `insert`、`remove`、`union` 和完整状态的 Serde 序列化；`digest()` 再对累加器序列化结果做 SHA-256，返回 32 字节 digest。
- `fastcrypto` 的 digest 不能直接相加或相减；组合时必须保留 `EllipticCurveMultisetHash` 状态。它的 Serde/bincode 表示也不应在未固定版本和兼容性测试时直接成为长期或跨语言协议。

## 调研依据

- [Elliptic Curve Multiset Hash 论文](https://arxiv.org/abs/1601.06502)
- [fastcrypto 当前实现](https://github.com/MystenLabs/fastcrypto/blob/main/fastcrypto/src/hash.rs)

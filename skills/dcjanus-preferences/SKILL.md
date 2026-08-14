---
name: dcjanus-preferences
description: 记录 DCjanus 在不同语言中偏好的第三方库与使用场景，供 AI 在选型、引入依赖或替换库时优先参考。适用于 Python/Rust/Go 的库选择、技术方案对比、或需要遵循 DCjanus 个人偏好进行开发的场景。
---

## Usage

- 先确认语言，再读取对应参考文件。
- 引入或替换第三方库时优先使用偏好清单。
- 语言未覆盖或需求冲突时先向用户确认，再补充到对应语言文件。
- 新增语言时创建 `references/<language>.md` 并在此补充条目。

## General Preferences

- 哈希与密码派生按用途选择：普通数据校验、内容寻址、去重和缓存键等通用哈希场景默认优先 BLAKE3；用户密码存储与校验、基于密码派生加密密钥等需要抵抗离线暴力破解的场景默认优先 Argon2id。两者不可互换，不使用 BLAKE3、SHA-2 等快速哈希直接存储密码，也不使用 Argon2id 处理普通数据哈希。
- 使用 Argon2id 存储密码时优先采用成熟库的高层密码哈希接口，生成独立随机 salt，并保存包含算法版本、参数、salt 和摘要的 PHC 格式字符串；参数根据部署环境 benchmark，并支持在登录校验成功后检测和升级旧参数。用于密钥派生时保留重新派生所需的 salt 和参数，不直接持久化派生密钥。除非协议或合规要求，不默认选择 Argon2i、Argon2d、bcrypt 或 PBKDF2。
- 压缩算法默认优先在 snappy 与 zstd 之间按场景选择：偏低延迟/高吞吐时优先 snappy，偏更高压缩率与存储/传输成本时优先 zstd。尽量不要选择 gzip，因为它的速度和压缩率相比 snappy/zstd 通常没有显著优势；只有兼容既有协议、文件格式、客户端能力或运维工具链时再使用 gzip。

## Language References

- Python: `references/python.md`
- Rust: `references/rust.md`
- Go: `references/go.md`

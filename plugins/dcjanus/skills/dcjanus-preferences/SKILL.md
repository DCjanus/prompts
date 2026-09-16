---
name: dcjanus-preferences
description: 适用于创建、修改或评审 Skill，或在跨语言的数据存储、分析、压缩、归档、哈希、API/Protobuf 契约、Telegram Bot 消息呈现及 Python/Rust/Go 第三方库之间做技术选择的场景。
---

## Usage

- 先确认选型问题是否跨语言：数据库、分析、压缩或归档场景读取 `references/data-storage.md`；Protobuf 字段 presence 与兼容性判断读取 `references/protobuf.md`；Telegram Bot 消息能力选择读取 `references/telegram-bot-api.md`；语言生态库选择则读取对应语言参考文件。
- 引入或替换第三方库时优先使用偏好清单。
- 当工作负载同时具有多种特征、偏好清单未覆盖或与明确需求冲突时，先说明主要工作负载、取舍与建议；结论仍不明确时再向用户确认。
- 新增语言时创建 `references/<language>.md`；新增跨语言主题时创建聚焦该主题的 reference，避免将无关偏好堆入泛化的 general 文件。

## Skill Preferences

- Skill frontmatter 中的 `description` 只服务于发现与触发：用具体、可区分的任务、对象、症状或用户意图说明何时应该使用该 skill，并保留识别这些场景所需的关键词；不要概述内部实现、执行流程、工具步骤或正文细节。只有在能避免相邻 skill 实际误触发时，才补充排除边界。
- 自行维护的 CLI 型 skill 应让命令行界面本身支持渐进探索：按稳定的领域或资源与动作组织子命令，并让每层 `--help` 都能发现下一层能力。`SKILL.md` 只保留入口、路由与关键约束，引导 Agent 从顶层到目标子命令逐层查看帮助，不平铺全部命令、参数和示例；简单 CLI 不为了分层而增加层级。
- 判断 skill 修改是否属于 breaking change 时，以用户或 Agent 实际使用的对外契约为准，不因内部脚本的命令、参数或 API 变化机械地添加 breaking 标记。脚本仅由同一 skill 驱动且指令已同步更新，用户仍能完成同样的任务时，通常不属于 breaking change。只有当变更使用户可见能力、输出或持久化格式、显式调用方式失效，或该脚本已被明确承诺给用户、自动化或其它 skill 直接调用时，才按 breaking change 处理并说明迁移方法。
  - 通常不是 breaking：仅供 skill 内部调用的 CLI 将 `cluster list` 重组为 `cluster query list`，同时更新 `SKILL.md`；用户仍然只需要提出“列出集群”，Agent 也能完成同样的任务。
  - 属于 breaking：某个命令或 `--json` 输出结构已明确提供给用户自动化或其它 skill 直接调用，变更却删除命令、重命名字段或改变语义，导致这些调用者失效。

## General Preferences

- 哈希与密码派生按用途选择：普通数据校验、内容寻址、去重和缓存键等通用哈希场景默认优先 BLAKE3；用户密码存储与校验、基于密码派生加密密钥等需要抵抗离线暴力破解的场景默认优先 Argon2id。两者不可互换，不使用 BLAKE3、SHA-2 等快速哈希直接存储密码，也不使用 Argon2id 处理普通数据哈希。
- ECMH: 顺序无关、保留重复次数且支持增量增删/分片合并的多重集合 hash；一次性集合摘要仍优先规范编码、排序后使用 BLAKE3。ECMH 不适用于认证或成员证明，组合时保留累加器而不是最终 digest。
- 使用 Argon2id 存储密码时优先采用成熟库的高层密码哈希接口，生成独立随机 salt，并保存包含算法版本、参数、salt 和摘要的 PHC 格式字符串；参数根据部署环境 benchmark，并支持在登录校验成功后检测和升级旧参数。用于密钥派生时保留重新派生所需的 salt 和参数，不直接持久化派生密钥。除非协议或合规要求，不默认选择 Argon2i、Argon2d、bcrypt 或 PBKDF2。
- 压缩算法默认优先在 snappy 与 zstd 之间按场景选择：偏低延迟/高吞吐时优先 snappy，偏更高压缩率与存储/传输成本时优先 zstd。尽量不要选择 gzip，因为它的速度和压缩率相比 snappy/zstd 通常没有显著优势；只有兼容既有协议、文件格式、客户端能力或运维工具链时再使用 gzip。

## References

- 跨语言数据存储、分析、压缩与归档：`references/data-storage.md`
- Protobuf 字段 presence 与兼容性：`references/protobuf.md`
- Telegram Bot API 消息能力选择：`references/telegram-bot-api.md`
- Python: `references/python.md`
- Rust: `references/rust.md`
- Go: `references/go.md`

---
name: dcjanus-preferences
description: 适用于创建、修改或评审 Skill，设计或评审 CLI 的命名、输入手感、输出与补全，或在前端技术栈与无障碍组件、Connect/Protobuf API、well-known types、FieldMask/PATCH、AIP-127 HTTP 映射与 Protovalidate 校验、项目开发工具（含 mbx/Cargo）及版本管理、用户级程序的 XDG 数据目录、跨语言的数据存储、分析、压缩、归档、哈希、Telegram Bot 消息呈现及 Python/Rust/Go 第三方库之间做技术选择的场景。
---

## Usage

- 创建、修改或评审 Skill 时读取 [Skill 编写偏好](references/skill-writing.md)。
- 设计或评审 CLI 的命名、参数入口、输入手感、输出、交互和 shell 补全时读取 [CLI 设计偏好](references/cli-design.md)。
- 选择 React 前端框架、组件库、无障碍基础设施，或从 Protobuf 生成前端 Connect 客户端时读取 [前端偏好](references/frontend.md)。
- 选择 Protobuf well-known types、字段 presence、FieldMask 部分更新、Connect RPC、AIP-127 HTTP 映射、Buf 第三方 proto 依赖、Protovalidate 校验或判断兼容性时读取 [Protobuf 偏好](references/protobuf.md)。
- 先确认选型问题是否跨语言：数据库、分析、压缩或归档场景读取 [数据存储偏好](references/data-storage.md)；Telegram Bot 消息能力选择读取 [Telegram Bot API 偏好](references/telegram-bot-api.md)；语言生态库选择则读取对应语言参考文件。
- 选择 Python 第三方库时读取 [Python 偏好](references/python.md)；选择 Rust 库、RPC 服务栈或 Protobuf 消息生成链时读取 [Rust 偏好](references/rust.md)；选择 Go 第三方库时读取 [Go 偏好](references/go.md)。
- 安装 mbx、接入 fish/zsh 或排查构建入口时读取 [mbx 接入指南](references/mbx.md)。
- 引入或替换第三方库时优先使用偏好清单。
- 当工作负载同时具有多种特征、偏好清单未覆盖或与明确需求冲突时，先说明主要工作负载、取舍与建议；结论仍不明确时再向用户确认。
- 新增语言时创建 `references/<language>.md`；新增跨语言主题时创建聚焦该主题的 reference，避免将无关偏好堆入泛化的 general 文件。

## General Preferences

- 自己编写且可决定文件布局的用户级程序，尽量遵循上游的 [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)；包括在 macOS 上运行的个人 CLI 和脚本。macOS/Windows 原生应用、项目内文件及已有路径契约按相应平台或项目约定处理，不机械迁移。
- 项目开发工具及运行时版本优先使用 mise 管理，在 `mise.toml` 中共享配置；Rust 工具链默认使用 rustup 和项目级 `rust-toolchain.toml` 管理，不在 mise 中重复声明。已有工具链和语言包管理器沿用项目约定。
- Rust 本地构建默认优先用 mbx 包装 Cargo，以复用不同项目和 worktree 的编译结果；Cargo 仍负责依赖解析、构建调度和测试。已有 cargo-binstall 时优先用 `cargo binstall mbx` 安装，否则用 `cargo install mbx --locked`；用 mbx 自带的 `mbx setup` 接入普通 `cargo` 命令，并在 fish 和 zsh 中验证入口；已有项目明确的构建方式优先。
- 哈希与密码派生按用途选择：普通数据校验、内容寻址、去重和缓存键等通用哈希场景默认优先 BLAKE3；用户密码存储与校验、基于密码派生加密密钥等需要抵抗离线暴力破解的场景默认优先 Argon2id。两者不可互换，不使用 BLAKE3、SHA-2 等快速哈希直接存储密码，也不使用 Argon2id 处理普通数据哈希。
- ECMH: 顺序无关、保留重复次数且支持增量增删/分片合并的多重集合 hash；一次性集合摘要仍优先规范编码、排序后使用 BLAKE3。ECMH 不适用于认证或成员证明，组合时保留累加器而不是最终 digest。
- 使用 Argon2id 存储密码时优先采用成熟库的高层密码哈希接口，生成独立随机 salt，并保存包含算法版本、参数、salt 和摘要的 PHC 格式字符串；参数根据部署环境 benchmark，并支持在登录校验成功后检测和升级旧参数。用于密钥派生时保留重新派生所需的 salt 和参数，不直接持久化派生密钥。除非协议或合规要求，不默认选择 Argon2i、Argon2d、bcrypt 或 PBKDF2。
- 压缩算法默认优先在 snappy 与 zstd 之间按场景选择：偏低延迟/高吞吐时优先 snappy，偏更高压缩率与存储/传输成本时优先 zstd。尽量不要选择 gzip，因为它的速度和压缩率相比 snappy/zstd 通常没有显著优势；只有兼容既有协议、文件格式、客户端能力或运维工具链时再使用 gzip。

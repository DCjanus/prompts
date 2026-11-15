---
name: dcjanus-preferences
description: 应用 DCjanus 在 Skill 编写、个人仓库与 fork 维护、CLI/前端设计、技术选型和开发工具上的偏好。涵盖 Protobuf/Connect、数据存储、压缩与哈希、Telegram Bot，以及 Python/Rust/Go 库选择。
---

# 个人偏好

按当前决策读取对应参考；已有项目约定和用户新要求优先。引入或替换库时优先采用偏好清单，需求冲突时说明取舍；只有仍需用户决策时才询问。

| 任务 | 参考 |
| --- | --- |
| 创建、修改或评审 Skill | [Skill 编写](references/skill-writing.md) |
| 个人 GitHub 仓库的维护与合并策略 | [仓库维护](references/repository-maintenance.md) |
| 长期自用 fork 的分支、上游同步和改造记录 | [Fork 维护](references/fork-maintenance.md) |
| Action 版本、lockfile、CI 与发布 | [GitHub Actions](references/github-actions.md) |
| CLI 命名、参数、输出、交互与补全 | [CLI 设计](references/cli-design.md) |
| 前端布局、文案、React、无障碍组件和 Connect 客户端 | [前端](references/frontend.md) |
| Protobuf 类型、presence、FieldMask/PATCH、HTTP 映射、Buf 与 Protovalidate | [Protobuf](references/protobuf.md) |
| 数据库、分析、归档与压缩 | [数据存储](references/data-storage.md) |
| 数据哈希、ECMH、密码存储与密钥派生 | [哈希与密码派生](references/hashing.md) |
| XDG 数据目录、开发工具和运行时版本管理 | [开发环境](references/runtime.md) |
| Rust 本地构建、mbx/Cargo 入口与 shell 接入 | [mbx](references/mbx.md) |
| Telegram Bot 消息能力 | [Telegram Bot API](references/telegram-bot-api.md) |
| Python、Rust、Go 第三方库或服务栈 | [Python](references/python.md) · [Rust](references/rust.md) · [Go](references/go.md) |

维护偏好时，在对应主题 reference 中保存可跨项目复用的准则、适用条件和取舍，不保存项目名单、配置快照或历史。新增语言或跨语言主题使用聚焦的 reference，避免堆入通用文件。

---
name: dependency-management
description: 新增、移除或升级项目及长期维护脚本的依赖，以及修改项目版本时使用。一次性 Python 脚本使用 python-execution；库的选型比较使用 dcjanus-preferences。
---

# 依赖与项目版本管理

## 范围与版本选择

- 从目标项目的规范、manifest、锁文件和工具链确定包管理器与 workspace/package 范围；命令在目标项目执行，不能以 skill 目录作为项目目录。
- 保留项目已有工具链；没有指定时，前端使用 pnpm，Python 使用 uv。
- 仅新增或升级本次任务需要的依赖，优先采用满足项目运行时、兼容性和版本策略的最新稳定版本；不为遵循“最新版”升级无关依赖。
- 项目及长期维护脚本的依赖声明、锁文件及受工具管理的版本字段由对应工具更新，不手工编辑。一次性 Python 脚本按 [SKILL.md](../python-execution/SKILL.md) 直接生成无版本约束的 PEP 723 依赖声明；其它项目配置、描述文本等按任务正常编辑。
- 沿用项目的版本范围和锁定策略，非必要不额外固定版本；不要通过删除锁文件来追求最新版。

## 常用入口

| 目标 | 命令 |
| --- | --- |
| Rust 添加依赖 | `cargo add <crate>` |
| Python 项目添加依赖 | `uv add <package>` |
| 长期维护的 PEP 723 脚本添加依赖 | `uv add --script <script.py> <package>` |
| pnpm 项目添加依赖 | `pnpm add <package>` |
| 既有 npm 项目添加依赖 | `npm install <package>` |
| 既有 Yarn 项目添加依赖 | `yarn add <package>` |
| Go 添加或升级依赖 | `go get <module>@<version>`，本次需要最新版本时使用 `@latest` |
| Rust 修改 package version | `cargo set-version <version>` |

移除、升级以及 workspace 定位使用对应工具的子命令或参数；不确定时查看该工具帮助。开发依赖按项目已有分组处理。创建 PEP 723 CLI 的其余约定见 [SKILL.md](../uv-cli-creator/SKILL.md)。

## 结果核对

检查 manifest、锁文件和版本字段的最终差异，确认没有误改其它 workspace package、依赖分组或无关版本；传递依赖的必要变化按实际依赖关系判断。运行与变更相关的项目检查，明确仍需迁移的调用方或不兼容行为。

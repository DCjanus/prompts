---
name: change-request-writing
description: 编写或更新 GitHub/GitLab Issue、PR、MR 的标题与正文；适用于创建、修改、重写 reviewer-facing 描述、Risks、Breaking Change、避免低价值验证噪声与本地路径泄露等场景。
---

# Change Request Writing Skill

适用于 GitHub Issue/PR、GitLab Issue/MR 等提交给 reviewer/maintainer 的标题与正文。平台命令交给 [SKILL.md](../github-cli/SKILL.md) / [SKILL.md](../gitlab-cli/SKILL.md)；本 skill 只管文案内容。

## 创建前检查

在创建 Issue、PR 或 MR 前，先检查平台模板、表单和当前资源状态。

1. 优先检查 issue / PR / MR 模板、平台配置、项目说明文档、必填字段、标签、base/target 分支、squash 策略等仓库约束。
2. 若仓库要求特定标题格式、正文结构、关联 issue、检查项或其它平台字段，先按仓库要求准备，再补充本 skill 的默认格式。
3. 在正式创建前检查当前代码、分支与提交状态是否和准备提交到平台上的内容一致，避免创建出与现状不符的 Issue、PR 或 MR。

## 标题与正文原则

创建或更新标题与正文时，只描述当前需要提交给 reviewer/maintainer 的最终信息。

- PR/MR 必须只描述目标分支当前状态到当前分支最终状态的净变化；不要按 commit 历史、开发过程、临时实验或旧正文残留来写。
- 先确认 base/head 或 target/source，再用 final net diff 作为正文依据：`git fetch` 后查看 `git diff --stat <base-or-target>...HEAD` 与 `git diff --name-status <base-or-target>...HEAD`；必要时再看关键文件 diff 或平台 diff。
- 正文不要包含：中间提交顺序、调试过程、失败尝试、临时方案、merge/rebase/冲突解决过程、曾经实现过但最终 diff 已不存在的行为。
- 正文不要包含本机绝对路径、home 目录、agent 工作区路径、临时正文文件路径或其它会暴露个人/机器环境的信息；如需引用仓库内文件，使用相对路径或 Markdown 链接。
- PR/MR 正文默认不写 `Validation`。只有当验证内容提供 reviewer 在 diff 或平台 CI 状态里看不到的高信噪比行为证据时，才添加 `## Validation`。
- 不要把 CI、pipeline、workflow、job、格式化、lint、类型检查、构建、普通单元测试、仓库标准测试命令或“测试通过”写进正文；这些属于合入门槛，平台已经展示，信息增量低。
- 即使本地实际运行过 `go test ./...`、`cargo test`、`pnpm build`、`ruff check` 等命令，也不要为了证明“我测过了”而写入 PR/MR body；除非它是刻意构造的 red/green 回归验证，且 CI 不会自然覆盖这个信号。
- 可写的 `Validation` 应聚焦 CI 看不到的结果：真实环境/线上/测试集群验证、手工 UI/API/CLI 行为确认、外部服务集成、迁移 dry-run、性能或兼容性数据、安全边界验证，或 bug 修复中的稳定复现用例从失败到通过。
- 写 `Validation` 时描述“验证了什么行为和结果”，不要写命令流水账。不要记录探索性失败、调试命令或临时注入失败，除非它是最终交付的已知风险。
- 更新已有 PR/MR 正文时，不要在旧正文上做局部补丁；先回读当前正文，再基于 final net diff 重写完整正文并替换过时内容。
- 如果正文经历过实验性修改，最终更新前重新审视完整 PR/MR body，确保它只描述最终 diff；不要写 `rerun`、`after removing`、`now`、`previously` 这类暴露过程的措辞，除非过程本身是 reviewer 需要审查的证据。
- Breaking change 按 final net diff / 对外行为判断，不按中间 commit 机械继承；只有最终净变化确实破坏既有用法时，才在标题和正文标识。

## Issue

1. 若仓库要求 issue 必须包含特定字段、标签、复现步骤、版本信息、最小示例或分类，先据此整理内容；不要跳过必填项。
2. 若 issue 与当前本地改动或分支上下文有关，先检查相关代码、分支与提交信息，确认 issue 描述与现状一致，不要提交已经过时或与代码不符的内容。
3. 标题与描述保持简洁清晰，正文不要写入草稿路径或其它本机路径。

## PR/MR

默认标题与正文格式如下；如与团队、仓库、平台模板冲突，以既有约束为准。若有明确要求（如需中文），则优先遵循。

1. 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），简洁且描述核心目的；即使标题要求中文，语义化前缀仍需英文。
2. 有 breaking change 时标题用 `type(scope)!: short summary`，正文加 `BREAKING CHANGE:` 说明影响和迁移方式；否则不要加 `!` 或 `BREAKING CHANGE:`。
3. 描述风格：英文、短句和项目符号，优先让不看代码的读者快速理解动机、改动与影响，避免流水账与过多实现细节。涉及专有名词、函数名、方法名、类名、API 名称或配置键时，使用 inline code（反引号）包裹。
4. 默认正文格式：
   - `## Why`：1-2 条短句说明为什么要做这次改动，聚焦问题背景或目标。
   - `## What`：1-3 条说明主要变更，聚焦功能或行为层面的变化，不罗列琐碎实现细节。
5. 默认不要添加 `## Validation`；仅在有 CI 看不到的高信噪比行为证据时添加，否则省略。
6. 可选正文块：仅在确有必要时添加 `BREAKING CHANGE:`、`## Risks` 或 `## Notes`。

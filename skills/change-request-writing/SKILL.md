---
name: change-request-writing
description: 编写或更新 GitHub/GitLab Issue、PR、MR 的标题与正文；适用于创建、修改、重写 reviewer-facing 描述、Risks、Breaking Change、避免低价值验证噪声与本地路径泄露等场景。PR/MR 正文默认禁止 Validation；只有 CI/diff 看不到的高信噪比行为证据才允许写。
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
- GitLab MR/Issue 正文里的关联资源一律使用完整 Markdown URL，不要依赖短引用自动链接。
- 更新已有 PR/MR 正文时，不要在旧正文上做局部补丁；先回读当前正文，再基于 final net diff 重写完整正文并替换过时内容。
- 如果正文经历过实验性修改，最终更新前重新审视完整 PR/MR body，确保它只描述最终 diff；不要写 `rerun`、`after removing`、`now`、`previously` 这类暴露过程的措辞，除非过程本身是 reviewer 需要审查的证据。
- Breaking change 按 final net diff / 对外行为判断，不按中间 commit 机械继承；只有最终净变化确实破坏既有用法时，才在标题和正文标识。
- PR/MR 存在 breaking change 时，正文默认使用独立的 `## BREAKING CHANGE` 章节，至少分别说明影响范围与迁移方式；不要只在正文末尾放一行普通的 `BREAKING CHANGE:` 文本。
- Conventional Commit 的提交信息仍使用精确的 `BREAKING CHANGE:` footer；不要把提交 footer 语法机械套用为 PR/MR Markdown 的展示结构。

## Validation Gate

在写 PR/MR 正文前，先执行这个 gate。默认结论是“不写 `## Validation`”；不确定时也省略。

只有同时满足以下条件，才允许添加 `## Validation`：

1. 证据不在 final diff、平台 CI/checks、pipeline 状态或标准合入门槛中自然可见。
2. 证据能改变 reviewer 对风险的判断，而不是证明“我跑过测试”。
3. 证据描述的是最终交付行为，不是探索过程、失败尝试或临时调试。
4. 证据可以用行为结果表达，而不是命令流水账。

禁止写入 `Validation` 的内容包括：

- `just before_commit`、`cargo test`、`cargo nextest`、`cargo llvm-cov`、`go test ./...`、`pnpm build`、`pnpm test`、`ruff check` 等普通本地命令。
- lint、fmt、typecheck、build、unit test、integration test、coverage 数字、测试数量、CI job 名称、workflow 名称、pipeline 通过状态。
- “142 tests passed”“coverage 67.71%”“CI passed”“checks green”这类平台或标准测试已经表达的信息。
- 为了证明自己执行过命令而列出的命令清单。

允许写入的 `Validation` 例子：

- 真实环境、线上、测试集群、外部服务或手工 UI/API/CLI 行为确认，且 CI 不会自然覆盖。
- 迁移 dry-run、性能数据、兼容性矩阵、安全边界验证，且这些结果直接影响 reviewer 判断。
- Bug 修复中的 red/green 回归证据，前提是它是刻意构造的复现用例，且 CI 不会自然展示这个信号。

如果允许写 `Validation`，只写“验证了什么行为和结果”，不要写命令流水账。

## Issue

1. 若仓库要求 issue 必须包含特定字段、标签、复现步骤、版本信息、最小示例或分类，先据此整理内容；不要跳过必填项。
2. 若 issue 与当前本地改动或分支上下文有关，先检查相关代码、分支与提交信息，确认 issue 描述与现状一致，不要提交已经过时或与代码不符的内容。
3. 标题与描述保持简洁清晰，正文不要写入草稿路径或其它本机路径。

## PR/MR

默认标题与正文格式如下；如与团队、仓库、平台模板冲突，以既有约束为准。若有明确要求（如需中文），则优先遵循。

1. 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），简洁且描述核心目的；即使标题要求中文，语义化前缀仍需英文。
2. 有 breaking change 时标题用 `type(scope)!: short summary`，正文增加独立的 `## BREAKING CHANGE` 章节，明确列出影响范围与迁移方式；否则不要加 `!` 或 breaking change 章节。
3. 描述风格：英文、短句和项目符号，优先让不看代码的读者快速理解动机、改动与影响，避免流水账与过多实现细节。涉及专有名词、函数名、方法名、类名、API 名称或配置键时，使用 inline code（反引号）包裹。
4. 默认正文格式：
   - `## Why`：1-2 条短句说明为什么要做这次改动，聚焦问题背景或目标。
   - `## What`：1-3 条说明主要变更，聚焦功能或行为层面的变化，不罗列琐碎实现细节。
5. 默认正文只包含 `## Why` 和 `## What`；存在 breaking change 时必须再增加 `## BREAKING CHANGE`。不要添加 `## Validation`；只有通过上面的 Validation Gate 时才允许添加，否则省略。
6. 可选正文块：仅在确有必要时添加 `## Risks` 或 `## Notes`。

---
name: change-request-writing
description: 编写或更新 GitHub/GitLab Issue、PR、MR 与 inline review reply 的 reviewer-facing 文案；适用于创建、修改、重写标题、正文、设计取舍回复、Risks、Breaking Change，以及避免低价值验证噪声与本地路径泄露等场景。PR/MR 正文默认禁止 Validation；只有 CI/diff 看不到的高信噪比行为证据才允许写。
---

# Change Request Writing Skill

适用于 GitHub Issue/PR、GitLab Issue/MR 与 inline review reply 等提交给 reviewer/maintainer 的文案。平台命令交给 [SKILL.md](../github-cli/SKILL.md) / [SKILL.md](../gitlab-cli/SKILL.md)；本 skill 只管文案内容。

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
- GitHub reviewer-facing 文案引用同仓库 commit 时，一律写裸的完整 40 位 SHA；GitHub 会原生自动链接并缩短显示。不要包反引号，也不要手写 Markdown URL。引用其它仓库 commit 时使用 `owner/repo@完整 SHA`。
- GitLab reviewer-facing 文案里的关联资源一律使用完整 Markdown URL，不要依赖短引用自动链接。
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

## Inline review reply

Inline reply 的目标是用最低阅读成本消除 reviewer 对处理结果、设计理由或剩余风险的不确定性。

1. 写作前先确定回复的实际意图：接受并落实、部分落实、维持现状、推迟处理，或仅补充一种可能性。开头直接表达处理结果，不要把已经作出的决定、尚未确定的判断和开放想法混在一起。
2. 把原始评论、所在 diff 与当前 thread 视为共享上下文，不要复述 reviewer 已经看得到的信息。只补充验证当前决定所必需、但无法从现有上下文直接得出的内容，例如对应改动、非局部约束、关键理由或仍然存在的风险。
3. 让解释深度与 reviewer 的验证成本匹配。改动本身足以回答意见时，只给结果和可定位的改动引用；涉及设计判断时，说明决定性的约束、所选方案、实质性代价及其可接受依据。只有当替代方案有助于理解当前决定时才提及，不要记录完整探索过程。
4. 区分事实、推断、判断与承诺。对风险或可接受性的判断使用与决策相关的规模、频率、边界条件或系统不变量支撑；不确定的想法保持不确定，不要无意写成实施计划，也不要在并不需要答复时把它写成向 reviewer 提问。
5. 假定 maintainer 熟悉仓库，但不了解撰写者未公开的讨论过程。省略仓库常识，解释隐藏或跨文件的因果关系，并确保所有指代和结论都能从公开 thread 中还原。
6. 使用简洁、专业且与仓库一致的语言。每个段落只承担一个沟通目的，并按平台实际渲染调整结构；不要用更多段落、术语或修辞制造虚假的完整感。
7. 先稳定语义、立场和承诺强度，再润色或翻译。发送前重读完整 thread，确认回复仍然针对原始意见、引用对应最终代码，且没有把旧草稿或中间方案当成当前结论。
8. 仅修正文案时编辑原回复；出现新的独立信息时再追加回复。平台写入与 resolve 权限仍遵循对应交互 skill，未经用户明确授权不要发送或 resolve。

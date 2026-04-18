---
name: github-cli
description: 使用 GitHub CLI 与 GitHub 资源交互；适用于 repo、issue、PR、comment、release、workflow 等查看、更新或创建场景。
---

# GitHub CLI Skill

一句话说明：当任务核心是“和 GitHub 打交道”时，优先使用 `gh`，而不是把范围局限在 Issue/PR。

## 常用场景
- 仓库、Issue、PR、评论、release、workflow 等资源，优先先用 `gh <group> --help` 确认是否有现成子命令，再执行。
- 需要机器可读输出时，优先使用 `--json`，必要时再配合 `jq` 整理字段。

## PR Review
- 先看 PR 概览，再拉取 review / comment / thread 明细，确保不是只看单一来源。
- 必要时可以查看本地对应分支的代码；查看前先 `git fetch`，确保分支是最新远端状态。
- 当用户要求整理 PR 审查意见时，按严重程度从高到低排列，数字编号，方便用户回复。
- 每次最多展示 10 条；若还有更多，在末尾提示“还剩 N 条未展示”。
- 当用户要求回复 inline review comment 时，优先直接在线程里回复，不要把具体回复散落到总评论。
- 对已经完成的小改动，回复保持简短，优先使用 “Added in [b771da1ea](https://github.com/owner/repo/commit/b771da1ea).” / “Moved in [b771da1ea](https://github.com/owner/repo/commit/b771da1ea).” / “Adjusted in [b771da1ea](https://github.com/owner/repo/commit/b771da1ea).” 这类句式；commit 链接优先使用 `[short_sha](full_commit_url)` 形式，而不是笼统的 `[commit]`。
- 除非需要解释设计取舍或说明暂不修改的原因，否则不要在 inline reply 里重复 reviewer 原文或写过长说明。

## 快速查看
- 仓库概览：`gh repo view [owner/repo]`
- Issue 概览：`gh issue view <id|url>`
- PR 概览：`gh pr view <id|url>`
- Release 列表：`gh release list`
- Workflow 列表：`gh workflow list`

## 创建前检查
在创建 Issue 或 PR 前，先检查对应的 GitHub 模板、表单和当前资源状态。
1. 优先检查 issue / PR form 模板，以及 `.github/ISSUE_TEMPLATE/`、`.github/ISSUE_TEMPLATE.md`、`.github/PULL_REQUEST_TEMPLATE.md`、`.github/pull_request_template.md`、`.github/PULL_REQUEST_TEMPLATE/`、`.github/config.yml` 等 GitHub 专用配置。
2. 若仓库要求特定标题格式、正文结构、关联 issue、检查项、标签、base 分支或其它平台字段，先按要求准备，再补充本 skill 的默认格式。
3. 在正式创建前检查当前代码、分支与提交状态是否和准备提交到平台上的内容一致，避免创建出与现状不符的 Issue 或 PR。

## 创建 Issue（非交互）
以下规范建立在“创建前检查”已完成的前提上。
1. 若仓库要求 issue 必须包含特定字段、标签、复现步骤、版本信息、最小示例或分类，先据此整理内容；不要跳过必填项。
2. 若 issue 与当前本地改动或分支上下文有关，先检查相关代码、分支与提交信息，确认 issue 描述与现状一致，不要提交已经过时或与代码不符的内容。
3. 标题与描述风格同 PR，内容保持简洁清晰。
4. Issue 正文默认先写到本地 Markdown 文件；草稿优先放 `/tmp/*.md`。标题通常较短，可直接用 `--title` 传入。
5. 创建与修改时优先使用 `--body-file`，例如：`gh issue create --title "..." --body-file /tmp/issue-body.md`，或 `gh issue edit <id> --title "..." --body-file /tmp/issue-body.md`。
6. 创建成功后，输出完整 Issue URL。

## 创建 PR
以下标题与描述规范为默认推荐格式；如与团队/仓库/平台等既有约束冲突，以既有约束为准。若有明确要求（如需中文），则优先遵循。
1. 先完成“创建前检查”。
2. 只有在确认仓库要求与本地代码/提交状态都满足后，才创建 PR；若发现不满足，应先修正，再创建。
3. `git status` 必须干净，且当前分支已推送到远端。
4. 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），简洁且描述核心目的；即使标题要求中文，语义化前缀仍需英文。
5. 描述风格：英文、短句和项目符号，优先让不看代码的读者快速理解动机、改动与验证方式。重点是 what/why/testing，避免流水账与过多实现细节。若上下文不足以明确目标或约束，应主动向开发者确认后再撰写。涉及专有名词、函数名、方法名、类名、API 名称或配置键时，使用 inline code（反引号）包裹以提升可读性与准确性。
6. 默认正文格式：
   - `## Why`：1-2 条短句说明为什么要做这次改动，聚焦问题背景或目标。
   - `## What`：1-3 条说明主要变更，聚焦功能或行为层面的变化，不罗列琐碎实现细节。
   - `## Testing`：说明验证方式、命令或场景；未测试需注明原因。
7. 可选正文块：仅在确有必要时再添加。
   - `## Risks`：兼容性影响、潜在风险、回滚注意事项。
   - `## Notes`：reviewers 需要特别关注的点，或后续计划。
8. PR 正文默认先写到本地 Markdown 文件；草稿优先放 `/tmp/*.md`，不要在 shell 里拼多行字符串，也不要依赖交互式编辑。标题通常较短，可直接用 `--title` 传入。
9. 创建 PR 时优先使用 `--body-file`，例如：
```
gh pr create \
  --title "feat(scope): short summary" \
  --body-file /tmp/pr-body.md \
  --base main \
  --draft
```
10. 修改 PR 时也复用本地文件，避免手工编辑，例如：`gh pr edit <id> --title "..." --body-file /tmp/pr-body.md`。
11. 创建成功后，输出完整 PR URL。

## 更新 Issue/PR 标题或描述（前置要求）
在更新 Issue 或 PR 的标题/描述之前，必须先读取当前标题/正文（即将被修改的内容），再进行修改。

## 冷门参数怎么查
- `gh --help`
- `gh <group> --help`
- `gh <group> <subcommand> --help`

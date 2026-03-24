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

## 快速查看
- 仓库概览：`gh repo view [owner/repo]`
- Issue 概览：`gh issue view <id|url>`
- PR 概览：`gh pr view <id|url>`
- Release 列表：`gh release list`
- Workflow 列表：`gh workflow list`

## 创建 Issue（非交互）
1. 标题与描述风格同 PR，内容保持简洁清晰。
2. 使用非交互方式创建，避免进入编辑器或依赖手工输入。
3. 创建成功后，输出完整 Issue URL。

## 创建 PR
以下标题与描述规范为默认推荐格式；如与团队/仓库/平台等既有约束冲突，以既有约束为准。若有明确要求（如需中文），则优先遵循。
1. 确认 `git status` 干净，`git push` 到远端。
2. 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），简洁且描述核心目的；即使标题要求中文，语义化前缀仍需英文。
3. 描述风格：英文、短句和项目符号，优先让不看代码的读者快速理解动机、改动与验证方式。重点是 what/why/testing，避免流水账与过多实现细节。若上下文不足以明确目标或约束，应主动向开发者确认后再撰写。涉及专有名词、函数名、方法名、类名、API 名称或配置键时，使用 inline code（反引号）包裹以提升可读性与准确性。
4. 默认正文格式：
   - `## Why`：1-2 条短句说明为什么要做这次改动，聚焦问题背景或目标。
   - `## What`：1-3 条说明主要变更，聚焦功能或行为层面的变化，不罗列琐碎实现细节。
   - `## Testing`：说明验证方式、命令或场景；未测试需注明原因。
5. 可选正文块：仅在确有必要时再添加。
   - `## Risks`：兼容性影响、潜在风险、回滚注意事项。
   - `## Notes`：reviewers 需要特别关注的点，或后续计划。
6. 使用非交互式命令创建 PR，避免进入交互式编辑流程；按需补充 base、draft 等参数。
7. 修改 PR 时复用与创建时一致的非交互方式，避免手工编辑。
8. 创建成功后，输出完整 PR URL。

## 更新 Issue/PR 标题或描述（前置要求）
在更新 Issue 或 PR 的标题/描述之前，必须先读取当前标题/正文（即将被修改的内容），再进行修改。

## 冷门参数怎么查
- `gh --help`
- `gh <group> --help`
- `gh <group> <subcommand> --help`

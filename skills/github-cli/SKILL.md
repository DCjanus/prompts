---
name: github-cli
description: 使用 GitHub CLI 与 GitHub 资源交互；适用于 repo、issue、PR、comment、release、workflow 等查看、更新或创建场景。
---

# GitHub CLI Skill

一句话说明：当任务核心是“和 GitHub 打交道”时，优先使用 `gh`，而不是把范围局限在 Issue/PR。

## 常用场景
- 仓库、Issue、PR、评论、release、workflow 等资源，优先先用 `gh <group> --help` 确认是否有现成子命令，再执行。
- 需要机器可读输出时，优先使用 `--json`，必要时再配合 `jq` 整理字段。
- 用户明确要求调整 repository merge / squash 策略时，参考 [squash-merge-policy.md](references/squash-merge-policy.md)。

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
说明：以下脚本调用均以当前 `SKILL.md` 所在文件夹为 workdir。脚本必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`。
1. 优先运行本 skill 的创建前扫描脚本，输出中文摘要和“已检查”清单：
   - Issue：`cd /Users/dcjanus/Code/prompts/skills/github-cli && ./scripts/github_preflight.py --mode issue --repo <repo>`
   - PR：`cd /Users/dcjanus/Code/prompts/skills/github-cli && ./scripts/github_preflight.py --mode pr --repo <repo>`
2. 根据脚本输出读取候选模板、workflow 和本地脚本；脚本已检查的项目不要重复机械检查，除非输出显示有候选 enforcement 或你需要确认细节。
3. 对 Issue Form 模板，注意 `labels:`、必填字段和 checkbox。若当前账号可能不是仓库协作者，不要假设 `gh issue create --label ...` 或 REST API 的 `labels` 字段一定会生效；创建前先确认权限，或优先使用网页 Issue Form。创建后立即回读 issue，确认 label、state、自动检查评论都符合预期。
4. Issue/PR 标题与正文编写统一遵循 [SKILL.md](../change-request-writing/SKILL.md)。
5. 在正式创建前检查当前代码、分支与提交状态是否和准备提交到平台上的内容一致，避免创建出与现状不符的 Issue 或 PR。

## 创建 Issue（非交互）
以下规范建立在“创建前检查”已完成的前提上。
1. 标题与正文先按 [SKILL.md](../change-request-writing/SKILL.md) 准备。
2. Issue 正文默认先写到本地 Markdown 文件；草稿优先放 `/tmp/*.md`，标题通常较短，可直接用 `--title` 传入。
3. 如果仓库的自动检查依赖 Issue Form 自动应用的 label、类型或隐藏字段，优先打开网页表单创建；不要用普通 `gh issue create` 绕过表单。
4. 如果确认 CLI 创建可行，创建与修改时优先使用 `--body-file`，例如：`gh issue create --title "..." --body-file /tmp/issue-body.md`，或 `gh issue edit <id> --title "..." --body-file /tmp/issue-body.md`。
5. 创建成功后立即用 `gh issue view --json state,stateReason,labels,comments,url` 回读；若缺少模板要求的 label 或出现自动检查评论，先修正或重开，不要直接把该 issue 当作已完成。
6. 创建成功并验证通过后，输出完整 Issue URL。

## 创建 PR
以下规范建立在“创建前检查”已完成的前提上。
1. 先完成“创建前检查”。
2. 只有在确认仓库要求与本地代码/提交状态都满足后，才创建 PR；若发现不满足，应先修正，再创建。
3. `git status` 必须干净，且当前分支已推送到远端。
4. 标题与正文先按 [SKILL.md](../change-request-writing/SKILL.md) 准备。
5. PR 正文默认先写到本地 Markdown 文件；草稿优先放 `/tmp/*.md`，不要在 shell 里拼多行字符串，也不要依赖交互式编辑。标题通常较短，可直接用 `--title` 传入。
6. 创建 PR 时优先使用 `--body-file`，例如：
```
gh pr create \
  --title "feat(scope): short summary" \
  --body-file /tmp/pr-body.md \
  --base main \
  --draft
```
7. 修改 PR 时也复用本地文件，避免手工编辑，例如：`gh pr edit <id> --title "..." --body-file /tmp/pr-body.md`。
8. 创建成功后，输出完整 PR URL。

## 更新 Issue/PR 标题或描述（前置要求）
在更新 Issue 或 PR 的标题/描述之前，必须先读取当前标题/正文（即将被修改的内容），再进行修改。
更新标题或正文时，文案仍按 [SKILL.md](../change-request-writing/SKILL.md) 重新生成。

## 冷门参数怎么查
- `gh --help`
- `gh <group> --help`
- `gh <group> <subcommand> --help`

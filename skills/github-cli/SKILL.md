---
name: github-cli
description: 使用 GitHub CLI 与 GitHub 资源交互；适用于 repo、issue、PR、comment、release、workflow 等查看、更新或创建场景。创建任何 GitHub Issue 时，统一使用本 skill 的 github_issue.py，保留模板 labels/assignees 并在创建后回读验证。
---

# GitHub CLI Skill

一句话说明：当任务核心是“和 GitHub 打交道”时，优先使用 `gh`，而不是把范围局限在 Issue/PR。

说明：以下脚本调用均以当前 `SKILL.md` 所在文件夹为 workdir。

脚本调用方式（必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`）：

```bash
./scripts/github_issue.py --help
./scripts/github_preflight.py --help
```

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
- Inline review reply 的文案与 commit 引用格式统一遵循 [SKILL.md](../change-request-writing/SKILL.md#inline-review-reply)，本 skill 只负责读取 thread 状态与执行平台交互。

## 快速查看

- 仓库概览：`gh repo view [owner/repo]`
- Issue 概览：`gh issue view <id|url>`
- PR 概览：`gh pr view <id|url>`
- Release 列表：`gh release list`
- Workflow 列表：`gh workflow list`

## 创建前检查

在创建 Issue 或 PR 前，先检查对应的 GitHub 模板、表单和当前资源状态。

1. 优先运行本 skill 的创建前扫描脚本，输出中文摘要和“已检查”清单：
   - Issue：`cd /Users/dcjanus/Code/prompts/skills/github-cli && ./scripts/github_preflight.py --mode issue --repo <repo>`
   - PR：`cd /Users/dcjanus/Code/prompts/skills/github-cli && ./scripts/github_preflight.py --mode pr --repo <repo>`
2. 根据脚本输出读取候选模板和 workflow；脚本已检查的项目不要重复机械检查，除非输出显示有候选 enforcement 或你需要确认细节。
3. 对 Issue Form 模板，注意 `labels:`、必填字段和 checkbox；再用 `./scripts/github_issue.py inspect` 读取远端默认分支上的实际模板，避免本地 checkout 过期。
4. Issue/PR 标题与正文编写统一遵循 [SKILL.md](../change-request-writing/SKILL.md)。
5. 在正式创建前检查当前代码、分支与提交状态是否和准备提交到平台上的内容一致，避免创建出与现状不符的 Issue 或 PR。

## 创建 Issue（统一入口）

以下规范建立在“创建前检查”已完成的前提上。

1. **创建任何 Issue 都必须使用 `./scripts/github_issue.py create`。** 默认不要直接调用 `gh issue create`、`gh api`、REST/GraphQL 请求或网页表单。
2. 标题与正文先按 [SKILL.md](../change-request-writing/SKILL.md) 准备；正文必须先写到本地 Markdown 文件，草稿优先放 `/tmp/*.md`。
3. 有模板时先检查远端模板：

```bash
./scripts/github_issue.py inspect \
  --repo owner/repo \
  --template bug.yml
```

4. 正式创建前，必须先用完全相同的参数运行 `--dry-run`：

```bash
./scripts/github_issue.py create \
  --repo owner/repo \
  --template bug.yml \
  --title "short title" \
  --body-file /tmp/issue-body.md \
  --dry-run
```

5. dry-run 确认无误且用户已授权创建后，移除 `--dry-run` 正式执行。需要机器可读输出时加 `--json`。
6. 无模板的普通 Issue 仍使用同一入口，只是不传 `--template`；此时可用可重复的 `--label` / `--assignee`。脚本会在权限不足时提前失败，避免 GitHub REST 静默丢弃元数据。
7. Markdown template 与 YAML Issue Form 都通过 `--template <文件名>` 指定。模板场景不要再传 `--label` / `--assignee`；脚本会让 GitHub 服务端应用模板预设元数据，并在创建后回读验证。
8. 脚本优先读取 `GH_TOKEN` / `GITHUB_TOKEN`（GitHub Enterprise 对应变量），仅在环境变量不可用时调用 `gh auth token`。除鉴权兜底外，脚本直接调用 GitHub REST/GraphQL API。
9. 创建后若模板 labels/assignees 缺失，脚本会返回非 0 并保留已创建 Issue URL 供处理；不要把这种结果报告为成功。
10. 只有脚本明确报告不支持当前平台能力、且无法安全扩展时，才回退网页表单；回复中要说明回退原因。
11. 创建成功并验证通过后，输出完整 Issue URL。

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

---
name: gitlab-cli
description: 使用 GitLab CLI（glab）与 GitLab 资源交互；适用于 project、issue、MR、comment、wiki 等查看、更新或创建场景，含自建实例。
---

# GitLab CLI Skill

一句话说明：当任务核心是“和 GitLab 打交道”时，优先使用 `glab`，而不是把范围局限在 MR/Issue。

## MR Review
- 优先读取 MR discussions / notes / diff comments，再做统一整理。
- 必要时可以查看本地对应分支的代码；查看前先 `git fetch`，确保分支是最新远端状态。
- 当用户要求整理 MR 审查意见时，按严重程度从高到低排列，数字编号，方便用户回复。
- 每次最多展示 10 条；若还有更多，在末尾提示“还剩 N 条未展示”。

## 基本准备
- 确认身份与认证：
  - `glab auth status` 读取当前实例及 “Logged in to <host> as <user>” 行。
  - 直接取用户名：`GITLAB_HOST=<host> glab api /user | jq -r '.username'`（依赖本机 `jq`，若已设全局 `GITLAB_HOST` 可直接 `glab api /user`）。
  - 自建实例优先通过环境变量 `GITLAB_HOST` 指定；如需单次覆盖，可在命令前加 `GITLAB_HOST=<host>` 或用 `-R group/project`。
- 输出格式默认够用；若需机器可读，优先使用该子命令帮助里声明的格式参数，通常是 `--output json` 或 `-F json`。
- `glab` 不同子命令的参数风格不完全统一；不要默认假设所有命令都支持 `--json`，先看 `glab <group> <subcommand> --help`。
- 创建 MR 或 Issue 成功后，在终端**单独一行**输出 CLI 返回的完整 URL。

## 常用场景
- project、issue、MR、comment、wiki 等资源，优先先用 `glab <group> --help` 确认是否有现成子命令，再执行。
- 若 `glab` 没有直接子命令，但 GitLab API 支持该资源，优先改用 `glab api ...`。

## Issue 快速查看
- 只看正文：`glab issue view <id|url>`.
- 带讨论：`glab issue view <id|url> --comments`（必要时加 `--system-logs`）。
- 列表：`glab issue list --state opened --per-page 50 [-R group/project]`；过滤标签用 `--label foo,bar`。
- 添加评论：`glab issue note <id> -m "comment"`。

## MR 快速查看
- MR 概览（按需取字段）：`glab mr view <id|branch|url> --output json | jq -r '.title,.state,.author.username,.web_url,.description'`。
- 查看 diff：`glab mr diff <id|branch> --color=never`；需要原始 patch 用 `--raw`。
- 相关 issue：`glab mr issues <id>`。

## Wiki
- 先检查命令：`glab wiki --help`
- 若当前版本没有直接的 `wiki` 子命令，改用 `glab api` 访问对应项目 wiki API。
- 访问前先确认 project 路径或 `project_id`；自建实例场景优先显式设置 `GITLAB_HOST=<host>`。

## 创建前通用检查
在创建 Issue 或 MR 前，先检查仓库规范、模板或表单；若仓库另有要求，以仓库要求为准。
1. 优先查这些位置：`CONTRIBUTING.md`、`README.md` 中的贡献说明、`.gitlab/merge_request_templates/`、`.gitlab/issue_templates/`、`CODEOWNERS`，以及仓库里与提交规范或分支策略相关的说明。若仓库明确混用 GitHub 模板或在其它文件中引用等价模板，再按实际情况补查。
2. 若仓库要求特定标题格式、描述模板、关联 issue、检查项、标签、目标分支、签名提交、提交整理方式、测试/文档要求或其它必填字段，先按仓库要求准备，再补充本 skill 的默认格式。
3. 在正式创建前检查本地状态是否匹配这些要求：相关代码、当前分支、提交标题/历史、测试、文档与变更说明是否一致且完整。
## 创建 MR（非交互）
以下标题与描述规范为默认推荐格式；如与团队/仓库/平台等既有约束冲突，以既有约束为准。若有明确要求（如需中文），则优先遵循；未覆盖的部分再按本规范补齐。
1) 先完成“创建前通用检查”。  
2) 只有在确认仓库要求与本地代码/提交状态都满足后，才创建 MR；若发现不满足，应先修正，再创建。  
3) 当前分支必须已推送，且 `git status` 干净。  
4) 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），保持简洁且描述核心目的；即使标题要求中文，语义化前缀（如 `feat`、`fix`）仍需英文。  
5) 描述风格：英文、短句和项目符号，优先让不看代码的读者快速理解动机、改动与验证方式。重点是 what/why/testing，避免流水账与过多实现细节。若上下文不足以明确目标或约束，应主动向开发者确认后再撰写。涉及专有名词、函数名、方法名、类名、API 名称或配置键时，使用 inline code（反引号）包裹以提升可读性与准确性。  
6) 默认正文格式：
- `## Why`：1-2 条短句说明为什么要做这次改动，聚焦问题背景或目标。
- `## What`：1-3 条说明主要变更，聚焦功能或行为层面的变化，不罗列琐碎实现细节。
- `## Testing`：说明验证方式、命令或场景；未测试需注明原因。
7) 可选正文块：仅在确有必要时再添加。
- `## Risks`：兼容性影响、潜在风险、回滚注意事项。
- `## Notes`：reviewers 需要特别关注的点，或后续计划。
8) 特别强调：描述应聚焦 MR 合并前后系统的变化与影响，避免记录开发中的中间过程或修改步骤。
9) 用 heredoc 传多行描述，避免交互式编辑：
```
glab mr create \
  --title "feat(scope): short summary" \
  --description "$(cat <<'EOF'
## Why
- explain why

## What
- summarize key changes

## Testing
- list validation steps
EOF
)" \
  --target-branch main \
  --source-branch $(git branch --show-current) \
  --label bugfix \
  --draft \
  --yes
```
- 推荐参数（可按需开启）：`--remove-source-branch`（合并后删源分支）、`--squash-before-merge`（合并前压缩为单一 commit）；若团队偏好可省略。  
- 其他常用参数：`--reviewer user1,user2`、`--allow-collaboration`。  
- 修改已建 MR：`glab mr update <id> --title "..."
  --description "$(cat <<'EOF'\n...\nEOF\n)" --label ... --yes`。

## Issue 创建（非交互）
以下规范建立在“创建前通用检查”已完成的前提上。
- 若仓库要求 issue 必须包含特定字段、标签、复现步骤、版本信息、最小示例或分类，先据此整理内容；不要跳过必填项。
- 若 issue 与当前本地改动或分支上下文有关，先检查相关代码、分支与提交信息，确认 issue 描述与现状一致，不要提交已经过时或与代码不符的内容。
- 命令模式与 MR 类似，使用 `--title` 与 heredoc 描述：  
```
glab issue create \
  --title "feat: short summary" \
  --description "$(cat <<'EOF'\n- context\n- expected\nEOF\n)" \
  --label backlog,team-x \
  --assignee user1 \
  --yes
```
- 若需私密：加 `--confidential`；截止日期 `--due-date YYYY-MM-DD`。

## 常见选项速记
- `-R group/project`：指定自建实例项目，等价于完整 URL。
- `--per-page` 与 `--page`：分页查看列表或评论时使用。

## 更新 Issue/MR 标题或描述（前置要求）
在更新 Issue 或 MR 的标题/描述之前，必须先读取当前标题/正文（即将被修改的内容），再进行修改。

## 冷门参数怎么查
- `glab --help`
- `glab <group> --help`
- `glab <group> <subcommand> --help`
- API 字段不明确时：`glab api --help`

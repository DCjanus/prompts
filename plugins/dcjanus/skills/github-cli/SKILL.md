---
name: github-cli
description: 使用 gh 查看或管理 GitHub 的 repo、Issue、PR、comment、release 和 workflow。
---

# GitHub CLI

平台资源读取与操作使用本 skill；标题、正文和 review reply 使用 [repository-workflow](../repository-workflow/SKILL.md)。

## 入口

- 常规操作优先使用 `gh`，不确定能力时从对应命令的 `--help` 查询；机器可读输出使用 `--json`。
- 持续等待 workflow、job 或 PR checks 时读取 [Actions 等待](references/actions-wait.md)，使用统一脚本，不自行轮询。
- 用户明确要求个人合并策略时使用 [dcjanus-merge-policy](../dcjanus-merge-policy/SKILL.md)。

## 创建与更新前

- 创建 Issue/PR 前运行 `scripts/github_preflight.py --mode issue|pr --repo <目标仓库绝对路径>`；根据结果读取适用模板、必填字段和 workflow，不重复检查脚本已覆盖的项目。
- Issue 模板还需通过 `scripts/github_issue.py inspect` 核对远端默认分支版本，保留模板 labels/assignees。
- 更新标题或正文前先读取当前内容与状态。独立 Issue 不要求本地有提交或干净工作区。
- PR 的本次交付改动须已提交并推送，远端 head 与拟交付版本一致；保留并排除用户无关未提交改动。验证结果应对应交付提交。
- 多行正文先写入 Markdown 文件，通过 `--body-file` 传入；短标题可用 `--title`，不在 shell 中拼多行正文。

## Issue

创建统一使用 `scripts/github_issue.py create`，参数从 `--help` 查询。

- 正式创建前，用相同参数运行 `--dry-run`；确认结果且已获得创建授权后去掉该参数执行。
- 有模板时用 `--template <文件名>`，不再传 `--label` / `--assignee`；无模板时可用这两个参数。
- 脚本会回读模板元数据；缺失 labels/assignees 时返回非零并保留资源 URL，须处理已有 Issue，不报告成功或重复创建。
- 只有脚本明确不支持当前平台能力且无法安全扩展时，才回退网页表单并说明原因。

## PR

- 创建统一使用 `scripts/github_pr.py create`；更新正文使用 `scripts/github_pr.py update <number|url> --repo owner/repo --body-file <path>`。其它参数从 `--help` 查询，两入口均支持 `--dry-run`。
- 创建默认允许维护者修改；脚本自动回读核验正文和适用权限。复用脚本已完成的验证，仅补查状态、CI 和未覆盖元数据；验证失败但已有 URL 时处理现有资源，不重复创建。

成功后输出完整资源 URL。仅在成功且不再复用时，用同次 shell 的 `&& rm -- <明确文件路径>` 清理本次临时输入；失败保留，不用变量、通配符或目录作为清理目标，不删除用户文件、仓库文件或待验证材料。

## PR Review

- 先看 PR 概览，再拉取 review / comment / thread 明细，确保不是只看单一来源。
- 必要时可以查看本地对应分支的代码；查看前先 `git fetch`，确保分支是最新远端状态。
- 当用户要求整理 PR 审查意见时，按严重程度从高到低排列，数字编号，方便用户回复。
- 每次最多展示 10 条；若还有更多，在末尾提示“还剩 N 条未展示”。
- 当用户要求回复 inline review comment 时，优先直接在线程里回复，不要把具体回复散落到总评论。

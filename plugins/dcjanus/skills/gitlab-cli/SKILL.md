---
name: gitlab-cli
description: 使用 glab 查看或管理 GitLab 的 project、Issue、MR、comment、wiki 和 CI，含自建实例。
---

# GitLab CLI

平台资源读取与操作使用本 skill；标题、正文和 review reply 使用 [repository-workflow](../repository-workflow/SKILL.md)。

## 入口

- MR/Issue 创建与更新、GitLab CI lint 使用 [gitlab_cli.py](scripts/gitlab_cli.py)，从顶层和目标子命令的 `--help` 查询参数。
- 其它操作优先用 `glab`；不确定能力时查对应命令帮助，没有子命令再用 `glab api`。
- 脚本通过 `--cwd <repo>` 指定目标仓库，`--hostname <host>` 指定自建实例；不在目标仓库时用 `--project <id|group/project>`。
- MR internal ref 的 CI lint 可用 `--ref refs/merge-requests/<iid>/head`；已知源分支时传 `--source-branch`，否则脚本查询 MR。

## 创建与更新

- 创建前检查适用的 `.gitlab/issue_templates/`、`.gitlab/merge_request_templates/` 和项目 CI 要求；更新前读取当前标题、正文与状态。
- MR 的本次交付改动须已提交并推送，远端 source 与拟交付版本一致；保留并排除用户无关未提交改动。验证结果应对应交付提交。独立 Issue 不要求本地有提交或干净工作区。
- 正文写入 Markdown 文件，通过 `--description-file <path>` 传入；短标题可用 `--title`。不得在 shell 参数中拼接多行正文。
- 除非仓库或用户要求保留多 commit 或源分支，创建 MR 时显式传 `--squash true --remove-source-branch true`。
- MR create/update 支持 `--dry-run`，并自动回读核验标题和正文；复用核验结果，仅补查状态和未覆盖的元数据。Issue 写入后需回读核验。失败但已有 URL 时处理现有资源，不重复创建。
- 成功后输出完整资源 URL。仅在成功且不再复用时，用同次 shell 的 `&& rm -- <明确文件路径>` 清理本次临时正文；失败保留，不用变量、通配符或目录作为清理目标，不删除用户文件或待验证材料。

## Review、CI 与合并

- 审查先读 MR 概览、discussions、notes 和 diff comments，再汇总；回复尽量留在对应线程。
- 等待 pipeline 用 `glab ci status --live --compact`，按需指定 `--branch` 和 `-R`；跟随 job 日志用 `glab ci trace`，不自行轮询。
- 报告最终状态时，用 `glab ci get` 或 `glab api` 锁定目标 pipeline 和提交读取机器可读结果，避免把动态日志结束当作检查通过。
- 用户要求“可以合并”或“准备好合入”时读取 [MR 合入门禁](references/merge-readiness.md)；无冲突和 CI 通过不等于满足全部项目策略。
- 用户明确要求个人合并策略时使用 [dcjanus-merge-policy](../dcjanus-merge-policy/SKILL.md)。

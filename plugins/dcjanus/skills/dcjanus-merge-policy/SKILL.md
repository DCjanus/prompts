---
name: dcjanus-merge-policy
description: 将 GitHub 或 GitLab 仓库配置为 DCjanus 偏好的合并策略，包括 squash、组织仓库的 merge queue、提交消息模板和源分支删除设置。适用于明确要求采用 DCjanus 个人合并策略的场景，不用于一般 PR/MR 合并操作。
disable-model-invocation: true
---

# DCjanus Merge Policy

这是 DCjanus 的个人偏好，不是通用最佳实践。修改 repository/project 级合并设置；GitHub 组织仓库同时启用默认分支的 merge queue。除队列专用规则集外，不调整其它 branch protection 或 ruleset，也不执行 PR/MR 合并。

## 直接调用

- 常规配置直接运行附带脚本，无需阅读 Python 源码。参数不明确时先查看 `--help`；只有执行失败需要排障，或任务明确要求审计、修改脚本时，才阅读实现。
- 用户明确要求对目标仓库应用本策略即已授权配置，包括组织仓库的 merge queue；仅讨论策略或修改本 skill 不代表授权修改远端仓库设置。
- 将下列 `<skill-dir>` 替换为本 `SKILL.md` 所在目录的绝对路径，不从目标仓库目录推断脚本位置。
- 需要本机 `uv`，以及已登录目标平台且有修改仓库设置权限的 `gh`（GitHub）或 `glab`（GitLab）。

GitHub：

```bash
uv run --script <skill-dir>/scripts/configure_github.py --repo <owner/repo>
```

GitLab：

```bash
uv run --script <skill-dir>/scripts/configure_gitlab.py --project <group/project-or-id> --hostname <gitlab-host>
```

两个脚本均支持 `--cwd <目标仓库目录>`、`--hostname <host>` 和 `--json`。GitLab host 能从执行目录正确确定时可省略 `--hostname`；GitHub 自建实例也应显式指定 host。

脚本会直接写入配置，然后回读校验并输出结果；回读不匹配时列出字段并非零退出。失败不代表没有写入，应根据错误核对实际设置，不盲目重试。

## GitHub 策略

- 只允许 squash merge，禁用 merge commit 和 rebase merge。
- 开启 Allow auto-merge，让用户可为单个 PR 启用自动合并；只有该 PR 明确启用后，才会在必需检查和审批等合并条件满足时自动合并。
- squash commit 标题与正文分别采用 PR 标题和正文；平台可继续自动追加 PR number、分隔线与 `Co-authored-by` trailer。
- PR 合并后自动删除 source branch。
- 脚本通过 GitHub 返回的 `owner.type` 区分组织和个人仓库。组织仓库默认分支使用 squash merge queue；个人仓库不创建队列规则集。

对应字段：`allow_squash_merge=true`、`allow_merge_commit=false`、`allow_rebase_merge=false`、`allow_auto_merge=true`、`squash_merge_commit_title=PR_TITLE`、`squash_merge_commit_message=PR_BODY`、`delete_branch_on_merge=true`。

### 组织仓库的 merge queue

- 默认分支须已初始化。应用前检查项目 CI：必需的 GitHub Actions 检查须响应 `merge_group`，job 的条件也要允许队列运行；发布任务仅在真正更新默认分支后执行。脚本不自动修改项目 workflow。
- 脚本创建或更新名为 `DCjanus merge queue` 的独立规则集，只作用于默认分支；保留其中已有的其它规则、检查与 bypass actors，不改其它规则集。重复执行不重复创建。
- 队列使用 `SQUASH`、`ALLGREEN`，一次构建、合并一个 PR；等待 CI 默认 90 分钟。通过 `--help` 查看队列超时和可重复的 `--required-check` 参数；必需检查名称须来自项目实际 CI，不从历史运行自动推断。
- 省略 `--required-check` 时保留已有检查，不会自动把队列变成 CI 门禁。首次配置时按项目实际需要指定检查；已有其它规则集提供队列时保留它，存在合并方法冲突或要求追加检查时明确报错，交由调用方定位原规则处理。
- 写入后回读规则集，并检查它确实对默认分支生效。权限、套餐或组织策略不支持时返回失败，不静默忽略；仓库级合并设置可能已写入，应核对实际状态。

功能及 CI 约束见 [GitHub merge queue 文档](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)。

## GitLab 策略

- 使用 Merge commit with semi-linear history（`merge_method=rebase_merge`）并强制 squash（`squash_option=always`）。目标分支的 first-parent 历史保持线性，每次 MR 合并保留 squash commit 和记录合并边界的 merge commit。
- squash commit 模板为 `%{title}\n\n%{description}\n\n%{co_authored_by}`，采用 MR 标题、正文及 GitLab 可生成的协作者 trailer，不重复记录 MR reference。
- merge commit 使用平台默认模板承载 MR 链接。脚本校验 `merge_commit_template` 为空，但不会覆盖已有自定义模板；存在自定义模板时会在写入其他设置后校验失败，需要单独处理。
- 默认删除 source branch（`remove_source_branch_after_merge=true`）；通过 API 创建 MR 时仍显式传 `remove_source_branch`。

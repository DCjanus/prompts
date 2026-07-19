---
name: repository-workflow
description: 处理从本地 Git 变更到 GitHub/GitLab 协作发布的完整工作流；适用于创建或更新分支、语义化 commit message、commit、push、Issue/PR/MR 文案、inline review reply、Breaking Change 与提交范围核对。纯只读的平台查询不使用本 skill。
---

# Repository Workflow

统一管理仓库变更的准备、记录和发布。GitHub/GitLab 的资源读取与平台写入仍交给 [SKILL.md](../github-cli/SKILL.md) / [SKILL.md](../gitlab-cli/SKILL.md)。

## 路由

- 涉及 commit 或 commit message 时，先完整读取 [commit-messages.md](references/commit-messages.md)。
- 涉及 Issue、PR/MR 标题或正文、Breaking Change 展示、inline review reply 时，先完整读取 [change-requests.md](references/change-requests.md)。PR/MR 标题还要读取 [commit-messages.md](references/commit-messages.md)。
- 只涉及 branch、push、merge 或历史管理时，使用本文件即可。
- 只读查看、搜索、状态检查或 CI 日志不使用本 skill，直接使用对应平台或 CI skill。

## 授权边界

- 修改或实现代码只授权工作区文件变更，不自动授权 commit、push 或平台写入。
- commit、push、创建或更新 Issue/PR/MR、发送 inline reply、resolve thread 都需要用户明确授权。
- 用户一次明确要求连续动作（如“提交并推送”）时，可连续完成，无需逐步重复确认。
- 草拟文案不等于授权发送。
- PR/MR 默认创建为正式状态；只有用户明确要求时才创建 draft。

## 工作区与提交范围

1. 先运行 `git status -sb`，确认当前分支、上游关系和 dirty worktree。
2. 区分当前任务改动与用户已有改动，只处理当前任务负责的路径。
3. 不要为了当前任务 stash、restore、reset 或清理无关改动。
4. 如果同一文件混有无法安全分离的改动，停止提交并说明情况。
5. 新文件可以先精确 stage；已有文件优先通过 `git commit --only -- <paths>` 限定提交范围。

## 创建 commit

1. 完整读取 [commit-messages.md](references/commit-messages.md)，并根据最终待提交内容生成 message。
2. 从本 skill 目录直接运行 helper，禁止通过 `python` 或 `uv run python` 间接调用：

```bash
./scripts/codex_git_commit.py
```

3. 只有 helper 成功返回包含非空 `agent_name` 与 `model_name` 的有效 JSON 时，才继续提交。失败、超时、输出无效或字段缺失时立即停止；禁止猜测、伪造、使用占位值或省略 `Assisted-by`。
4. 创建范围受控的提交：

```bash
git commit --only \
  -m "type(scope): concise summary" \
  --trailer "Assisted-by: <agent-name>:<model-name>" \
  -- <paths-owned-by-current-task>
```

5. 新文件需要 stage 时，只 stage 当前任务负责的新文件，再用同样的路径范围提交。
6. 提交后运行以下检查：

```bash
git show --name-status --oneline --no-renames HEAD
git show -s --format=%B HEAD | git interpret-trailers --parse
git status -sb
```

## 分支、推送与历史

- 日常切换分支使用 `git switch`，恢复工作区或暂存区使用 `git restore`。
- 新分支优先使用符合仓库约定的 Conventional Branch 名称。
- 涉及真实 index 或引用的 Git 写操作保持串行；遇到 `.git/index.lock` 时先检查活跃 Git 进程。
- 推送前再次确认分支、远端、上游关系和工作区状态。
- 更新已有 PR/MR 分支时，默认 merge target/base 到 source/head，并追加修正 commit。
- 默认不 amend、rebase、squash 或 force push。只有用户明确要求，或仓库明确要求线性历史时才改写历史；执行前先确认本地与远端目标。

## Issue、PR/MR 与 review reply

1. 完整读取 [change-requests.md](references/change-requests.md)；PR/MR 标题同时读取 [commit-messages.md](references/commit-messages.md)。
2. 根据平台同时使用 `github-cli` 或 `gitlab-cli` 完成模板检查、资源读取和实际写入。
3. 创建或更新前核对平台当前内容与最终本地状态；独立 Issue 按 reference 中的例外处理。
4. 多行正文先写入临时 Markdown 文件，再通过平台命令的 file 参数提交，不在 shell 中拼接。
5. 写入后回读标题、正文、状态和必要的元数据，确认平台结果与预期一致。

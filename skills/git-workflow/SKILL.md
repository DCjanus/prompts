---
name: git-workflow
description: 处理 git 提交、推送、分支命名与提交信息规范；当任务涉及 commit、push、起分支或整理 commit message 时使用。
---

## 默认流程

1. 确认当前状态，并确定本次任务负责的路径：

```bash
git status -sb
```

2. 获取 `Assisted-by` 信息：

`<skill_dir>` 是当前 `SKILL.md` 所在文件夹。脚本必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`。

```bash
(cd <skill_dir> && ./scripts/codex_git_commit.py)
```

错误示例：

```bash
uv run python skills/git-workflow/scripts/codex_git_commit.py
python skills/git-workflow/scripts/codex_git_commit.py
```

3. 创建范围受控的提交：

```bash
git commit --only \
  -m "type(scope): concise summary" \
  -m "Optional body explaining the change." \
  --trailer "Co-authored-by: Name <name@example.com>" \
  --trailer "Assisted-by: <agent-name>:<model-name>" \
  -- <paths-owned-by-current-task>
```

4. 核对提交范围：

```bash
git show --name-status --oneline --no-renames HEAD
```

5. 如需推送，先确认状态，再按仓库和用户要求推送：

```bash
git status -sb
git push <remote> <branch>
```

## 路径范围

- `<paths-owned-by-current-task>` 只包含当前任务负责的文件或目录；多个 Agent 共用同一个 worktree 时也按这个规则执行。
- 目标可以是文件，也可以是当前任务完整负责的目录；大量生成文件优先传目录，例如 `gen/`。
- 如果目录里混有无关改动，改用更精确的文件或子目录路径。
- 如果同一个文件里混有用户或其他 Agent 的改动，先停止并说明情况，不要强行提交。
- 不要为了提交当前任务去清理、reset、restore 或 stash 无关改动。
- 默认不需要提前 `git add`；`git commit --only -- <paths>` 会直接提交这些路径的当前工作区内容。

## 提交信息

- 提交信息使用简洁、精确的英文。
- 推荐格式：`type(scope): short summary`，遵循 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)。
- 常见 `type`：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`
- `summary` 聚焦结果；若无合适 scope，可省略。
- 若提交包含 breaking change，标题和 footer 必须同时标识：

```bash
git commit --only \
  -m "type(scope)!: concise summary" \
  -m "BREAKING CHANGE: describe the impact and required migration." \
  --trailer "Assisted-by: <agent-name>:<model-name>" \
  -- <paths-owned-by-current-task>
```

- `BREAKING CHANGE:` footer 应说明影响范围和迁移方式；不要只重复标题。
- 关键字必须写作 `BREAKING CHANGE:`，不要写成 `BREAK CHANGE:`。
- commit 标题和正文使用 `-m`；结构化 trailer 使用 `--trailer`。
- 若提交内容存在 AI 编码助手的实质性参与，用 `--trailer "Assisted-by: <agent-name>:<model-name>"` 追加 trailer。
- 添加 `Co-authored-by`、`Reviewed-by`、`Assisted-by` 等多个 trailer 时，重复使用 `--trailer "Key: Value"`；不要手工用多个 `-m` 拼 trailer block。
- 提交后可用 `git show -s --format=%B HEAD | git interpret-trailers --parse` 验证 trailer 解析结果。
- 用 shell 执行 `git commit -m ...` 时，不要在提交标题或正文里直接放未转义的反引号 `` ` ``。

## 分支和推送

- 如果仓库或用户有额外限制，例如受保护分支、发布流程、禁止自动推送，先遵循这些限制。
- 日常切换分支优先使用 `git switch`，恢复工作区或暂存区优先使用 `git restore`，尽量避免 `git checkout`。
- 创建分支时尽量遵循 [Conventional Branch](https://conventional-branch.github.io/)。
- 涉及真实 index / 引用的 Git 写操作时默认串行执行，不并行调用多个 `git commit`、`git push` 或其他写操作。
- 如果遇到 `.git/index.lock`，先判断是否有其他活跃 Git 进程。
- 推送前，使用 `git status -sb` 确认本次提交、分支和工作区状态符合预期。

## 更新 MR/PR 分支

- 需要解决 MR/PR 与 target branch 的冲突或落后状态时，默认优先 merge target branch 到 source branch，而不是 rebase。
- 仅当用户明确要求 rebase，或仓库/平台有额外约束要求保持线性历史时，才改用 rebase。

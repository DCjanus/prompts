---
name: git-commit
description: 处理 git 提交/推送/分支命名与提交信息规范；当任务涉及 commit、push、起分支或整理 commit message 时使用。
---

## 核心原则

- 默认只提交当前任务负责的路径。
- 创建提交默认使用 `git commit --only -- <paths-owned-by-current-task>`，显式指定本次提交范围，不依赖暂存区。
- 不要为了提交当前任务去清理、reset、restore 或 stash 无关改动。
- 如果同一个文件里混有用户或其他 Agent 的改动，先停止并说明情况，不要强行提交。
- 如果仓库或用户有额外限制，例如受保护分支、发布流程、禁止自动推送，先遵循这些限制。

## 标准流程

1. 确认当前状态，并确定本次任务负责的路径。

```bash
git status -sb
```

2. 获取 `Assisted-by` 信息。

`<skill_dir>` 是当前 `SKILL.md` 文件所在文件夹。脚本必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`。

```bash
(cd <skill_dir> && ./scripts/codex_git_commit.py)
```

错误示例：

```bash
uv run python skills/git-commit/scripts/codex_git_commit.py
python skills/git-commit/scripts/codex_git_commit.py
```

3. 创建提交。

```bash
git commit --only \
  -m "type(scope): concise summary" \
  -m "Assisted-by: <agent-name>:<model-name>" \
  -- <paths-owned-by-current-task>
```

4. 核对提交范围。

```bash
git show --name-status --oneline --no-renames HEAD
```

## 路径选择

- `<paths-owned-by-current-task>` 必须只包含当前任务负责的文件或目录；多个 Agent 共用同一个 worktree 时也按这个规则执行。
- `<paths-owned-by-current-task>` 可以是文件，也可以是当前任务完整负责的目录。
- 大量生成文件优先传目录，例如 `gen/`，不要把几千个文件展开成命令参数。
- 如果目录里混有无关改动，不要传整个目录，改用更精确的文件或子目录路径。
- 默认不需要提前 `git add`；`git commit --only -- <paths>` 会直接提交这些路径的当前工作区内容。

## 提交信息

- 提交信息使用简洁、精确的英文。
- 推荐格式：`type(scope): short summary`，遵循 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)。
- 常见 `type`：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`
- `summary` 保持简短，聚焦结果；若无合适 scope，可省略。
- 若提交内容存在 AI 编码助手的实质性参与，追加 `Assisted-by: <agent-name>:<model-name>` trailer。
- 用 shell 执行 `git commit -m ...` 时，不要在提交标题或正文里直接放未转义的反引号 `` ` ``。

## 分支、推送和 PR

- 日常切换分支优先使用 `git switch`，恢复工作区或暂存区优先使用 `git restore`，尽量避免 `git checkout`。
- 创建分支时尽量遵循 [Conventional Branch](https://conventional-branch.github.io/)；Codex 创建分支默认使用 `codex/` 前缀。
- 涉及真实 index / 引用的 Git 写操作时默认串行执行，不并行调用多个 `git commit`、`git push` 或其他写操作。
- 如果遇到 `.git/index.lock`，先判断是否有其他活跃 Git 进程。
- 推送或创建 PR 前，使用 `git status -sb` 确认本次提交、分支和工作区状态符合预期。

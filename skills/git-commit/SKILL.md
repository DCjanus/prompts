---
name: git-commit
description: 处理 git 提交/推送/分支命名与提交信息规范；当任务涉及 commit、push、起分支或整理 commit message 时使用。
---

## 使用约定

说明：以下调用方式均以当前 `SKILL.md` 文件所在文件夹为 workdir。

脚本调用方式（必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`）：

```bash
cd skills/git-commit && ./scripts/codex_git_commit.py
```

错误示例：

```bash
uv run python skills/git-commit/scripts/codex_git_commit.py
python skills/git-commit/scripts/codex_git_commit.py
```

### 先确认范围与限制

- 确认当前仓库或用户没有额外限制，例如受保护分支、发布流程、禁止自动推送。
- 不确定应提交哪些改动、推送到哪个远端或分支、是否会影响共享分支时，先澄清。
- 提交前确认工作区中哪些改动属于当前任务，不要混入无关改动。

### 提交信息与分支命名

- 提交信息使用简洁、精确的英文。
- 推荐格式：`type(scope): short summary`，遵循 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)。
- 常见 `type`：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`
- `summary` 保持简短，聚焦结果；若无合适 scope，可省略。
- 创建分支时尽量遵循 [Conventional Branch](https://conventional-branch.github.io/)。

### Assisted-by

- 若提交内容存在 AI 编码助手的实质性参与，追加 `Assisted-by:` trailer。
- 在 Codex 场景下，先直接执行本 skill 下的 [codex_git_commit.py](scripts/codex_git_commit.py)，再用脚本返回的 agent 名和模型名补充 `Assisted-by:`。
- 推荐格式：`Assisted-by: <agent-name>:<model-name>`
- 方括号只是占位说明，不是字面量。

### Git 执行方式

- 日常切换分支优先使用 `git switch`，恢复工作区或暂存区优先使用 `git restore`，尽量避免 `git checkout`。
- 涉及 Git 写操作时默认串行执行，不并行调用多个 `git add`、`git commit`、`git push` 或其他会写入 index / 引用的命令。
- 如需连续执行 `git add`、`git commit`、`git push`，按顺序逐条执行，前一步成功后再执行下一步。
- 如果遇到 `.git/index.lock`，先判断是否有其他活跃 Git 进程。
- 用 shell 执行 `git commit -m ...` 时，不要在提交标题或正文里直接放未转义的反引号 `` ` ``。

## 示例

- 创建提交：

```bash
git status -sb
git add <paths>
(cd <skill_dir> && ./scripts/codex_git_commit.py)
git commit -m "fix(scope): concise summary" -m "Assisted-by: <agent-name>:<model-name>"
```

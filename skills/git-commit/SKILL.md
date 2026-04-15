---
name: git-commit
description: 处理 git 提交/推送/分支命名与提交信息规范；当任务涉及 commit、push、起分支或整理 commit message 时使用。
---

用于处理 git 提交相关操作与约定，重点是提交信息、分支命名、变更筛选和常用非交互命令。

## 使用约定

### 先确认范围与限制

- 先确认当前仓库或用户没有额外限制，例如受保护分支策略、发布流程要求或显式禁止自动推送。
- 若操作目标或影响范围不清楚，例如不确定应提交哪些改动、推送到哪个远端或分支、是否会影响共享分支，先澄清再执行。
- 提交前先确认工作区中哪些改动属于当前任务，避免把无关改动混入同一个提交。

### 提交信息与分支命名

- 提交信息使用简洁、精确、描述性强的英文。
- 推荐格式：`type(scope): short summary`，遵循 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)。
- 常见 `type`：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`
- `summary` 保持简短，聚焦结果，不写空泛描述；若无合适 scope，可省略 scope，但优先保留。
- 创建分支时尽量遵循 [Conventional Branch](https://conventional-branch.github.io/)。

### Assisted-by

- 若提交内容存在 AI 编码助手的实质性参与，追加 `Assisted-by:` trailer。
- 在 Codex 场景下，先运行本 skill 下的 [codex_git_commit.py](scripts/codex_git_commit.py)，再用脚本返回的 agent 名和模型名补充 `Assisted-by:`；不要自己猜模型名。
- 推荐格式：`Assisted-by: <agent-name>:<model-name>`
- 方括号只是占位说明，不是字面量；基础开发工具（如 `git`、编译器、编辑器、常规测试命令）不应写入 trailer。

### Git 执行方式

- 日常切换分支优先使用 `git switch`，恢复工作区或暂存区优先使用 `git restore`，尽量避免 `git checkout`；`git checkout` 承载的语义过多，不如专用子命令清晰。
- 涉及 Git 写操作时默认串行执行，不并行调用多个 `git add`、`git commit`、`git push` 或其他会写入 index / 引用的命令。
- 如需连续执行 `git add`、`git commit`、`git push`，按顺序逐条执行，前一步成功后再执行下一步。
- 如果遇到 `.git/index.lock`，先判断是否有其他活跃 Git 进程；不要把并行执行当成默认方案。
- 用 shell 执行 `git commit -m ...` 时，提交标题或正文里不要直接放未转义的反引号 `` ` ``；需要内联代码时，优先改用单引号包裹整条命令并在内部使用双引号，或改用提交消息文件 / heredoc。

## 示例

以下示例中的 `(cd <skill_dir> && ./scripts/codex_git_commit.py)` 表示在子 shell 中切换到本 skill 目录执行脚本，不影响后续命令的当前目录。

- 创建提交：

```bash
git status -sb
git add <paths>
(cd <skill_dir> && ./scripts/codex_git_commit.py)
git commit -m "fix(scope): concise summary" -m "Assisted-by: <agent-name>:<model-name>"
```

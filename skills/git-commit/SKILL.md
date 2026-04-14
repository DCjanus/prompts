---
name: git-commit
description: 处理 git 提交/推送/分支命名与提交信息规范；当任务涉及 commit、push、起分支或整理 commit message 时使用。
---

用于处理 git 提交相关操作与约定，重点是提交信息、分支命名、变更筛选和常用非交互命令。

## Quick start

```bash
cd /path/to/repo
git status --short
git add <paths>
git commit -m "feat(scope): short summary"
```

涉及 Git 写操作时，默认按串行顺序执行单条命令，避免并行触发多个 `git add`、`git commit`、`git push`，以免因为 `.git/index.lock` 导致部分命令失败。

## 使用约定

- 执行前先确认当前仓库或用户没有额外限制，例如受保护分支策略、发布流程要求或显式禁止自动推送。
- 若操作目标或影响范围不清楚，例如不确定应提交哪些改动、推送到哪个远端/分支，或可能影响共享分支，先澄清再执行。
- 提交信息使用简洁、精确、描述性强的英文，遵循 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)；可行时尽量包含 scope。
- 创建分支时尽量遵循 [Conventional Branch](https://conventional-branch.github.io/)。
- 若提交内容存在 AI 编码助手的实质性参与，追加 `Assisted-by: AGENT_NAME:MODEL_VERSION [TOOL1] [TOOL2]` trailer；不要把 AI 助手写成 `Co-authored-by:`。
- `AGENT_NAME` 与 `MODEL_VERSION` 由当前实际使用的 agent 和模型自行决定，不要写死成某个固定产品名或版本号。
- `Co-authored-by:` 保留给真实的人类协作者；`Signed-off-by:` 只能由人类添加。
- 方括号只是占位说明，不是字面量；基础开发工具（如 `git`、编译器、编辑器、常规测试命令）不应写入 trailer。
- 日常切换/恢复操作优先使用 `git switch` 与 `git restore`，尽量避免 `git checkout`。
- 进行提交前，先确认工作区中哪些改动属于当前任务，避免把无关改动混入同一个提交。
- 涉及 Git 写操作时，默认串行执行，不并行调用多个 Git 命令；尤其不要并行触发多个会写入 index 或引用的命令。
- 如需连续执行 `git add`、`git commit`、`git push`，优先单次按顺序执行，前一步成功后再执行下一步；只有明确确认不存在锁竞争风险时才可例外。
- 如果遇到 `.git/index.lock`，先判断是否有其他活跃 Git 进程；不要把并行执行当成默认方案。
- 用 shell 执行 `git commit -m ...` 时，提交标题或正文里不要直接放未转义的反引号 `` ` ``；它会触发命令替换并污染提交内容。需要内联代码时，优先改用单引号包裹整条命令并在内部使用双引号，或改用提交消息文件 / heredoc。

## 常用场景

- 创建提交：

```bash
git status --short
git add <paths>
git commit -m "fix(scope): concise summary"
```

- 创建带 trailer 的提交：

```bash
git commit -m "feat(scope): concise summary" -m "Assisted-by: <agent-name>:<model-version>"
```

- 补充说明较多的提交：

```bash
git commit -m "refactor(scope): concise summary" -m "Explain the key intent or constraint." -m "Assisted-by: <agent-name>:<model-version>"
```

- 当提交正文需要包含反引号或多行内容时，优先使用消息文件或 `-F -`：

```bash
cat <<'EOF' | git commit -F -
feat(scope): concise summary

Explain the key intent with `inline code` safely.

Assisted-by: <agent-name>:<model-version>
EOF
```

- 新建并切换分支：

```bash
git switch -c feat/scope-short-summary
```

- 切换已有分支：

```bash
git switch <branch>
```

- 丢弃工作区单文件改动：

```bash
git restore <path>
```

- 取消暂存：

```bash
git restore --staged <path>
```

- 顺序执行 add / commit / push：

```bash
git add <paths>
git commit -m "feat(scope): concise summary" -m "Assisted-by: <agent-name>:<model-version>"
git push origin HEAD
```

## 提交信息约定

- 推荐格式：`type(scope): short summary`
- 常见 `type`：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`
- `summary` 保持简短，聚焦结果，不写空泛描述
- 若无合适 scope，可省略 scope，但优先保留

## 冷门参数怎么查

- `git commit --help`
- `git switch --help`
- `git restore --help`
- `git push --help`

## 资源

- [SKILL.md](SKILL.md)

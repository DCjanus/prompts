---
name: git-commit
description: 处理 git 提交/推送/分支命名与提交信息规范；当用户要求 commit、push、起分支或整理 commit message 时使用。
---

用于处理 git 提交相关操作与约定，重点是授权边界、提交信息、分支命名和常用非交互命令。

## Quick start

```bash
cd /path/to/repo
git status --short
git add <paths>
git commit -m "feat(scope): short summary"
```

## 使用约定

- 未收到用户当次明确 `commit` 指令时，不执行 `git commit`。
- 未收到用户当次明确 `push` 指令时，不执行 `git push`。
- 可以在确有需要时询问是否需要 `commit`；不得主动询问是否需要 `push`。
- 如存在授权歧义，先向用户确认，再执行相关 git 写操作。
- 提交信息使用简洁、精确、描述性强的英文，遵循 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)；可行时尽量包含 scope。
- 创建分支时尽量遵循 [Conventional Branch](https://conventional-branch.github.io/)。
- 提交时追加 `Co-authored-by: OpenAI Codex <codex@openai.com>` trailer。
- 日常切换/恢复操作优先使用 `git switch` 与 `git restore`，尽量避免 `git checkout`。
- 进行提交前，先确认工作区中哪些改动属于当前任务，避免把无关改动混入同一个提交。

## 常用场景

- 创建提交：

```bash
git status --short
git add <paths>
git commit -m "fix(scope): concise summary"
```

- 创建带 trailer 的提交：

```bash
git commit -m "feat(scope): concise summary" -m "Co-authored-by: OpenAI Codex <codex@openai.com>"
```

- 补充说明较多的提交：

```bash
git commit -m "refactor(scope): concise summary" -m "Explain the key intent or constraint." -m "Co-authored-by: OpenAI Codex <codex@openai.com>"
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

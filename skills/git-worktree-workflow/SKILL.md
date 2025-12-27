---
name: git-worktree-workflow
description: 面向多 agent 并行开发的 git worktree 全生命周期流程，包括创建、协作、切换与清理。用于需要在当前仓库中基于场景建立新 worktree/分支、管理多 worktree 并行开发、或执行收尾清理的任务。
---

# Git Worktree Workflow

## 触发与必要输入

- 必须用户显式声明要创建 worktree/分支，否则仅给出建议与候选命名。
- 必须用户声明场景（feature/bugfix/docs/chore/etc.），缺失则先询问。
- 收集 `tree_name`（目录名）与可选 `base_branch`。

## 默认策略

- 基准分支：默认使用当前分支 `git branch --show-current`，除非用户另行指定。
- worktree 路径：`~/.cache/worktrees/<repo>/<tree_name>`，其中 `<repo>` 为仓库根目录名。

## 分支命名

- 遵循 [Conventional Branch](https://conventional-branch.github.io/) 规范。
- 按场景选择类型：`feat`/`fix`/`docs`/`chore`/`refactor`/`test`/`build`/`ci`/`perf`/`revert`。
- 将 `tree_name` 或场景摘要转为 slug：小写、短横线分隔、避免空格。
- 形如 `<type>/<slug>`；仅在用户提供 scope 时使用 `<type>/<scope>/<slug>`。

## 生命周期流程

1. **创建**：校验目标路径与分支状态后创建 worktree/分支。
2. **并行协作**：强调每个 worktree 只操作自己的分支，避免跨目录混用。
3. **切换/查看**：使用 `git branch --show-current` 进行状态确认。
4. **清理**：确认分支合并或不再需要后，移除 worktree 并按需删除分支。
5. **输出路径**：创建完成后单独一行输出 worktree 的完整路径，便于终端快速跳转。

## 关键命令

1. 仓库根目录：`git rev-parse --show-toplevel`
2. 仓库名：`basename "$(git rev-parse --show-toplevel)"`
3. 创建 worktree：
   - 新分支：`git worktree add -b <branch> <path> <base_branch>`
   - 现有分支：`git worktree add <path> <branch>`
4. 移除 worktree：`git worktree remove <path>`
5. 删除分支：`git branch -d <branch>`（必要时用 `-D` 并先确认）

## 安全检查

- 目标路径已存在则停止并询问是否更换 `tree_name`。
- 新建分支已存在则询问复用或改名。
- 清理前确认分支是否已合并或可安全删除。

## 风险提示

- `~/.cache/worktrees` 仅存放额外检出目录；删除不会影响主仓库本体。
- 误清理会丢失 worktree 内未提交的改动与未推送的临时文件。
- 已提交到分支的内容仍保存在主仓库对象库中，不在 `~/.cache` 里。

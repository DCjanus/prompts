---
name: partial-git-commit
description: 禁用 git add -p 时，需要只提交部分改动或剔除调试/格式化生成代码的场景使用。
---

# 共识：非交互式部分提交

## 何时用
- 禁用 `git add -p`，但需只提交部分改动或剔除调试/自动生成/格式化噪声。

## 极简流程（依赖脚本完成筛选并提交）
1) 列表浏览：`./scripts/hunk_slice.py list --start 1 --count 5`（路径以本 SKILL.md 所在目录为基准；跨仓库调用请写成绝对/相对到此目录的路径）  
   - 预览最多展示每个 hunk 前 5 行，超出以 `...` 省略；可用 `--path` 限定路径，多次传入。
2) 反复翻页确认要保留的 hunk ID。
3) 一步提交：`./scripts/hunk_slice.py commit --keep src/foo.py:42 --keep src/bar.py:10 --message "fix: foo"`  
   - 可用 `--keep-temp` 在提交后保留生成的临时 patch 路径，便于排查。

## 过滤手法（可选，先粗筛再用脚本）
- 路径级：直接用脚本的 `--path` 多次传入。

## 辅助脚本
- 位置：相对于本文件的 `./scripts/hunk_slice.py`（uv shebang，依赖 `unidiff2` + Typer）；在任意仓库使用时，请按本文件所在目录的相对/绝对路径调用，不要假设当前仓库自带 `skills` 目录。
- 功能：分页缩略输出 hunk（含文件、起始行、增删计数），`commit` 子命令按 hunk ID 写出精简 patch 并直接提交，避免大 diff 全量加载。

## 红线 / 回滚
- 只用 `git apply --cached`，不改工作区。
- 禁用交互式筛选（`git add -p`、编辑器 patch）。
- 提交前以暂存区为准：`git diff --cached` 必看。
- 出现异常/冲突：`git reset` 清空暂存区后重来。

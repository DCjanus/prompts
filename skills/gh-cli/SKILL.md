---
name: gh-cli
description: 使用 GitHub CLI 查看 issue/PR 并按约定创建 PR 的流程指引。
---

# GitHub CLI Skill

## GitHub 链接快速查看
- 进入 Issue 前可先运行 `gh auth status` 或 `gh api user --jq '.login'`，确认当前身份以辨识讨论中提到的用户是否就是自己。
- Issue：`gh issue view <url|number> -c`（含评论）。
- PR diff：`gh pr diff <url|number> --color never`。

## 创建 PR
1. 确认 `git status` 干净，`git push` 到远端。
2. 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），保持简洁且描述核心目的。
3. 描述风格：英文要点式，首段写最关键目标，再补充次要更新，必要时用列表清晰呈现，避免冗长叙述；若上下文不足以明确目的，应主动向开发者确认后再撰写。
4. 用非交互式命令创建 PR，正文统一通过 `--body-file` 传入：
   ```bash
   gh pr new --title "feat(scope): short semantic summary" --body-file - <<'EOF'
   - Added X
   - Updated Y
   - Notes: Z
   EOF
   ```
   - 可追加 `--base <branch>`、`--draft` 等参数。
   - 多行正文只能通过 `--body-file` 传入，避免在 `--body` 中写 `\n`。
5. `gh pr edit` 与 `gh pr new` 参数一致，需修改时复用。
6. PR 创建成功后，在终端单独输出 CLI 返回的完整 PR URL。

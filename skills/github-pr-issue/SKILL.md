---
name: github-pr-issue
description: 查看/更新 GitHub Issue、PR（含评论与 diff），并按团队规范非交互创建或修改 PR；涉及 GitHub Issue/PR 的操作时使用。
---

# GitHub CLI Skill（Issue/PR）

## GitHub 链接快速查看
- 进入 Issue 前可先运行 `gh api user --jq '.login'`，确认当前身份以辨识讨论中提到的用户是否就是自己。
- Issue：`gh issue view <url>`。
- PR 信息：`gh pr view <url>`，同样使用默认输出即可，必要时可附加 `--files` 等参数按需展开。
- PR diff：`gh pr diff <url> --color never`。
- PR Review / Review Threads / Issue Comments：
  - 一次性拉取 Review（评审）、Review Threads（代码行内讨论线程）与 Issue Comments（PR 评论）（JSON，推荐）：使用脚本 `./scripts/gh_pr_context.py`。
    - PR 链接：`./scripts/gh_pr_context.py fetch https://github.com/OWNER/REPO/pull/123`
    - 手动参数：`./scripts/gh_pr_context.py fetch --owner OWNER --repo REPO --number 123`

## 创建 Issue（非交互）
1. 标题与描述风格同 PR，内容保持简洁清晰。
2. 用 `--body-file` 传多行描述，避免交互式编辑：
   ```bash
   gh issue create --title "feat: short summary" --body-file - <<'EOF'
   # 按上面的格式填充正文
   EOF
   ```
3. Issue 创建成功后，在终端**单独一行**输出 CLI 返回的完整 Issue URL。

## 创建 PR
以下标题与描述规范为默认推荐格式；如与团队/仓库/平台等既有约束冲突，以既有约束为准。若有明确要求（如需中文），则优先遵循；未覆盖的部分再按本规范补齐。
1. 确认 `git status` 干净，`git push` 到远端。
2. 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），保持简洁且描述核心目的；即使标题要求中文，语义化前缀（如 `feat`、`fix`）仍需英文。
3. 描述风格：英文、短句和项目符号，优先让不看代码的读者也能理解动机与结果。重点是 what/why/impact 和被迫约束，避免流水账与开发过程细节。若上下文不足以明确目标或约束，应主动向开发者确认后再撰写。
4. 期望正文格式（精简但信息完整，按需删减无关块）：
   - `## Summary`：用 1-2 条短句说明“改了什么/影响是什么”与“为什么现在做”。
   - `## Key changes`：3-5 条要点列出主要变更。
   - `## Constraints / tradeoffs`：若存在约束、限制或非理想选择，简要说明。
   - `## Testing`：验证方式、命令或场景；未测试需注明原因。
   - `## Notes`（可选）：reviewers 关注点、发布注意事项或后续计划。
5. 特别强调：描述应聚焦 PR 合并前后系统的变化与影响，避免记录开发中的中间过程或修改步骤。
6. 用非交互式命令创建 PR，正文统一通过 `--body-file` 传入：
   ```bash
   gh pr new --title "feat(scope): short semantic summary" --body-file - <<'EOF'
   # 按上面的格式填充正文
   EOF
   ```
   - 可追加 `--base <branch>`、`--draft` 等参数。
   - 多行正文只能通过 `--body-file` 传入，避免在 `--body` 中写 `\n`。
7. `gh pr edit` 与 `gh pr new` 参数一致，需修改时复用。
8. PR 创建成功后，在终端**单独一行**输出 CLI 返回的完整 PR URL。

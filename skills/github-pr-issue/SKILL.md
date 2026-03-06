---
name: github-pr-issue
description: 查看/更新 GitHub Issue、PR（含评论与 diff），并按团队规范非交互创建或修改 PR；涉及 GitHub Issue/PR 的操作时使用。
---

# GitHub CLI Skill（Issue/PR）

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
以下标题与描述规范为默认推荐格式；如与团队/仓库/平台等既有约束冲突，以既有约束为准。若有明确要求（如需中文），则优先遵循。
1. 确认 `git status` 干净，`git push` 到远端。
2. 标题风格：英文、遵循语义化提交规范（如 `feat(scope): short summary`），简洁且描述核心目的；即使标题要求中文，语义化前缀仍需英文。
3. 描述风格：英文、短句和项目符号，优先让不看代码的读者快速理解动机、改动与验证方式。重点是 what/why/testing，避免流水账与过多实现细节。若上下文不足以明确目标或约束，应主动向开发者确认后再撰写。涉及专有名词、函数名、方法名、类名、API 名称或配置键时，使用 inline code（反引号）包裹以提升可读性与准确性。
4. 默认正文格式：
   - `## Why`：1-2 条短句说明为什么要做这次改动，聚焦问题背景或目标。
   - `## What`：1-3 条说明主要变更，聚焦功能或行为层面的变化，不罗列琐碎实现细节。
   - `## Testing`：说明验证方式、命令或场景；未测试需注明原因。
5. 可选正文块：仅在确有必要时再添加。
   - `## Risks`：兼容性影响、潜在风险、回滚注意事项。
   - `## Notes`：reviewers 需要特别关注的点，或后续计划。
6. 用非交互式命令创建 PR，正文统一通过 `--body-file` 传入：
   ```bash
   gh pr new --title "feat(scope): short semantic summary" --body-file - <<'EOF'
   ## Why
   - explain why this change is needed

   ## What
   - summarize the main user-visible or behavior-level changes

   ## Testing
   - list validation steps or explain why not tested
   EOF
   ```
   - 可追加 `--base <branch>`、`--draft` 等参数。
   - 多行正文只能通过 `--body-file` 传入，避免在 `--body` 中写 `\n`。
7. `gh pr edit` 与 `gh pr new` 参数一致，需修改时复用。
8. PR 创建成功后，在终端**单独一行**输出 CLI 返回的完整 PR URL。

## 更新 Issue/PR 标题或描述（前置要求）
在更新 Issue 或 PR 的标题/描述之前，必须先读取当前标题/正文（即将被修改的内容），再进行修改。

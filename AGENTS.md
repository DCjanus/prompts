## 基础约束
- 日常对话使用中文。
- 仅当用户主动指示提交时才可执行 `git commit`；不得主动请求授权，每次提交都需重新取得明确指示，不得沿用既往口头许可。
- Git Commit Message 使用简洁、精确、描述性强的英文，遵循[语义化提交规范](https://www.conventionalcommits.org/en/v1.0.0/)，且在可行时尽量包含 scope 信息

## 依赖管理
- 通用原则
  - 优先使用官方命令获取最新版依赖。
  - 默认使用最新可用版本，非必要不手动固定版本号。
  - 不手动修改项目描述文件或锁文件。
- 示例
  - Rust：`cargo add <crate>`
  - Python：`uv add <package>`
  - 前端（npm）：`npm install <package>`

## GitHub 链接快速查看
- URL 格式：`https://github.com/<owner>/<repo>/(issues|pull)/<id>`；收到后优先用 gh 而非直接访问。
- Issue：`gh issue view <url> -c`（含评论）。
- PR diff：`gh pr diff <url> --color never`。

## 创建 PR
- PR 标题：一律使用英文且遵循语义化提交规范，必要时包含 scope。
- PR 描述：使用英文保持简洁、专业、精准，像专业工程师撰写的说明；合理运用 Markdown（列表、代码块等）提升可读性，并根据需要引用关联 issue、相关代码片段、历史 PR 或提交，为 reviewer 提供充分上下文；描述聚焦整个 PR 的核心变更和目的，结合问题背景或待修复 BUG 说明我们解决了什么，而非罗列零散提交的细节，以降低 reviewer 的认知负担。
  - 正文开头先写最关键的目标或解决的问题，再补充次要更新；若当下信息不足以明确目标，先询问开发者而非自行臆测。
- 提交流程：
  - 确认当前分支及代码已推送到远程（`git status`、`git push`）。
    - 通过 `gh pr new` 创建 PR，显式提供标题与描述以避免交互：
      - 推荐使用标准输入一次性写入正文，例如：
        ```bash
        gh pr new --title "feat(scope): short semantic summary" --body-file - <<'EOF'
        - Added X
        - Updated Y
        - Notes: Z
        EOF
        ```
      - `gh pr edit` 与 `gh pr new` 的参数大体类似，可按需复用 `--base`、`--draft`、`--body-file` 等选项。
      - **注意**：正文默认走 `--body-file`（文件或标准输入），多行内容禁止在 `--body` 中写 `\n`，否则描述会展示字面字符串。
    - 创建 PR 成功后，在终端单独一行输出完整的 PR URL，方便后续引用。

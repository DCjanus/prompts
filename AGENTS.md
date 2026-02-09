## 基础约束
- 我是 DCjanus <DCjanus@dcjanus.com>。
- 日常对话使用中文。
- 需要查看 GitHub issue 或 PR 时，避免直接打开链接，应使用 GitHub CLI 命令获取详情。
- 向后兼容性策略（默认不做）
  - 默认：除非用户当次明确要求，否则不为历史接口/行为做向后兼容；允许为提升质量而进行必要的重构、重命名、删除与行为修正。
  - 目标：以代码质量优先（可维护、高效、易理解、简洁），避免为兼容历史包袱引入长期复杂度。
- 破坏性更新（breaking change）：如果改动会导致既有用法失效或行为变化，必须在回复中显式声明，并用以下两行警示包裹说明正文（必须成对出现且与正文分行）：
    - 在说明前单独一行添加 `==== !!!! BREAKING CHANGE BEFORE !!!! ====`
    - 在说明后单独一行添加 `==== !!!! BREAKING CHANGE AFTER !!!! ====`
- Markdown 链接偏好使用 `[描述](URL)` 形式，避免裸露 `<URL>`。
- 在 Markdown 中引用相对路径文件时，优先使用链接形式，链接文本仅保留文件名（路径放在链接目标里）；除非有歧义或明确要求，否则不要用 inline code 引用路径。

## Git 提交/推送（最高优先级，严禁自动执行）
- 未收到用户当次明确“提交/commit”指令时：不得执行 `git commit`、`git push`（即便工作区已准备好）。
- 严禁：主动请求提交/推送授权；沿用任何历史授权。
- 有疑义：必须先向用户确认，等待明确指令后再执行。
- Git Commit Message 使用简洁、精确、描述性强的英文，遵循[语义化提交规范](https://www.conventionalcommits.org/en/v1.0.0/)，且在可行时尽量包含 scope 信息。
- 创建分支时尽量遵循[Conventional Branch](https://conventional-branch.github.io/) 规范。
- 每次提交用 `git commit --trailer "Co-authored-by: OpenAI Codex <codex@openai.com>" -m "commit message"`。

## 依赖管理
- 通用原则
  - 优先使用官方命令获取最新版依赖。
  - 默认使用最新可用版本，非必要不手动固定版本号。
  - 不手动修改项目描述文件或锁文件。
  - 无外部依赖的临时 Python 执行优先用 `uv run python`，不要直接调用系统 `python`/`python3`。
- 示例
  - Rust：`cargo add <crate>`
  - Python：`uv add <package>`
  - 前端（npm）：`npm install <package>`
  - Go：`go get <module>`

## 文件编辑（优先使用 apply_patch）
- 小范围修改（如：单文件、少量行的增删改）：优先使用 `apply_patch` 进行编辑，以便在对话中生成清晰可读的 diff。
- `uv run python` 仅用于“临时执行/验证/检查”（例如：运行一次性脚本、格式化检查、快速计算），不要把它作为“编辑文件”的默认手段。
- 只有在批量/机械化改动（跨多文件大量替换、代码生成等）且 `apply_patch` 明显不合适时，才允许用脚本修改文件；并在回复中给出关键改动点（必要时附精简 diff 片段）。

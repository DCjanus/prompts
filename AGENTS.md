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
- 输出文件路径默认只写纯路径/文件名，不附加 `:行号` 或 `#L行号`。
- 仅当用户明确要求或任务必须精确定位（如代码评审/报错排查/同名文件消歧）时附加行号；新生成且需直接打开的文件一律不加行号。

## Git 提交/推送（最高优先级，严禁自动执行）
- 未收到用户当次明确“提交/commit”指令时：不得执行 `git commit`、`git push`（即便工作区已准备好）。
- 严禁：主动请求提交/推送授权；沿用任何历史授权。
- 有疑义：必须先向用户确认，等待明确指令后再执行。
- 进入仓库后先读项目规范（如 `CONTRIBUTING.md`、`README`、`.github/`）：默认提交加 `Co-authored-by: OpenAI Codex <codex@openai.com>` trailer；若项目规范禁止 AI/Co-authored-by（或要求互斥 trailer），按项目规范执行，并在回复中说明原因。
- Git Commit Message 使用简洁、精确、描述性强的英文，遵循[语义化提交规范](https://www.conventionalcommits.org/en/v1.0.0/)，且在可行时尽量包含 scope 信息。
- 创建分支时尽量遵循[Conventional Branch](https://conventional-branch.github.io/) 规范。

## 依赖管理
- 通用原则
  - 优先使用官方命令获取最新版依赖。
  - 默认使用最新可用版本，非必要不手动固定版本号。
  - 不手动修改项目描述文件或锁文件。
  - 一次性临时 Python 统一使用 `uv run (--with <外部依赖包>)* python ...`（`*` 表示 0~N 次），不要直接调用系统 `python`/`python3`。
- 示例
  - Rust：`cargo add <crate>`
  - Python：`uv add <package>`
  - 前端（npm）：`npm install <package>`
  - Go：`go get <module>`

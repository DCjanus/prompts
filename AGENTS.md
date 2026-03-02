# Codex 代理基础约束（AGENTS）

## 1. 适用范围与覆盖规则
本文件定义 Codex 的全局默认规则。

本文件中：第 2 章为硬规则；第 3 章为默认策略。冲突处理见 1.1。

### 1.1 规则优先级（冲突处理）
当多份规范同时存在且出现冲突时，按以下优先级（从高到低）执行：

1. 用户当次明确指令（针对当前任务的具体要求）
2. 项目级规范（同一层级：项目内 [AGENTS.md](AGENTS.md)、[CONTRIBUTING.md](CONTRIBUTING.md)、[README.md](README.md)、[.github](.github/) 内规范、团队/仓库政策等）
3. 全局默认规范（如全局 AGENTS.md）
4. 其它默认习惯或通用最佳实践

同一优先级内的冲突处理：
- 更具体（更贴近当前任务/目录/工具链/语言）的规则优先于更泛化的规则。
- 若仍无法判定，以更保守（更少副作用、风险更低、约束更严格）的一条为准，并在回复中说明取舍理由；必要时先向用户确认。

## 2. 硬规则

### 2.1 沟通与身份
- 日常对话使用中文。
- 身份信息：DCjanus <DCjanus@dcjanus.com>。

### 2.2 破坏性更新（Breaking Change）
- 如果改动会导致既有用法失效或行为变化，必须在回复中显著标识为 breaking change，并清晰说明影响范围（哪些用法/接口/行为变了）与迁移建议（用户该怎么改）。

### 2.3 Git 提交/推送（最高优先级）
- 未收到用户当次明确 `commit` 指令时，不得执行 `git commit`（即便工作区已准备好）。
- 未收到用户当次明确 `push` 指令时，不得执行 `git push`（即便工作区已准备好）。
- 如工作需要提交且用户未明确要求 `commit`，可以询问用户是否需要 `commit`；但不得沿用任何历史授权。
- 禁止主动询问是否需要 `push`（例如“要不要顺便推送”）；只有用户当次明确要求 `push` 才能执行 `git push`。
- 有疑义先向用户确认，等待明确指令后再执行（`push` 相关限制见上条）。
- 提交信息使用简洁、精确、描述性强的英文，遵循 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)；可行时尽量包含 scope。
- 创建分支时尽量遵循 [Conventional Branch](https://conventional-branch.github.io/)。

### 2.4 依赖管理
- 优先使用官方命令获取最新版依赖。
- 禁止手动修改项目描述文件或锁文件。
- 一次性临时 Python 统一使用 `uv run (--with <外部依赖包>)* python ...`（`*` 表示 0~N 次），不要直接调用系统 `python`/`python3`。

## 3. 默认策略

### 3.1 长期质量
- 优先选择能提升长期可维护、可理解、可扩展的方案；避免为了快速完成任务引入临时权衡/一次性 hack 或长期复杂度。
- 除非用户当次明确要求，否则不为历史接口/行为做兼容层；如确需引入额外复杂度，先说明成本与替代方案，再执行。

### 3.2 文档与 Markdown 风格
- Markdown 链接优先使用 `[描述](URL)` 形式，避免裸露 `<URL>`；在 Markdown 中引用相对路径文件时，优先使用链接形式（链接文本仅保留文件名、路径放在链接目标里）。除非有歧义或明确要求，否则不要用 inline code 引用路径。
- 输出文件路径只写纯路径/文件名，不附加 `:行号` 或 `#L行号`；仅当用户明确要求或任务必须精确定位（如代码评审/报错排查/同名文件消歧）时附加行号；新生成且需直接打开的文件一律不加行号。

### 3.3 Git 约定
- 提交追加 `Co-authored-by: OpenAI Codex <codex@openai.com>` trailer。

### 3.4 依赖版本策略
- 使用最新可用版本；非必要不手动固定版本号。

## 4. 操作流程

### 4.1 查看 GitHub issue / PR
- 涉及 GitHub issue/PR 的查看、更新或创建：优先使用 [SKILL.md](skills/github-pr-issue/SKILL.md)（用 `gh`/脚本获取描述、评论、diff、状态等；回复需包含足够上下文以支持后续决策/修改）。

### 4.2 添加/更新依赖
- 使用对应生态官方命令：
  - Rust：`cargo add <crate>`
  - Python：`uv add <package>`
  - 前端（npm）：`npm install <package>`
  - 前端（pnpm）：`pnpm add <package>`
  - 前端（yarn）：`yarn add <package>`
  - Go：`go get <module>`
- 依赖变更可复现（通过 lockfile/工具链保证）；不手工编辑描述文件或锁文件。

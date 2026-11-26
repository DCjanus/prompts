# Commit messages

先检查仓库已有提交规范；仓库规则优先于本文件默认值。下面的手写 commit 约定与平台生成的合并提交分开处理。

## Conventional Commits

- 手动创建的 commit message 使用简洁、精确的英文，并采用 `type(scope): summary` 形式；平台 squash merge 使用下文的独立约定。
- `type` 必须存在。仓库没有额外约定时，优先使用 `feat`、`fix`、`refactor`、`docs`、`test` 或 `chore`。
- 只有 scope 能准确表达影响边界时才添加；不要为了格式完整而猜测。
- summary 描述最终结果，不记录执行过程、工具操作或临时状态。
- 默认只写 subject。大部分边界清晰的简单提交不需要正文。

## 正文

- 先判断 reviewer 是否仍需要从 commit message 获得无法由 subject 和 diff 自然推导的重要信息；没有则完全省略 `body`。
- 仅在需要解释非显然的动机、决定性约束、重要行为影响、迁移要求或关键设计取舍时添加正文。
- 不要用正文复述 subject、罗列修改文件或实现步骤、汇报普通测试与检查、描述工具操作，或补充“暂未引入依赖”等对理解提交没有实际帮助的信息。
- 正文只保留理解和维护该提交所必需的内容，不套用固定的“背景 / 处理 / 验证”模板。

## 结构化 YAML

使用 `scripts/commit_from_yaml.py` 创建 commit，不直接通过 shell 的 `-m` 参数拼接正文。最小配置：

```yaml
subject: "fix(auth): handle missing email claims"
paths:
  - src/main/java/example/AuthService.java
```

确实需要解释关键约束时才添加 `body`：

```yaml
subject: "chore(toolchain): configure JDK 17 with mise"
body: |
  生产构建环境固定使用 JDK 17；仓库级配置用于避免本地与 CI 选择不同工具链。
trailers:
  - key: Reviewed-by
    value: DCjanus <DCjanus@dcjanus.com>
paths:
  - .mise.toml
```

- `subject` 和 `paths` 必填，标题须符合 Conventional Commits。
- `body` 和 `trailers` 可选；不满足上述正文条件时不要写 `body`。确需正文时，它是自由多行字符串，内部 Markdown 与换行完全由调用方控制。
- `paths` 列出本次提交的仓库相对路径。可以填文件、目录或 Git pathspec。使用通配符时加引号，例如 `':(glob)src/**/*.py'` 匹配 `src` 下各层级的 Python 文件。
- `empty_commit` 默认为 `false`，此时 `paths` 至少填一项。创建空提交时填写 `paths: []` 和 `empty_commit: true`，已有暂存改动会保留。
- `Assisted-by` 由脚本根据顶层 `assisted_by` 覆盖项生成，禁止放入 `trailers`。
- 所有字符串都禁止包含字面量 `\\n`；多行正文使用 YAML 的 `|` block scalar 表达。

## Breaking change

最终净变化确实会导致既有用法、接口或行为失效时，同时在标题和 footer 中显式标记：

```text
type(scope)!: concise summary

BREAKING CHANGE: Describe the affected usage and how to migrate.
```

对应 YAML：

```yaml
subject: "feat(api)!: replace authorization contract"
body: |
  BREAKING CHANGE: Requests from older clients will fail.
  Upgrade to the v2 API and send the email field.
paths:
  - src/main/java/example/AuthService.java
```

- footer 必须同时说明影响范围和迁移方式，不能只写“存在 breaking change”。
- 在 `body` 末尾直接撰写脚注。
- 不要根据中间实现或旧提交机械继承 breaking 标记，以最终净变化为准。

## Trailers

- 通过 YAML 的 `trailers` 添加 `Co-authored-by`、`Reviewed-by` 等 trailer。每项填写 `key` 和非空的单行 `value`。键名使用字母、数字和连字符。
- `Assisted-by` 由提交脚本自动探测，或通过顶层 `assisted_by` 覆盖项控制：`agent` 指定 Agent 前缀，`model` 指定模型并跳过探测，`assisted_by: false` 明确省略 trailer。
- `BREAKING CHANGE` 写在 `body` 末尾。

## PR/MR 标题

- PR/MR 标题默认采用 `type(scope): summary` 形式；语言遵循仓库和用户对 reviewer-facing 工件的要求，不因 squash merge 而强制改为英文。
- 根据相对 base/target 的最终净变化选择 type、scope 和 summary，不要机械复制某个中间 commit 标题。
- Issue 标题不使用这项要求。

## 平台合并提交

- 在没有明确强制提交格式的仓库中，squash merge 默认采用平台根据仓库设置生成的标题与正文，不将手写 commit 的英文 Conventional Commits 约束套用于合并提交。仓库明确强制要求或用户当次指定时，才覆盖默认消息。
- 合并前按最终净变化更新 PR/MR 标题和描述，让平台生成的提交承载最终结果。
- GitHub 合并时不传覆盖标题或正文的参数（例如 `gh pr merge` 的 `--subject`、`--body`、`--body-file`），不自行拼接提交清单或 trailer；采用仓库的默认 squash message 设置。
- 本约定只控制已授权合并时的消息处理，不授予合并权限，也不修改仓库的合并方式或消息模板设置。

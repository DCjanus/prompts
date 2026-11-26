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

使用 `scripts/commit_from_yaml.py` 创建 commit。每次都要填写 Conventional Commits 标题 `subject` 和提交范围 `paths`。

```yaml
subject: "fix(auth): handle missing email claims"
paths: [src/auth.py]
```

普通提交只包含 `paths` 匹配的文件，包括未跟踪且未被忽略的文件。其他已暂存的改动会保留。使用仓库相对路径、目录或 Git pathspec，含通配符或 magic 的表达式用引号括起。例如，`':(glob)src/**/*.py'` 匹配 `src` 各层目录的 Python 文件。

需要创建空提交时，显式填写 `empty_commit: true` 和空列表。已有暂存内容会保留。

```yaml
subject: "chore(ci): retrigger checks"
paths: []
empty_commit: true
```

## Breaking change

变更会使既有用法失效时，在标题中用 `!` 标记，并在 `body` 末尾写 `BREAKING CHANGE:`，说明影响和迁移方式。多行正文使用 YAML 的 `|` 保留换行；字符串中不能使用字面量 `\n`。

```yaml
subject: "feat(api)!: require an email claim"
paths: [src/auth.py]
body: |
  BREAKING CHANGE: Tokens without an email claim are rejected.
  Configure your identity provider to include the user's email in each token.
```

## Trailers

- 通过可选的 `trailers` 列表添加普通 trailer，例如 `- {key: Reviewed-by, value: "DCjanus <DCjanus@dcjanus.com>"}`。key 以字母开头，可包含字母、数字和连字符。value 必须是非空单行字符串。
- `Assisted-by` 默认根据当前会话生成。通过顶层 `assisted_by.agent` 或 `assisted_by.model` 覆盖对应值，或设 `assisted_by: false` 省略此项。

## PR/MR 标题

- PR/MR 标题默认采用 `type(scope): summary` 形式；语言遵循仓库和用户对 reviewer-facing 工件的要求，不因 squash merge 而强制改为英文。
- 根据相对 base/target 的最终净变化选择 type、scope 和 summary，不要机械复制某个中间 commit 标题。
- Issue 标题不使用这项要求。

## 平台合并提交

- 在没有明确强制提交格式的仓库中，squash merge 默认采用平台根据仓库设置生成的标题与正文，不将手写 commit 的英文 Conventional Commits 约束套用于合并提交。仓库明确强制要求或用户当次指定时，才覆盖默认消息。
- 合并前按最终净变化更新 PR/MR 标题和描述，让平台生成的提交承载最终结果。
- GitHub 合并时不传覆盖标题或正文的参数（例如 `gh pr merge` 的 `--subject`、`--body`、`--body-file`），不自行拼接提交清单或 trailer；采用仓库的默认 squash message 设置。
- 本约定只控制已授权合并时的消息处理，不授予合并权限，也不修改仓库的合并方式或消息模板设置。

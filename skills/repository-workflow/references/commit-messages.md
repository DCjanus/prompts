# Commit messages

先检查仓库已有提交规范；仓库规则优先于本文件默认值。

## Conventional Commits

- commit message 使用简洁、精确的英文，并采用 `type(scope): summary` 形式。
- `type` 必须存在。仓库没有额外约定时，优先使用 `feat`、`fix`、`refactor`、`docs`、`test` 或 `chore`。
- 只有 scope 能准确表达影响边界时才添加；不要为了格式完整而猜测。
- summary 描述最终结果，不记录执行过程、工具操作或临时状态。
- 只有标题不足以解释动机、约束或影响时才添加正文。

## Breaking change

最终改动确实会破坏既有用法时，同时在标题和 footer 标识：

```text
type(scope)!: concise summary

BREAKING CHANGE: describe the affected usage and required migration.
```

不要根据中间实现或旧提交机械继承 breaking 标记。

## Trailers

- 使用 `git commit --trailer "Key: Value"` 添加 `Assisted-by`、`Co-authored-by`、`Reviewed-by` 等结构化 trailer。
- 不要用多个 `-m` 手工拼接 trailer block。
- shell 命令中的提交标题或正文不要包含未安全处理的反引号。

## PR/MR 标题

- PR/MR 标题默认采用同样的 `type(scope): summary` 形式，便于 squash merge 后直接成为合格 commit message。
- 根据相对 base/target 的最终净变化选择 type、scope 和 summary，不要机械复制某个中间 commit 标题。
- Issue 标题不使用这项要求。

# Commit messages

先检查仓库已有提交规范；仓库规则优先于本文件默认值。

## Conventional Commits

- commit message 使用简洁、精确的英文，并采用 `type(scope): summary` 形式。
- `type` 必须存在。仓库没有额外约定时，优先使用 `feat`、`fix`、`refactor`、`docs`、`test` 或 `chore`。
- 只有 scope 能准确表达影响边界时才添加；不要为了格式完整而猜测。
- summary 描述最终结果，不记录执行过程、工具操作或临时状态。
- 只有标题不足以解释动机、约束或影响时才添加正文。

## Breaking change

最终改动确实会破坏既有用法时，默认在标题的冒号前添加 `!`：

```text
type(scope)!: concise summary
```

- 标题放不下的影响与迁移方式写入普通 body，不必重复添加 `BREAKING CHANGE` footer。
- Conventional Commits 允许用 `BREAKING CHANGE: description` footer 代替标题中的 `!`。只有项目工具明确要求该形式时才使用，并通过独立的 `-m "BREAKING CHANGE: ..."` message paragraph 写入。
- 禁止使用 `--trailer "BREAKING CHANGE: ..."`。Git 不会把带空格的 `BREAKING CHANGE` 当作普通 trailer key，可能生成尾部多余冒号并破坏后续 trailer 的解析。
- 不要根据中间实现或旧提交机械继承 breaking 标记。

## Trailers

- 使用 `git commit --trailer "Key: Value"` 添加 `Assisted-by`、`Co-authored-by`、`Reviewed-by` 等结构化 trailer。
- `--trailer` 只用于能被 `git interpret-trailers --parse` 正确识别的普通 key；Conventional Commits 的 `BREAKING CHANGE` 是特殊 footer，不属于这里的普通 trailer。
- 不要用多个 `-m` 手工拼接 trailer block。
- shell 命令中的提交标题或正文不要包含未安全处理的反引号。

## PR/MR 标题

- PR/MR 标题默认采用同样的 `type(scope): summary` 形式，便于 squash merge 后直接成为合格 commit message。
- 根据相对 base/target 的最终净变化选择 type、scope 和 summary，不要机械复制某个中间 commit 标题。
- Issue 标题不使用这项要求。

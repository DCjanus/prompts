# Commit messages

先检查仓库已有提交规范；仓库规则优先于本文件默认值。

## Conventional Commits

- commit message 使用简洁、精确的英文，并采用 `type(scope): summary` 形式。
- `type` 必须存在。仓库没有额外约定时，优先使用 `feat`、`fix`、`refactor`、`docs`、`test` 或 `chore`。
- 只有 scope 能准确表达影响边界时才添加；不要为了格式完整而猜测。
- summary 描述最终结果，不记录执行过程、工具操作或临时状态。
- 只有标题不足以解释动机、约束或影响时才添加正文。

## 结构化 YAML

使用 `scripts/commit_from_yaml.py` 创建 commit，不直接通过 shell 的 `-m` 参数拼接正文。最小配置：

```yaml
subject: "fix(auth): handle missing email claims"
paths:
  - src/main/java/example/AuthService.java
```

带中文正文的完整配置：

```yaml
subject: "chore(toolchain): configure JDK 17 with mise"
body:
  - heading: 背景
    paragraphs:
      - 项目以 Java 17 为目标。
  - heading: 处理
    bullets:
      - 新增仓库级 mise 配置。
      - 允许团队成员复用相同工具链。
  - heading: 验证
    bullets:
      - Maven 测试通过。
trailers:
  - key: Reviewed-by
    value: DCjanus <DCjanus@dcjanus.com>
paths:
  - .mise.toml
```

- `subject` 必填，必须符合 Conventional Commits。
- `body`、`trailers`、`paths` 可选；正文段支持 `paragraphs` 和 `bullets`，至少填写一种。
- `paths` 必须是仓库相对路径；非空时脚本使用 `git commit --only`，为空时提交当前 index。
- `Assisted-by` 由脚本生成，禁止放入 `trailers`。
- 所有字符串都禁止包含字面量 `\\n`；用 YAML 列表表达段落和项目符号。

## Breaking change

最终净变化确实会导致既有用法、接口或行为失效时，同时在标题和 footer 中显式标记：

```text
type(scope)!: concise summary

BREAKING CHANGE: Describe the affected usage and how to migrate.
```

对应 YAML：

```yaml
subject: "feat(api)!: replace authorization contract"
breaking_change:
  impact: 旧客户端的授权请求会失效。
  migration: 升级到 v2 接口并发送 email 字段。
```

- footer 必须同时说明影响范围和迁移方式，不能只写“存在 breaking change”。
- 通过 YAML 的 `breaking_change.impact` 与 `breaking_change.migration` 生成 footer；禁止将它放入 `trailers`。
- 不要根据中间实现或旧提交机械继承 breaking 标记，以最终净变化为准。

## Trailers

- 通过 YAML 的 `trailers` 添加 `Co-authored-by`、`Reviewed-by` 等结构化 trailer。
- `Assisted-by` 由提交脚本自动探测、通过 `--model` 显式生成，或通过 `--skip-assisted-by` 明确省略。
- `trailers` 只用于能被 `git interpret-trailers --parse` 正确识别的普通 key；不能包含 `Assisted-by` 或 `BREAKING CHANGE`。
- 不要用多个 `-m` 或 shell 转义手工拼接正文和 trailer block。
- shell 命令中的提交标题或正文不要包含未安全处理的反引号。

## PR/MR 标题

- PR/MR 标题默认采用同样的 `type(scope): summary` 形式，便于 squash merge 后直接成为合格 commit message。
- 根据相对 base/target 的最终净变化选择 type、scope 和 summary，不要机械复制某个中间 commit 标题。
- Issue 标题不使用这项要求。

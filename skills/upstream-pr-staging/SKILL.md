---
name: upstream-pr-staging
description: 在向 GitHub 上游提交 PR 前，先用用户 fork 中的中文预审 PR 审查 AI 辅助产出的代码、提交、PR 文案和 CI 证据，并通过独立 comment 收敛内部记录；适用于 fork 预审、低干扰验证、内部 review/CI、red/green 证据和正式上游 PR 重放。
---

# Upstream PR Staging

## 目的

AI 可以生成代码、测试和 PR 文案，但贡献者仍须对最终提交的正确性、风险和表述负责。不要把未经本人审查的 AI 输出直接交给上游 maintainer 筛选和纠错。

默认先在用户 fork 中创建预审 PR。它提供接近真实上游 PR 的代码审查、文案审查和 GitHub Actions 环境，同时不提前打扰上游。预审通过后，再整理或重放为正式上游 PR。

这套流程用于履行贡献者的审查责任，不用于规避上游对 AI 辅助贡献的政策。

## 信息分层

fork 预审 PR 使用两个互不混杂的区域：

1. **PR 标题和正文**：默认中文，但采用正式上游 PR 的模板、叙述视角和信息密度。只写上游 reviewer 需要的动机、净变化、风险和高信噪比证据。
2. **内部记录 comment**：默认中文，记录实验过程、fork issue、red/green 明细、临时 workflow、内部决策、未决事项和正式提交前清理项。

内部记录 comment 首行固定为：

```html
<!-- upstream-pr-staging:internal-notes -->
```

后续先按 marker 查找并编辑这一条 comment；不要为每次进展新增 comment。正式提交上游时不迁移它，只转写已经证实且对 reviewer 有价值的结论。

## 核心规则

- **低干扰**：预审阶段不触发上游 issue、PR 或 discussion 的 backlink、timeline mention 和通知，也不使用 `fixes`、`closes`、`resolves`。
- **链接**：预审阶段引用上游资源时使用带描述的 `redirect.github.com` Markdown 链接；正式上游 PR 再改为 repo-native 引用或普通链接。同仓库 issue/PR 需要展开标题时用独立列表项 `- #123`；commit 证据默认写完整 40 位 SHA。workflow、job 和 artifact 使用 `[失败记录](...)`、`[通过记录](...)`、`[CI](...)` 等短文本。
- **命名**：预审分支名、标题和 commit message 不包含上游 `#123`、`owner/repo#123`、完整 GitHub URL 或 closing keyword。“GitHub Draft PR”只表示平台状态，不用作预审流程名称。
- **正文**：不写预审状态、内部讨论、失败尝试、临时 CI 生命周期和待办；正文始终仿佛会直接交给上游 reviewer。
- **提交默认值**：预审阶段的后续修改默认提交并推送到预审分支；正式上游 PR 阶段默认只改本地，除非用户明确要求推送或正在执行正式 PR 重放。
- **工具**：提交和推送使用 `git-workflow`；GitHub PR、comment、checks 和 workflow 操作使用 `github-cli`；正文先写入 `/tmp/*.md`，再通过 `--body-file` 创建或更新。

## Fork 预审流程

1. **确认基准**
   - 获取上游目标分支和 fork 基准分支，确认二者一致。
   - 可 fast-forward 时按用户授权更新；出现分叉或额外提交时停下来确认。
2. **创建分支和 PR**
   - 从 fork 基准创建只包含当前任务的分支。
   - PR 开在用户 fork 内，base 指向 fork 基准；标题和正文默认中文并遵循目标仓库模板。
   - 创建带 marker 的内部记录 comment，建议包含“当前状态、内部证据、待确认、正式提交前清理”。
3. **收敛**
   - 运行必要 CI 和内部 review；通过 follow-up commit 正常推进，不默认改写历史。
   - PR 正文只随最终净变化更新；过程信息只更新到原内部记录 comment。

用户明确要求跳过预审时，直接进入正式上游 PR 流程。用户要求“像预审 PR 没存在过”时，从最新上游基准重建正式分支，不复用预审历史。

## Red / Green / Cleanup

仅在 bugfix 需要证明回归测试有效，或临时 CI 能提供关键证据时使用。三个阶段必须分别推送并等待结果，否则通常无法获得独立 job URL。

1. **Red**：只加入能在旧实现上编译、并因目标行为断言而失败的测试或临时 CI。记录 commit、job URL 和失败摘要；配置、依赖、lint 或缺少修复符号导致的失败无效。
2. **Green**：只加入修复，不修改已证明有效的 red 测试。等待同一检查或等价检查通过并记录证据。
3. **Cleanup**：删除临时 workflow、脚本、配置和 matrix，保留修复与正式回归测试。最终 CI 尚在运行时可以更新正文，但要继续观察结果。

PR 正文先解释验证方法，再给简洁证据，不用阶段名代替结论。完整过程留在内部记录 comment。正文不重复列出 CI 已自然覆盖的 fmt、lint、build 和普通测试命令。

## 转为正式上游 PR

1. 从最新上游基准创建正式分支，或从预审分支整理出只包含最终改动的分支。
2. 按最终 diff 和目标仓库语言复核或翻译标题、正文与提交历史；移除预审、实验、rerun 和临时方案痕迹。
3. 使用真实上游上下文和 repo-native 链接；不要迁移内部记录 comment。
4. 优先使用正式 PR 自己的 CI 证据。若需要该 PR 自己的 red/green URL，在 GitHub Draft PR 中依次重放 red、green、cleanup，最后更新正文并标记 ready for review。
5. 只有无法取得正式 PR 的证据且用户接受时，才引用 fork CI，并在正文说明来源。

## 停下来确认

- fork 基准与上游分叉，或包含无法解释的额外提交。
- 需要 force-push 或重写 fork 基准历史。
- red 失败不是目标行为断言导致，或 green 必须修改 red 测试才能通过。
- 无法判断某个上游引用是否会产生不希望的关联或通知。

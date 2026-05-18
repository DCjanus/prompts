---
name: upstream-pr-staging
description: 用于向 GitHub 上游提交 PR 前，在用户 fork 内创建草稿 PR/内部 PR 做低干扰收敛；当用户提到草稿 PR、内部 PR、fork draft、先内部 review/CI、或 red/green 证据时使用。
---

# Upstream PR Staging

用于向 GitHub 上游提交 PR 前，先在用户 fork 内低干扰收敛方案、提交历史、CI 和证据，再整理成正式上游 PR。

## 先选路径

默认先做内部 draft，再准备正式上游 PR。

- **内部 draft**：用于探索和收敛。PR 开在用户 fork 内，默认中文标题和正文，默认低干扰。
- **正式上游 PR**：用于提交给上游 reviewer。标题、正文和提交历史重新整理，只保留上游需要的动机、行为变化和验证证据。
- **正式 PR 重放**：当正式 PR 需要自己的 red/green/cleanup workflow URL 时，从上游基准新建正式分支，在正式 draft PR 上按阶段重放提交。

如果用户明确要求跳过内部 draft，直接进入正式上游 PR 流程；如果用户要求“像内部 PR 没存在过”，从最新上游基准重建正式分支，不复用内部 draft 分支历史。

## 不变量

- 内部 draft 默认低干扰：不触发上游 issue / PR / discussion backlink、timeline mention 或通知。
- 内部 draft 的标题、正文默认中文；除非用户明确要求英文，或目标仓库/团队规范要求英文。
- 内部探索阶段不使用 `fixes` / `closes` / `resolves` 等可能自动关闭上游 issue 的关键词。
- 正式上游 PR 使用 repo-native 视角，不保留“内部 draft / fork 草稿”的叙述。
- 正式上游 PR 是否使用真实 issue 编号、普通 GitHub 链接或 closing keyword，按用户最新指令和目标仓库规范决定。
- 提交或推送前使用 `git-workflow`，不要把无关本地修改带进 PR。
- 创建或读取 GitHub PR、checks、workflow、job 时使用 `github-cli`。

## 链接策略

需要可点击链接时，不裸贴长 URL；按 PR 场景选择链接形式。

- 内部 draft 或其它低干扰场景引用上游 issue / PR / commit / discussion 时，默认使用 Markdown 链接配合 `redirect.github.com`，例如 `[RedisShake PR 1050](https://redirect.github.com/tair-opensource/RedisShake/pull/1050)`。
- 正式上游 PR 使用 repo-native 引用；同仓库 issue / PR 默认写成 `#1050` 这类形式，让 GitHub 自动渲染和关联。只有跨仓库、需要自定义链接文本或用户明确要求低干扰时，才改用 Markdown URL。
- 尽量不要用 inline code 表示上游 URL；只有在标题、分支名、commit message 等非 Markdown 环境，或明确不想要点击链接时，才把 `owner/repo#123`、`#123`、URL 写成普通文本或 inline code。
- 标题、分支名、commit message 不是可靠 Markdown 环境；内部 draft 中不要写 `#123`、`owner/repo#123`、完整 GitHub URL 或 closing keyword。
- workflow run、job、artifact、日志等证据链接写成短链接文本，例如 `[失败记录](...)`、`[通过记录](...)`、`[CI](...)`；证据含义写在链接前后的正文里。
- 同仓库 commit 证据默认裸写短 SHA，例如 c6bb444，不包 inline code；GitHub 会自动把同仓库 commit SHA 识别成链接。
- 只有跨仓库、需要消歧，或用户明确要求点击 commit 时，才把 commit 写成 `[c6bb444](...)`。

## 内部 Draft 流程

1. 确认基准。
   - 确认用户 fork 是否有对齐上游的基准分支，例如 `upstream_main`。
   - 获取上游目标分支和 fork 基准分支，确认两者是否一致。
   - 如果 fork 基准分支可 fast-forward 到上游，按用户授权更新；如果分叉或有额外提交，停下来确认。
2. 创建开发分支。
   - 从 fork 基准分支新建特性分支。
   - 分支只包含当前任务需要的提交。
   - 分支名默认不包含上游 issue / PR 编号。
3. 创建 fork 内部 draft PR。
   - PR repo 指向用户 fork，base 指向 fork 基准分支。
   - 标题、正文、分支名和 commit message 按低干扰规则处理。
   - PR body 写给内部审查者，说明背景、改动、验证、风险和待确认点。
   - 草稿正文优先写到 `/tmp/*.md`，再用 `gh pr create --body-file` 或 `gh pr edit --body-file`。
4. 内部收敛。
   - 等待必要 CI 和内部 review。
   - 记录对正式上游 PR 有价值的结论；探索过程、临时 workflow 和内部讨论不要原样搬过去。

## 正式上游 PR 流程

1. 从最新上游基准创建正式 PR 分支，或从内部 draft 中整理出只包含最终改动的分支。
2. 重新整理标题、正文和提交历史，让最终 diff 看起来像一开始就是这样设计的。
3. PR body 只写上游 reviewer 需要的信息：
   - 为什么需要这个改动。
   - 改了什么用户可见行为或维护边界。
   - 如何验证，证据入口在哪里。
4. 默认不列本地格式化、lint、测试命令；如果 CI 覆盖这些内容，直接引用 CI 证据。
5. 如果上游 maintainer 不希望保留多段提交，再按 reviewer 要求 squash 或重排历史。

## Red / Green 证据

只有 bugfix 需要证明回归测试有效时，才使用三阶段证据。不要一次性推送 red 和 green；否则 red 证据会变弱。

1. **Red**：只加入复现问题需要的回归测试、focused check 或临时 CI，不包含修复代码。
   - 旧实现必须能编译。
   - 失败必须来自行为断言，不是缺少修复里的符号、平台配置、依赖解析、生成文件、lint 或临时 workflow 本身。
   - 推送后等待目标 workflow/job 明确失败，记录 commit SHA、workflow/job URL 和失败摘要。
2. **Green**：只加入生产代码或真实实现。
   - 不修改 red 阶段已经确认有效的测试。
   - 推送后等待同一个检查或等价检查通过，记录 commit SHA 和 workflow/job URL。
3. **Cleanup**：删除临时 workflow、调试脚本、一次性配置或临时 matrix。
   - 保留正式回归测试和修复代码。
   - cleanup 推送后即可更新 PR 描述；不必先等待 cleanup 提交触发的正常 CI 全部通过。
   - 如果最终 CI 还在运行，PR body 简短说明正在运行；随后继续观察并按结果更新。

## 正式 PR 重放

当内部 draft 已经收敛，但正式 PR 需要自己的 red/green/cleanup workflow URL 时，按这个流程重放。

1. 从最新上游基准创建正式 PR 分支。
2. 只应用 red 提交并推送，创建到上游目标分支的 draft PR。
3. 等待正式 PR 的 pull_request workflow 或上游接受的等价检查失败，记录正式 PR/repo 下的 URL。
4. 应用 green 提交并推送，等待同一个检查或等价检查通过，记录正式 PR/repo 下的 URL。
5. 应用 cleanup 提交并推送，更新正式 PR 标题和正文。
6. 等 PR 描述、提交历史和必要 CI 状态都达到正式提交标准后，再标记 ready for review。

正式上游 PR 默认优先使用该 PR 自己触发的 workflow/job URL。只有无法取得正式 PR URL，且用户接受时，才退而使用 fork 分支 push 自动触发的 workflow/job URL，并在 PR body 里说明来源。

## PR Body 证据写法

PR body 要先说明验证方法论，再给证据；不要一上来用 Red / Green / Cleanup 这类标签代替解释。

推荐写法：

```markdown
提交历史按“测试有效性 -> 实现修复 -> 清理临时 CI”拆成三段，便于确认新增测试不是只覆盖最终状态。

- c6bb444：只加入测试；确认测试能在缺少目标行为时失败：[失败记录](https://github.com/owner/repo/actions/runs/123)。
- a1ec55e：只加入修复；确认同一检查通过：[通过记录](https://github.com/owner/repo/actions/runs/456)。
- f00ba47：删除临时 workflow；最终 CI 见：[CI](https://github.com/owner/repo/actions/runs/789)。
```

保持三条证据各占一行；每行只保留 commit、动作和证据入口，不展开完整失败细节。

## 停下来确认

- fork 基准分支和上游分叉，或含有无法解释的额外提交。
- 需要 force-push 或重写 fork 基准分支。
- red 阶段失败不是目标行为断言导致的。
- green 阶段必须修改 red 测试才能通过。
- 正式 PR 需要引用上游 issue/PR，但无法判断链接是否会产生不希望的 backlink。

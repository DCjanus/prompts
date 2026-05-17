---
name: upstream-pr-staging
description: 用于向 GitHub 上游提交 PR 前，在用户 fork 内创建草稿 PR/内部 PR 做低干扰收敛；当用户提到草稿 PR、内部 PR、fork draft、先内部 review/CI、或 red/green 证据时使用。
---

# Upstream PR Staging

用于向 GitHub 上游项目提交 PR 前，先在用户 fork 内创建低干扰 draft PR，收敛方案、CI、review 和必要证据，再整理成面向上游 reviewer 的最小 PR。

## 默认策略

内部 draft PR 默认低干扰，不需要用户额外说明。

低干扰指：

- 不让上游 issue / PR / discussion 自动出现 backlink、timeline mention 或通知。
- 不在内部探索阶段暴露未收敛的标题、正文、提交历史或临时 CI。
- 不使用 `fixes` / `closes` / `resolves` 等可能被平台解释为自动关闭的关键词。

内部 draft 的限制只服务内部收敛；正式上游 PR 阶段要重新整理标题、正文和提交历史，按用户最新指令和仓库规范决定是否恢复真实链接、issue 编号或 closing keyword。

## 背景引用

内部 draft 有时需要保留上游背景，但默认不要写成 GitHub 会自动引用的形式。

- 标题、分支名、commit message 不是可靠 Markdown 环境：不要写 `#123`、`owner/repo#123`、完整 issue URL 或 closing keyword。
- PR body 需要保留编号时，用 inline code 写成 `` `owner/repo#123` ``、`` `#123` `` 或 `` `https://github.com/owner/repo/issues/123` ``，让它作为背景文本而不是链接。
- 如果确实需要可点击链接但不要 backlink，把 Markdown 链接目标里的 `github.com` 换成 `redirect.github.com`。这是 GitHub 官方支持的 GitHub.com 写法，不适用于 GitHub Enterprise Cloud with Data Residency。
- 如果不能确认某种写法是否会 backlink，默认不用链接，改写成普通文本背景。

## PR 正文链接写法

PR body、review comment、issue comment 和交接说明里需要提供可点击链接时，默认使用 Markdown URL 语法，不要直接裸贴长链接。

- 对内部 fork PR、workflow run、job、commit、artifact、日志等证据链接，写成 `[简短描述](URL)`。
- 链接文本要说明目标和用途，例如 `[red run](...)`、`[green run](...)`、`[failing job](...)`、`[cleanup commit](...)`，不要只写 `[link](...)`。
- 如果同一段里有多个证据链接，优先合并到一句短说明或项目符号里，避免连续堆 URL。
- 如果链接指向上游 issue / PR / discussion，仍要先遵循“背景引用”的低干扰规则；需要可点击但不想触发 backlink 时，用 Markdown 链接配合 `redirect.github.com`。
- commit SHA 可以写成短 SHA 文本；如果需要可点击，写成 `[c6bb444](...)` 这类 Markdown 链接。

示例：

```markdown
- Red: [focused workflow run](https://github.com/owner/repo/actions/runs/123) failed with `aof_received_bytes=1103`.
- Green: [focused workflow run](https://github.com/owner/repo/actions/runs/456) passed after [a1ec55e](https://github.com/owner/repo/commit/a1ec55e...).
```

## 内部 Draft 流程

1. 确认基准
   - 确认用户 fork 里是否有专门对齐上游的基准分支，例如 `upstream_main`。
   - 获取上游主分支和 fork 基准分支，确认两者是否一致。
   - 如果 fork 基准分支能 fast-forward 到上游，按用户授权更新；如果出现分叉或额外提交，停下来确认。

2. 创建开发分支
   - 从 fork 基准分支新建特性分支。
   - 分支只包含当前任务需要的提交，不夹带工作树里的其它改动。
   - 分支名默认不包含上游 issue / PR 编号。

3. 创建 fork 内部 draft PR
   - PR repo 指向用户 fork，不指向上游仓库。
   - base 指向 fork 基准分支，head 指向当前特性分支。
   - 标题、正文、分支名和 commit message 按低干扰规则处理。
   - PR body 写给内部审查者：说明背景、改动、验证、风险和待确认点。
   - 草稿正文优先写到 `/tmp/*.md`，再用 `gh pr create --body-file` 或 `gh pr edit --body-file`。

4. 内部收敛
   - 等待必要 CI 和内部 review。
   - 用 `github-cli` 查询 PR、checks、workflow 和 job 链接。
   - 记录对正式上游 PR 有价值的结论；证据链接按“PR 正文链接写法”整理，探索过程、临时 workflow 和内部讨论不要原样搬过去。

5. 准备上游 PR
   - 重新整理标题、正文和提交历史，让最终 diff 看起来像一开始就是这样设计的。
   - 只保留上游 reviewer 需要的动机、行为变化、验证结果和必要背景。
   - 是否引用上游 issue / PR / discussion，按用户最新指令和仓库规范决定。
   - 如果本次是 bugfix，且用户要求或任务需要证明新增回归测试有效，正式上游 PR 也应保留或重建“只加测试 / 只加修复 / 删除临时 workflow”三段提交，方便 reviewer 直接看到测试先失败、修复后通过、临时 workflow 已清理。

## Red / Green 证据

只有 bugfix 需要证明回归测试有效时，才使用这一节。

1. Red 阶段
   - 只加入复现问题需要的回归测试、focused check 或临时 CI。
   - 不包含修复代码。
   - 确认旧实现能编译，并通过行为断言失败；不能因为缺少修复里的符号失败。
   - 推送后等待目标 workflow / job 明确失败，记录 red commit SHA、workflow/job 链接和失败摘要；写入 PR body 时链接必须使用 Markdown URL 语法。

2. Green 阶段
   - 只修改生产代码或真实实现。
   - 不修改 red 阶段已经确认有效的测试。
   - 推送后等待同一个检查或等价检查通过，记录 green commit SHA、workflow/job 链接；写入 PR body 时链接必须使用 Markdown URL 语法。

3. 清理阶段
   - 删除临时 workflow、调试脚本、一次性配置或临时 matrix。
   - 保留正式回归测试和修复代码。
   - 等待正常 CI 通过，再把必要 red/green 证据写进最终 PR 描述。

不要一次性推送 red 和 green；否则远端只会突出最终 head 的 CI，red 证据会变弱。

## 上游 PR 中呈现验证思路

当正式上游 PR 需要展示测试和修复分别有效时，默认按下面方式处理：

1. 上游 PR 分支保留三段提交：
   - `test(...)`：只加入回归测试和必要的临时 focused workflow，不包含修复代码。
   - `fix(...)`：只加入修复代码，不修改 red 阶段已验证有效的测试。
   - `chore(ci)`：删除临时 workflow、调试脚本或一次性配置，只保留正式测试和修复。
2. PR body 要短，不写完整流水账；用三条项目符号说明“只加入测试 / 只加入修复 / 删除临时 workflow”的验证思路即可。
3. PR body 里的 commit 和测试任务链接必须使用 Markdown URL 语法，例如 `[第一个 commit](...)`、`[测试任务](...)`；避免裸 URL。
4. 如果没有权限直接运行上游仓库 workflow，可以使用用户 fork 中由分支 push 自动触发的 workflow/job URL 作为证据；PR body 里用一句话说明这些测试任务来自 fork 分支 push 自动触发的 workflow。
5. 如果 red 阶段是上游 PR 分支的一部分，推送 red 后先等待目标 job 明确失败，再推送 green；不要在没有拿到 red job URL 前继续。
6. 不要在上游 PR 描述里默认列本地验证命令；除非仓库模板要求或用户明确要求，否则优先说明验证思路和关键证据。
7. 如果上游 maintainer 不希望 PR 历史保留 red/green/cleanup 提交，再按 reviewer 要求 squash 或整理历史。

## 硬规则

- 内部 draft PR 默认低干扰；除非用户明确要求，否则不要写会自动链接或 cross-reference 上游 issue / PR / discussion 的标题、正文、分支名或 commit message。
- 不要擅自 force-push 或重写 fork 基准分支；如果基准分支和上游分叉，先说明状态并等待确认。
- 如果 red 阶段失败来自平台 cfg、依赖解析、feature 选择、生成文件、lint 或临时 workflow 本身，不算有效 red proof；先修正测试入口或 CI matrix。
- 如果 green 阶段必须改 red 测试，停下来重新设计复现阶段。
- 提交或推送前使用 `git-workflow`，不要把无关本地修改带进 PR。
- 创建或读取 GitHub PR、checks、workflow 时，使用 `github-cli` 获取当前状态和 job 链接。

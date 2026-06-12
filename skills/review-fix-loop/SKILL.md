---
name: review-fix-loop
description: 用干净的独立 subagent 反复做代码审查、由主 agent 判断审查意见价值、修复有效问题并提交推送，直到连续三轮没有有价值审查意见。适用于用户要求 review/fix loop、clean review cycle、创建新 subagent 审查当前修改、反复 review 到没有问题、或“连续三次没有有价值建议”这类任务。
---

# Review Fix Loop

## 核心目标

把“独立审查 -> 主 agent triage -> 修复验证 -> 提交推送 -> 再审查”的循环做成可控流程。reviewer subagent 只负责找问题；主 agent 保留最终判断权，避免把低价值建议或误报自动变成代码改动。

## 启动前检查

- 明确审查对象：当前工作树、当前分支相对默认分支、某个 PR/MR，或用户指定的 diff。
- 先确认本地状态和目标分支：用 `git status --short --branch`、`git branch --show-current`、平台 CLI 或 `git merge-base` 等低风险命令建立上下文。
- 如果任务涉及 GitHub/GitLab、commit、push 或 PR/MR 文案，同时使用对应平台 skill 与 `git-workflow` skill；本 skill 只定义循环控制。
- 如果工作树已有用户未提交改动，先识别范围。不要回滚或覆盖无关改动；必要时只 stage 本轮修复相关文件。

## 循环规则

维护一个 `clean_rounds` 计数，初始为 0。

每一轮都执行：

1. 创建一个新的 subagent，`fork_context=false`，让它看不到当前对话历史。
2. 明确要求它只做 review，不改文件、不提交、不推送。
3. 让它基于最终净变化审查，例如当前分支相对默认分支、PR diff、MR diff，避免围绕历史中间状态提意见。
4. 等待 subagent 完成，并关闭它，避免占用 agent 名额。
5. 主 agent 独立判断每条 finding 是否有价值。
6. 如果没有有价值 finding：`clean_rounds += 1`。
7. 如果存在有价值 finding：修复、验证、提交并推送；然后把 `clean_rounds` 重置为 0。
8. 当 `clean_rounds >= 3` 时停止循环。

## Reviewer Prompt 模板

按任务实际替换仓库路径、目标分支和重点风险：

```text
You are reviewing changes in repository <repo-path>. Do not edit files.
Do an independent code review of the current checked-out branch against <base-branch-or-PR-target>, focusing only on actionable bugs, behavioral regressions, compatibility problems, missing high-value tests, or CI/workflow risks introduced by this branch.

Please inspect the final net diff yourself with git/platform CLI rather than relying on prior conversation.

Pay special attention to:
- <risk area 1>
- <risk area 2>
- <risk area 3>

Output format:
- Start with Findings.
- If you find an issue, include file/line references and why it matters.
- If you find no actionable issues, say exactly that and list only concise residual risks.
- Do not make changes, commits, or pushes.
```

## Finding 价值判断

把 finding 当成“待验证假设”，不是命令。

有价值 finding 通常满足至少一项：

- 指向真实 bug、行为回归、数据损坏、兼容性破坏、安全问题、竞态、资源泄漏或 CI 阻断。
- 指出缺失的高价值测试，且测试能覆盖明确的公开行为、历史回归点、边界条件或高风险路径。
- 指出 PR/MR 目标与最终 diff 不一致，会误导 reviewer 或发布流程。
- 指出平台配置、workflow、镜像、权限、缓存、矩阵等会导致合并前后行为不可靠。

通常不要把这些当成有价值 finding：

- 纯风格偏好，且项目没有相关规范。
- 只要求覆盖当前实现细节、调用顺序或低价值中间状态的测试。
- “可以更完善”的泛泛建议，但没有指出实际风险或失败路径。
- 与本次 final net diff 无关的问题，除非它会直接阻塞本次改动。

## 修复与验证

如果 finding 有价值：

- 先用最小范围理解问题，必要时本地复现。
- 修复时遵守当前仓库规范；不要顺手重构无关代码。
- 补测试时优先覆盖对外行为、历史回归点、边界条件或高风险路径。
- 按风险选择验证命令；如果仓库有统一 pre-commit / before-commit 命令，优先跑它。
- 提交前复核 `git diff --check`、`git status --short` 和 staged diff。
- commit/push 后继续下一轮；不要因为“刚修过”直接跳过新的 clean review。

## 汇报方式

过程中简短汇报每轮结果：

- 第 N 轮 subagent 是否发现 actionable findings。
- 主 agent 接受或拒绝 finding 的理由。
- 如果修复了问题，说明修复范围、验证命令、commit 和 push 状态。
- 结束时明确说明已经连续 3 轮无有价值意见，以及剩余风险是否只是非阻断性 residual risk。

## 失败与中断处理

- 如果 subagent 被中断且没有完整 findings，这一轮不计入 clean round，重新开一轮。
- 如果 subagent 超时但可能仍在运行，不要把它当成 clean round；先等待、关闭或重新发起。
- 如果 CI 或本地验证失败，先修验证失败；修完后 `clean_rounds` 归 0。
- 如果被用户要求暂停，停止循环并报告当前轮次、已接受 finding、未完成验证和下一步。

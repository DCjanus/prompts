---
name: review-fix-loop
description: 用三个相互隔离的干净 subagent 并行做代码审查、由主 agent 判断审查意见价值、修复有效问题并提交推送，直到同一批三个 reviewer 都没有有价值审查意见。适用于用户要求 review/fix loop、clean review cycle、创建新 subagent 审查当前修改、反复 review 到没有问题、或“三个独立 reviewer 都没有有效建议”这类任务。
---

# Review Fix Loop

## 核心目标

把“三个相互隔离的并行独立审查 -> 主 agent triage -> 修复验证 -> 提交推送 -> 再审查”的循环做成可控流程。reviewer subagent 只负责找问题；主 agent 保留最终判断权，避免把低价值建议或误报自动变成代码改动。

## 启动前检查

- 明确审查对象：当前工作树、当前分支相对默认分支、某个 PR/MR，或用户指定的 diff。
- 先确认本地状态和目标分支：用 `git status --short --branch`、`git branch --show-current`、平台 CLI 或 `git merge-base` 等低风险命令建立上下文。
- 如果任务涉及 GitHub/GitLab、commit、push 或 PR/MR 文案，同时使用对应平台 skill 与 `git-workflow` skill；本 skill 只定义循环控制。
- 如果工作树已有用户未提交改动，先识别范围。不要回滚或覆盖无关改动；必要时只 stage 本次修复相关文件。

## 循环规则

每次并行启动 3 个新的干净 reviewer subagent；三个 reviewer 都看不到当前对话历史，也互相看不到彼此的输出。

每个 batch 都执行：

1. 整理一个简短的 review context packet（见下节），只放事实和约束，不放希望 reviewer 得出的结论。
2. 并行创建 3 个新的干净 subagent，让它们看不到当前对话历史，并且彼此相互隔离。按当前可用工具 schema 选择参数：
   - MultiAgentV1 / `multi_agent_v1.spawn_agent`：传 `fork_context=false`，或省略 `fork_context`（默认 false）。
   - MultiAgentV2 / `spawn_agent`：必须传 `fork_turns="none"`；不要使用 `fork_context`，也不要省略 `fork_turns`，因为 v2 默认 `fork_turns="all"` 会 fork 全历史。
3. 三个 reviewer 使用同一份 review context packet 和同一审查范围，但在 prompt 中标明自己的编号（例如 Reviewer 1/2/3），便于主 agent 汇总来源。
4. 明确要求它们只做 review，不改文件、不提交、不推送。
5. 让它们基于最终净变化审查，例如当前分支相对默认分支、PR diff、MR diff，避免围绕历史中间状态提意见。
6. 把 review context packet 放进 reviewer prompt，帮助它们跳过已验证事实和已判定非问题，但仍要求它们在 diff 证据相反时指出问题。
7. 等待 3 个 subagent 都完成，并关闭它们，避免占用 agent 名额。
8. 主 agent 合并三个 reviewer 的输出，去重后独立判断每条 finding 是否有价值。
9. 如果三个 reviewer 都没有有价值 finding：停止循环，认为审查通过。
10. 如果任一 reviewer 提出有价值 finding：修复、验证、提交并推送；然后重新启动下一批 3 个干净 reviewer。

## Review Context Packet

每个 batch 创建 subagent 前，主 agent 应准备一个低噪音上下文包，减少 reviewer 重复消耗在已验证或已排除的问题上。

允许包含：

- 审查对象：repo、当前分支、base/target、PR/MR 编号或 diff 范围。
- 已验证事实：已通过的 CI/check 名称、手动 workflow run URL、真实环境验证结果、已发布镜像 digest 等。
- 本次审查重点风险：希望 reviewer 优先看的具体模块、协议、兼容性或 workflow 风险。
- 已判定非问题：此前或主 agent 已核实的误报，并给出一句证据，例如“该 workflow 已手动运行成功，run: ...”。
- 约束：不要改文件、不要提交、不要推送；只看 final net diff；输出 actionable findings。

禁止包含：

- 主 agent 希望 reviewer 复述的结论。
- 未经验证的安慰性判断，例如“这个应该没问题”。
- 修复思路、怀疑点或内部推理，除非它本身就是需要 reviewer 验证的明确问题。
- 大段历史过程、失败尝试或与 final diff 无关的探索细节。

如果 reviewer 发现 context packet 与 final diff 或平台状态冲突，应以可验证证据指出冲突；context packet 不是免审清单。

## Reviewer Prompt 模板

按任务实际替换 reviewer 编号、仓库路径、目标分支和重点风险。三个并行 reviewer 应使用同一模板，但 reviewer 编号不同：

```text
You are Reviewer <1|2|3> in a parallel batch of three isolated reviewers.
You are reviewing changes in repository <repo-path>. Do not edit files.
Do an independent code review of the current checked-out branch against <base-branch-or-PR-target>, focusing only on actionable bugs, behavioral regressions, compatibility problems, missing high-value tests, or CI/workflow risks introduced by this branch.

You were started as a fresh-context reviewer. Do not rely on any prior parent-agent conversation or other reviewers. Please inspect the final net diff yourself with git/platform CLI.

Known verified facts and prior non-issues:
- <fact 1 with evidence, or "None">
- <fact 2 with evidence>

If any known fact conflicts with the final diff or live platform state, call that out as a finding with evidence.

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
- 推翻 review context packet 中“已验证事实/已判定非问题”，并给出新的 diff、日志或平台证据。

通常不要把这些当成有价值 finding：

- 纯风格偏好，且项目没有相关规范。
- 只要求覆盖当前实现细节、调用顺序或低价值中间状态的测试。
- “可以更完善”的泛泛建议，但没有指出实际风险或失败路径。
- 与本次 final net diff 无关的问题，除非它会直接阻塞本次改动。
- 重复指出 context packet 中已有证据证明的非问题，且没有补充新的反证。

## 修复与验证

如果 finding 有价值：

- 先用最小范围理解问题，必要时本地复现。
- 修复时遵守当前仓库规范；不要顺手重构无关代码。
- 补测试时优先覆盖对外行为、历史回归点、边界条件或高风险路径。
- 按风险选择验证命令；如果仓库有统一 pre-commit / before-commit 命令，优先跑它。
- 提交前复核 `git diff --check`、`git status --short` 和 staged diff。
- commit/push 后继续下一批 3 个并行 reviewer；不要因为“刚修过”直接跳过新的 clean review。

## 汇报方式

过程中简短汇报每个 batch 的结果：

- 当前批 3 个并行 subagent 各自是否发现 actionable findings。
- 主 agent 接受或拒绝 finding 的理由。
- 如果修复了问题，说明修复范围、验证命令、commit 和 push 状态。
- 结束时明确说明同一批 3 个相互隔离的 reviewer 都没有有价值意见，以及剩余风险是否只是非阻断性 residual risk。

## 失败与中断处理

- 如果当前 subagent 工具不支持创建干净上下文（例如无法设置 `fork_context=false` 或 `fork_turns="none"`），停止循环并向用户说明不能保证独立审查，不要把 forked reviewer 的结果计入通过 batch。
- 如果任一 subagent 被中断且没有完整 findings，整批不计为通过；先关闭已完成 reviewer，重新开一批。
- 如果任一 subagent 超时但可能仍在运行，不要把这一批当成通过；先等待、关闭或重新发起整批。
- 如果只有部分 reviewer 成功完成，即使完成的 reviewer 都没有 finding，也不能认为审查通过；必须重新开一批完整的 3 个干净 reviewer。
- 如果 CI 或本地验证失败，先修验证失败；修完后重新开一批 3 个并行 reviewer。
- 如果被用户要求暂停，停止循环并报告当前 batch、已接受 finding、未完成验证和下一步。

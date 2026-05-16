---
name: pr-proof-chain
description: 当用户准备给开源项目提交 bugfix PR，并需要新增回归测试证明“旧代码失败、修复后通过”时使用；重点是先证明测试用例有效，再修复代码，并把红绿证据写进 PR，降低 reviewer 的决策成本。
---

# PR Proof Chain

用于开源项目 bugfix PR：先补回归测试，确认旧代码在这个测试下失败；再修复代码，确认同一个测试通过；最后把失败和通过的证据写进 PR，说明这个测试确实覆盖了要修的 bug。

这套流程不是为了机械遵守“先写测试再写代码”的规范，而是为了降低 reviewer 的决策成本：让 reviewer 能直接看懂这个 bug 如何被测试复现、修复后为什么有效，以及最终 PR 为什么只保留必要改动。

## 何时使用

用户要给开源项目或上游项目修 bug，并且出现这些需求时使用：

- 需要新增回归测试，避免同一个 bug 将来再次出现。
- 需要先确认旧代码会被这个新测试打失败，证明测试本身有效。
- 需要再修复代码，并确认同一个测试变绿。
- 需要让 reviewer 看到失败 job 和通过 job 的链接。
- 需要分阶段整理 PR 历史，让“测试有效”和“代码修复”各自有证据。

普通小修复不需要使用这个 skill；如果不需要向 reviewer 证明测试有效，本地先跑失败测试、修复后再跑通过就够了。

## 执行流程

1. 复现阶段
   - 只加入复现问题需要的回归测试、focused check 或临时 CI。
   - 不包含修复代码。
   - 先确认当前 PR 的 CI 会跑到目标测试；如果普通 CI 不会覆盖目标测试，先加临时 focused workflow/job，最后再清理。
   - 可以用 focused CI 只跑相关测试，减少全量 CI 噪声。
   - 只推送 red commit，不要同时推送修复 commit。
   - 等目标 workflow / job 明确失败后，记录 red commit SHA、workflow URL、job URL、失败摘要。

2. 修复阶段
   - 只修改生产代码或真实实现。
   - 不修改复现测试或临时检查。
   - 在失败证据记录后，只推送 green commit。
   - 等待同一个检查或等价检查通过，记录 green commit SHA、workflow URL、job URL。

3. 清理阶段
   - 删除临时 workflow、调试脚本、一次性配置或临时 matrix。
   - 保留正式回归测试和修复代码。
   - 推送后等待正常 CI。
   - 最后更新 PR 描述，把 red/green 证据链接写进去；不要在只有 red commit 挂在 PR 上时提前写成最终修复已完成。

不要一次性推送所有阶段；否则远端只会给最终 head 留下 CI 证据。

## 推送节奏

如果需要改写远端 PR 分支历史，必须先确认用户允许，并用 `--force-with-lease` 绑定期望的旧 SHA：

```bash
git push --force-with-lease=refs/heads/<branch>:<expected_old_sha> \
  origin <red_sha>:refs/heads/<branch>
```

red job 明确失败并记录证据后，再推 green：

```bash
git push --force-with-lease=refs/heads/<branch>:<red_sha> \
  origin <green_sha>:refs/heads/<branch>
```

不要在同一次 push 中同时包含 red 和 green commit。

## 证据记录

推送 green 之前，先保存 red 证据；PR 页面通常只突出当前 head 的 checks，后续推送可能让 red run 不再显眼。

至少记录：

- Red commit SHA
- Red workflow URL
- Red failing job URL
- 具体失败测试或断言摘要
- Green commit SHA
- Green workflow URL
- Green passing job URL

如果失败来自平台 cfg、依赖解析、feature 选择、生成文件、lint 或临时 workflow 本身，而不是目标行为断言，这不能算作有效 red proof；先修正测试入口或 CI matrix，再重新开始复现阶段。

## 硬规则

- 复现阶段必须能在旧实现上编译，并通过行为断言失败，而不是因为缺少修复里的符号失败。
- 如果修复阶段必须改测试，停下来重新设计复现阶段。
- 如果多个关键测试都需要单独证明，给每个测试准备独立的 focused job。
- 只有用户明确允许改写历史时，才使用 `--force-with-lease`。
- 提交或推送前使用 `git-workflow`，不要把无关本地修改带进 PR。
- 读取 GitHub 或 GitLab checks 时，使用 `github-cli` 或 `gitlab-cli` 获取当前 PR/MR 状态和 job 链接。

## PR 描述

不要求固定格式，但必须让 reviewer 看懂两件事：

- 验证思路：先加测试或 focused check，在旧实现上确认失败；再只改修复代码，确认同一个检查通过；最后移除临时 workflow 或一次性验证配置。
- 证据链接：给出修复前失败的 workflow / job URL、修复后通过的 workflow / job URL；如果有最终全量 CI，也可以补最终 CI URL。

描述保持简短，使用 Markdown link，不要贴裸 URL。目标是降低 reviewer 的决策成本，而不是堆叠过程细节。

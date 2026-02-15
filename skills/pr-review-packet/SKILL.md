---
name: pr-review-packet
description: 生成 PR Review Packet（上下文/变更地图/阅读顺序/验证清单/待确认问题）；需要加速人类 review GitHub PR 时使用（review PR/code review/影响面/边界条件/checklist）。
---

为人类 reviewer 生成一份“Review Packet”（外部记忆笔记），用于降低来回翻找与重复阅读成本。

约束：不输出最终评审结论（如“LGTM/不通过/应该怎么改”）；只做事实摘录、结构化整理、可操作的导航与清单。

## Quick start

0) 创建 Review Packet 文件（默认落在 `/tmp`，每次生成一个新 Markdown）

```bash
cd skills/pr-review-packet
PACKET_PATH="$(mktemp "/tmp/pr-review-packet.XXXXXX.md")"
cp assets/review_packet_template.md "$PACKET_PATH"
echo "$PACKET_PATH"
```

如需固定路径（会覆盖）：自行设置 `PACKET_PATH=/tmp/pr-review-packet.md` 后再 `cp`。

1) 一次性抓取 PR 上下文（优先用 GitHub CLI，不打开网页）  
复用现有脚本：[read_pr.py](../github-pr-issue/scripts/read_pr.py)

```bash
cd skills/github-pr-issue
./scripts/read_pr.py "$PR_URL" \
  --with-body --with-files --with-stats --with-commits \
  --with-comments --with-reviews
```

需要深挖时再取 diff / review comments：

```bash
cd skills/github-pr-issue
./scripts/read_pr.py "$PR_URL" --with-diff --with-review-comments
```

2) 生成 Review Packet  
将内容写入 `$PACKET_PATH`（以该文件作为唯一“外部记忆”），并按 SOP 填充。

## SOP（固定流程）

### Step 0：锁定输入与目标
- 输入：`PR_URL`、目标 base 分支、是否有对应 Issue/设计文档（若缺失，记录到 “Open Questions”）。
- 目标：明确 reviewer 需要回答的 1 个问题（例如：风险是否可控、边界是否覆盖、影响面是否完整）。

### Step 1：Context Ingest（只做摘录与结构化）
从 PR body、issue comments、reviews 中提炼为短句要点：
- 需求背景 / 动机（why）
- 约束 / tradeoffs（constraints）
- 明确的非目标（non-goals）
- 已知风险与回滚/发布注意事项

要求：每条要点都附带来源（body/评论作者/时间点或引用片段）。

### Step 2：Change Map（把 diff 拆成“变更单元”）
把变更拆为 3–8 个“变更单元”（不要按文件逐条罗列），每个单元固定字段：
- What：行为/能力改了什么（面向系统行为，不是“改了哪些代码”）
- Why：对应的动机/约束（可引用 Step 1）
- Impact：入口/调用方/配置/数据/权限/外部依赖/回滚点
- Invariants：必须保持的不变量（协议、接口契约、幂等等）
- Evidence：证据指针（文件/关键符号/讨论点）

### Step 3：Reading Order（给出最短阅读路径）
基于 Change Map 输出阅读顺序（入口 → 编排 → 关键分支/边界 → 数据/外部依赖 → 测试与回滚点）：
- 每一项写清楚“为什么先看这里”
- 为“网页+本地混用”提供导航命令（示例）：
  - 本地定位：`rg -n "<symbol-or-keyword>" .`
  - 看变更：`git diff <base>...HEAD -- <path>`
  - 看历史：`git blame <path>` / `git log -p -- <path>`
  - 本地检出 PR（若在仓库内）：`gh pr checkout <number>`

### Step 4：Verification Checklist（可勾选、可操作）
输出 checklist，要求每条都落到“去哪看/怎么验”：
- 边界：空值/异常/超时/重试/并发/幂等
- 兼容：API/配置/数据迁移/默认值变化
- 可观测：日志/指标/告警/错误码
- 安全：鉴权/输入校验/敏感信息
- 性能：复杂度/热路径/IO
- 测试：覆盖核心路径与边界；缺失则记录为风险/问题

### Step 5：Open Questions for Author（只列必要闭环问题）
列出你无法从 PR 信息与代码直接确认、但会影响是否能合并/上线的关键问题：
- 隐含假设是什么？失败模式怎么处理？
- 回滚/降级策略是什么？
- 线上数据/配置/权限的影响是什么？
- 监控与告警如何证明变更正常？

### Step 6：Review Notebook（单一外部记忆）
全过程只维护一份 Notebook：
- Confirmed：已确认事实（带证据）
- Risks：风险点与触发条件
- TBD：待确认项与负责人（你/作者/CI）

## 输出约定（强约束）

最终产出以 `$PACKET_PATH` 文件为准，并遵循：
1) 必须写入 `Review Packet`（按模板完整填充）
2) 回复中单独一行输出 `$PACKET_PATH` 的绝对路径（方便人类直接打开）
3) 回复中附带 `Open Questions` 与 `Navigation`（避免把整份 Packet 粘贴到对话里）

## 资源
- 模板：[review_packet_template.md](assets/review_packet_template.md)
- PR 抓取脚本：[read_pr.py](../github-pr-issue/scripts/read_pr.py)

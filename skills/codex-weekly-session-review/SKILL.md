---
name: codex-weekly-session-review
description: 汇总过去一段时间的 Codex sessions 并起草中文周报或状态更新；当用户要求回顾最近一周 Codex 任务、包含 archived 任务、按 session/turn 总结工作、用便宜快速模型先做 session 摘要、或为定时自动化准备周报输入时使用。
---

通过 Codex Python SDK 读取 Codex app-server 中的 thread/session，按时间窗口汇总用户过去一周实际推进的工作，并生成可复用的结构化摘要与状态更新草稿。

## 核心原则

- 只走 Codex Python SDK / app-server，不读取 `~/.codex/sessions` 或 `~/.codex/archived_sessions` 的内部 jsonl 作为 fallback。
- 按 turn 时间窗口总结，而不是按 thread 整体总结。长 session 可以跨多周存在，但本周状态更新只能计入事实依据窗口内 turns 的工作。
- 默认使用 7 天事实依据窗口和 8 天上下文窗口：第 8 天只作为上下文缓冲，不得写成本周完成项。
- 不使用 fork + rollback 作为默认方案。当前 app-server 支持持久 fork 后 rollback，但不支持 ephemeral rollback，也没有可用的 thread delete；为了避免制造临时 thread，默认走简单的 7+1 窗口方案。
- 默认跳过 fork 副本，避免把临时 fork、review fork 或重复分支任务算进周报。
- 脚本内部模型调用必须使用 ephemeral thread，避免摘要 helper thread 反过来污染后续周报输入。
- 先用快速模型生成单 session 摘要卡片，再用更强模型聚合成最终状态更新，避免让最终模型直接读取大量原始 turns。

## 脚本调用

说明：以下脚本调用均以当前 `SKILL.md` 所在文件夹为 workdir。

脚本调用方式（必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`）：

```bash
cd skills/codex-weekly-session-review
./scripts/codex_weekly_session_review.py --help
```

错误示例：

```bash
uv run python skills/codex-weekly-session-review/scripts/codex_weekly_session_review.py --help
python skills/codex-weekly-session-review/scripts/codex_weekly_session_review.py --help
```

## 推荐流程

先检查本次会处理哪些 threads：

```bash
./scripts/codex_weekly_session_review.py inspect --evidence-days 7 --context-days 8 --limit 200
```

`inspect` 固定输出 JSON，面向 Agent 和自动化消费。如果只需要汇报会被纳入的 threads，直接读取 JSON 中的 `threads` 列表：

```bash
./scripts/codex_weekly_session_review.py inspect \
  --evidence-days 7 \
  --context-days 8 \
  --include-archived \
  --limit 200
```

`inspect` 会同时输出 `schema_version`、UTC 与本地时间窗口、`evidence_days`、`context_days`、`limit`、`include_archived`、`ordered_by`、`shown_count`、`counts_scope`、`scanned_excluded_total`、`scanned_excluded_counts` 等运行参数和扫描摘要。逐行判断是否纳入时，优先看 `threads[].evidence_first` / `threads[].evidence_last`，它们表示事实依据窗口内实际命中的 turn 时间；`threads[].updated` 只是 thread 元数据，长 session 的 `updated` 可能早于或不同于本次证据窗口。

命令未传 `--output` 时，默认向 stdout 输出 compact JSON，减少 Agent 上下文和终端截断风险；需要人工调试时再传 `--pretty`。传 `--output` 时 stdout/stderr 都保持静默，JSON 写入目标文件。

`inspect --schema` 会输出 inspect JSON Schema，不读取 sessions。`include_archived` 默认开启；推荐命令里显式传 `--include-archived` 只是为了让 Agent 输出中的调用意图更清楚。`shown_count` / `shown_active_count` / `shown_archived_count` 是应用 `limit` 后本次 JSON 中实际展示的数量；如果 `maybe_more_than_limit=true`，需要提高 `--limit` 才能展开更多候选。`scanned_excluded_total` / `scanned_excluded_counts` 是扫描过程中遇到的排除项统计，会受 `limit` 影响。逐条 thread 中的 `turns_label` 仅供显示，自动化应优先使用 `evidence_turns`、`context_buffer_turns`、`total_turns` 这些数值字段。

`threads` 按 `ordered_by=["evidence_last_desc","updated_desc"]` 排序；`scanned_excluded_counts` 会补齐 `active/archived` 与 `fork/summary_helper` 的 0 值，方便 Agent 直接做数值汇总。

`inspect`、`collect`、`draft-update` 都支持 `--until <ISO datetime>` 固定窗口结束时间；无时区的 ISO 值按 UTC 解析。JSON 中 UTC 时间使用 `Z` 后缀，并额外提供 `*_epoch` 数值字段，方便 Agent 用 `jq fromdateiso8601` 或直接用 epoch 做排序/比较。需要先 inspect 再 collect/draft 时，复用同一个 `until` 值以避免窗口漂移。

只生成确定性抽取结果：

```bash
./scripts/codex_weekly_session_review.py collect \
  --evidence-days 7 \
  --context-days 8 \
  --limit 200 \
  --output /tmp/codex-weekly-collect.json
```

用快速模型生成单 session 摘要卡片：

```bash
./scripts/codex_weekly_session_review.py summarize-sessions \
  --input /tmp/codex-weekly-collect.json \
  --output /tmp/codex-weekly-summaries.json \
  --model gpt-5.3-codex-spark \
  --effort low
```

一步生成最终状态更新：

```bash
./scripts/codex_weekly_session_review.py draft-update \
  --evidence-days 7 \
  --context-days 8 \
  --limit 200 \
  --fast-model gpt-5.3-codex-spark \
  --final-model gpt-5.5
```

## 长 session 处理策略

脚本读取完整 thread 后会按 turn 的 `completed_at` / `started_at` 切出两个窗口：

- `evidence_turns`：事实依据窗口内 turns，只能这些内容计入本周完成。
- `context_buffer_turns`：事实依据窗口前、上下文窗口内的 turns，只用于理解 continuation。
- `context_buffer`：第 8 天少量用户请求与最终回复原文片段，不是脚本维护的历史摘要。
- `context_compactions_in_evidence` / `context_compactions_in_buffer`：记录 compact marker 数量，只作为上下文完整性信号，不当作摘要正文。

如果用户明确要求“只总结过去一周”，不要把窗口前 final answer、旧 PR、旧排查结论写成新的完成项。正确写法是“本周继续推进 X，并在 Y 上完成 Z”。

## 模型选择

- 单 session 摘要默认使用 `gpt-5.3-codex-spark`，适合低成本快速生成结构化卡片。
- 最终状态更新默认使用 `gpt-5.5`，只读取摘要卡片并做主题聚合与措辞润色。
- 不要默认使用 `minimal` reasoning；当前 Codex SDK 运行环境可能带默认 tools，`minimal` 会与部分工具配置冲突。使用 `low` 作为快速摘要默认值。

## 输出约定

`collect` 输出稳定 JSON，适合作为调试和缓存输入。

`summarize-sessions` 输出每个 session 的结构化卡片，包括：

- `topic`
- `outcome`
- `repos_or_paths`
- `deliverables`
- `blockers`
- `followups`
- `importance`
- `evidence`

`draft-update` 输出 JSON；其中 `status_update` 是中文状态更新正文，默认包含：

- 本周完成
- 当前进展/阻塞
- 下周重点
- 依据摘要

## 自动化建议

定时任务 prompt 应要求使用这个 skill，并让脚本负责数据收集与分层摘要。不要在 automation prompt 里重新描述如何临时扫描 session 文件。

建议口径：

```text
Use $codex-weekly-session-review to review my Codex sessions from the past 7 days, including archived threads, and draft a concise Chinese status update.
```

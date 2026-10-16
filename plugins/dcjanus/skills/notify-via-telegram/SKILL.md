---
name: notify-via-telegram
description: 在用户明确要求后，通过本地安全配置发送当前长任务的 Telegram 结果通知；适用于用户希望离开终端，并在任务最终成功、最终失败或等待其处理时收到消息的场景。不得仅因任务耗时较长或一般任务完成而发送。
---

# Notify via Telegram

把 Telegram 通知视为用户对当前长任务的“结果订阅”，不是一般通知渠道。Bot Token 和目标 Chat ID 保存在用户本地配置文件中，不写入提示词、命令参数或仓库。

## 授权边界

- 只有用户在当前任务中显式调用 `$dcjanus:notify-via-telegram` 并要求通过 Telegram 通知，才允许发送。
- 不要因为任务耗时较长、执行了很多步骤、skill 被自动识别或普通任务完成而推断授权。
- 授权只覆盖当前任务，不延续到之后的任务。
- 默认不发送开始、进度、阶段完成、单条命令失败或自动重试消息。
- 在最终成功、确定无法继续的最终失败或必须等待用户输入时发送。可自动恢复的中间失败不发送。
- 等待用户处理时发送一次；用户回复并恢复执行后，当前订阅继续有效，任务最终结束时再发送结果。
- 每个通知事件最多发出一次 Telegram 发送请求；请求已发出后的失败不自动重发，避免结果不确定时产生重复消息。本地文案校验失败不算发送，按下面的修正上限处理。

## 执行约定

Agent 调用时使用 `--json`，并把全局参数放在子命令前。

### 发送前检查

1. 从 `./scripts/notify.py --help` 和 `preview --help` 查看参数及长度限制，拟好纯文本通知。首尾空白会被移除；必填字段和提供的可选字段都不能是空白。`context` 使用简短仓库或任务标签，不拼接长 URL；不要放入凭据、完整日志或冗长本地路径。
2. 实际发送前必须用 `./scripts/notify.py --json preview ...` 检查同一组参数。它不读取配置、不访问 Telegram；成功返回 `ok: true` 和 `rich_message`，检查内容是否准确表达任务结果。
3. 文案校验失败会返回非零退出码，以及 `error: invalid_notification`、`delivery: not_attempted` 和 `issues`。根据字段、原因及限制自行修正文案，再预览；保留关键事实，不静默截断或改变任务结果。
4. 每个通知事件从初稿起，最多允许 **30 次文案修正**，即最多初稿加 30 个修订版本。按整个事件累计，不能按字段、状态、命令或重跑流程清零。达到上限仍未通过时停止，不发送，报告通知校验失败；原任务结果保持不变。
5. 校验通过后以完全相同的参数调用 `--json send` 一次。发送前再改文案需要重新预览，并计入同一修正上限。`send` 也执行相同校验；若明确返回 `invalid_notification` 和 `not_attempted`，可在剩余额度内返回修正流程。

30 次上限只用于文案修正，不用于重复网络发送。配置缺失或无效时按配置指引处理；超时、异常响应、API 拒绝或其它发送失败均停止，不自动重发。脚本只负责校验和一次请求，修正文案与累计计数由 Agent 执行。

## 通知格式

只使用以下状态：

- `success`：整个任务最终完成。
- `failed`：整个任务确定无法完成，而不是某个中间步骤失败。
- `action-required`：任务暂停，必须等待用户输入或授权。

`title` 和 `summary` 必填；`verification`、`action`、`context` 可选。保持内容简洁，不发送完整日志、堆栈、凭据或冗长本地路径。

发送成功结果：

```bash
./scripts/notify.py --json send \
  --status success \
  --title "任务标题" \
  --summary "最终结果的一句话摘要" \
  --verification "关键验证结果" \
  --context "仓库或任务上下文"
```

发送失败结果：

```bash
./scripts/notify.py --json send \
  --status failed \
  --title "任务标题" \
  --summary "无法完成的直接原因" \
  --action "建议的下一步"
```

等待用户处理：

```bash
./scripts/notify.py --json send \
  --status action-required \
  --title "任务标题" \
  --summary "当前状态" \
  --action "需要用户决定或提供的内容"
```

在不读取配置、不访问 Telegram 的情况下预览同样的结构化参数：

```bash
./scripts/notify.py --json preview \
  --status success \
  --title "任务标题" \
  --summary "最终结果的一句话摘要"
```

所有输入字段按纯文本传入，不添加 HTML、Markdown 或 RichText 结构。脚本负责排版和 Codex 会话链接；`--json preview` 返回与发送一致的 `rich_message`，不读取配置、不联网。

## 配置

默认配置文件为 `${XDG_CONFIG_HOME:-~/.config}/notify-via-telegram/config.toml`；可用 `NOTIFY_VIA_TELEGRAM_CONFIG` 或全局 `--config` 指定其它文件。

```bash
./scripts/notify.py config path
./scripts/notify.py config show
./scripts/notify.py config get chat-id
./scripts/notify.py config set chat-id <chat-id>
./scripts/notify.py config set bot-token
./scripts/notify.py config unset chat-id
./scripts/notify.py config check
```

- `config set bot-token` 需要用户在交互式终端中隐藏输入；不要索取 Token，也不要尝试通过命令行参数传入。
- `config show`、`config get bot-token` 与所有 JSON 输出都不会回显 Token。
- `config check` 会访问 Telegram 验证 Bot 与目标 Chat，但不会发送消息。
- 配置缺失时，告诉用户应执行哪些配置命令；不要替用户猜测 Token 或 Chat ID。

发送成功后读取 JSON 中的 `message_id`。发送失败时，把通知失败与原任务结果分开报告，不要因此改变原任务的最终状态。

## 维护

仅在修改消息排版或深链 bridge 时阅读 [implementation.md](references/implementation.md)。

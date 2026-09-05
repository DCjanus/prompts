---
name: notify-via-telegram
description: 在用户明确要求后，通过本地安全配置发送当前长任务的 Telegram 结果通知；适用于用户希望离开终端，并在任务最终成功、最终失败或等待其处理时收到消息的场景。不得仅因任务耗时较长或一般任务完成而发送。
---

# Notify via Telegram

把 Telegram 通知视为用户对当前长任务的“结果订阅”，不是一般通知渠道。Bot Token 和目标 Chat ID 保存在用户本地配置文件中，不写入提示词、命令参数或仓库。

## 授权边界

- 只有用户在当前任务中显式调用 `$notify-via-telegram` 并要求通过 Telegram 通知，才允许发送。
- 不要因为任务耗时较长、执行了很多步骤、skill 被自动识别或普通任务完成而推断授权。
- 授权只覆盖当前任务，不延续到之后的任务。
- 默认不发送开始、进度、阶段完成、单条命令失败或自动重试消息。
- 在最终成功、确定无法继续的最终失败或必须等待用户输入时发送。可自动恢复的中间失败不发送。
- 等待用户处理时发送一次；用户回复并恢复执行后，当前订阅继续有效，任务最终结束时再发送结果。
- 每个通知事件只尝试发送一次。发送失败后不要自动重试，避免结果不确定时产生重复消息。

## 执行约定

Agent 调用时使用 `--json`，并把全局参数放在子命令前。

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
./scripts/notify.py preview \
  --status success \
  --title "任务标题" \
  --summary "最终结果的一句话摘要"
```

脚本统一生成 Telegram Rich Message 的显式 `blocks`：任务标题使用小号 heading，最终结论放入 blockquote；仅在提供 `action` 时增加高亮的“需要你处理”段落；用单行 footer 紧凑显示状态、验证和上下文。Codex 运行时提供合法的 `CODEX_SESSION_ID` 时，在 footer 后留出一个空行，再增加独立的两行会话入口：第一行加粗显示“↗ 打开 Codex 会话”，第二行展示完整 HTTPS URL，使长链接与结果元数据保持清晰的视觉分层。该链接经过配套 Cloudflare Worker 转为 `codex://threads/<session-id>`，绕过 Telegram 不支持自定义 URL 协议的问题。完整 URL 必须作为普通文本交由 Telegram 自动识别，不要改成隐藏目标的 URL 文字或按钮：Telegram 客户端会对这两种 inline link 强制弹出“Open this link?”确认。Codex 把 `CODEX_SESSION_ID` 定义为当前 agent tree 的根 thread ID，所以 subagent 通知返回根 Agent，普通 fork 成为新根后则指向 fork 出的新 thread。变量缺失或格式无效时省略链接，不要回退到 subagent 自己的 `CODEX_THREAD_ID`。不要添加泛化通知标题、分隔线或逐字段 Emoji。所有命令行输入字段都作为纯文本 RichText 传递；不要自行添加 Telegram HTML、Markdown 或 RichText 结构。

`preview --json` 返回与发送请求一致的 `rich_message` 对象，可在不读取配置、不访问 Telegram 的情况下检查内容块。格式能力与字段定义以 Telegram 官方的 [Rich Messages](https://core.telegram.org/bots/features#rich-messages) 和 [Bot API](https://core.telegram.org/bots/api#sendrichmessage) 文档为准。

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

## 深链 bridge

配套 Worker 位于 [worker](worker)，生产地址为 `https://codex-thread-bridge.dcjanus.workers.dev`。它只接受 `/codex/open-thread/<UUID>`，并直接返回指向对应 `codex://threads/<UUID>` 的 `302`；无效路径返回 `404`，因此不能被用作任意 URL 的开放重定向器。重定向响应允许浏览器缓存 1 天，以减少同一链接重复点击产生的 Worker 请求。Cloudflare Static Assets 的重定向规则不允许 `codex://` 目标，因此该 bridge 必须执行一段最小 Worker 脚本；每个未命中浏览器缓存的点击会产生一次 Worker 请求。

在本 skill 目录下执行以下命令可验证和部署 Worker：

```bash
node --test worker/test/index.test.mjs
wrangler deploy --dry-run --config worker/wrangler.jsonc
wrangler deploy --config worker/wrangler.jsonc
```

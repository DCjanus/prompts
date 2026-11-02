# 通知实现与维护

运行时行为由 [notify.py](../scripts/notify.py) 及其测试定义；修改排版或会话标识时保留以下设计约束。

- 标题、结论、待处理项和 footer 由脚本生成，输入字段始终为纯文本。
- 会话标识前保留空行，单独展示标签和行内代码格式的完整 session ID，方便复制；不生成 URL 或跳转按钮。
- 使用合法的 `CODEX_SESSION_ID` 返回当前 agent tree 的根任务；缺失或无效时省略，不回退到 subagent 的 `CODEX_THREAD_ID`。
- 用 `--json preview` 检查 `rich_message`。字段定义参考 Telegram 官方 [Rich Messages](https://core.telegram.org/bots/features#rich-messages) 和 [Bot API](https://core.telegram.org/bots/api#sendrichmessage)。

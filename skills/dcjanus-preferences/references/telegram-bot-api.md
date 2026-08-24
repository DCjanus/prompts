# Telegram Bot API 消息能力选择偏好

## 默认决策

- 短文本、操作确认、简单聊天流程，以及只需要粗体、斜体、链接、代码等少量行内格式时，默认使用 `sendMessage`。它更轻量、实现和调试成本更低，也支持 partial quote 与跨聊天引用等 Rich Message 没有的交互能力。
- 报告、AI 生成结果、文档片段，或内容需要标题、段落、分隔线、列表、表格、引用、折叠区、公式、媒体等明确块级结构时，使用 `sendRichMessage`。
- 不因为 `sendRichMessage` 更新、能力更多就默认替换 `sendMessage`。只有 richer structure 能实质提升信息层级、可扫读性或内容表达时才承担更高的 payload 与兼容成本。

## 内容表达方式

- 结构由程序生成、字段中包含用户或外部输入，或 payload schema 需要稳定可测试时，优先使用 `InputRichMessage.blocks`。动态文本作为纯 `RichText` 值传递，不拼接 Markdown/HTML，从而避免转义错误并让块级层级显式可见。
- 内容本身由可信模板或文档源维护、采用标记语言明显更易读时，可使用 Rich Markdown 或 Rich HTML。`InputRichMessage` 的 `blocks`、`markdown`、`html` 必须且只能选择一个；使用 Markdown/HTML 时仍要正确转义动态内容。
- 传统 `sendMessage` 的格式化沿用项目现有约定，在 MarkdownV2 与 HTML 中选择一种；不要为了少量样式引入 Rich Message。

## 流式输出与最终消息

- 只有需要在 Telegram 内实时展示生成过程时才使用 `sendMessageDraft` 或 `sendRichMessageDraft`。draft 是临时预览，最终仍必须调用对应的 `sendMessage` 或 `sendRichMessage` 才会持久化。
- 后台任务的完成通知、异步告警和一次性结果推送默认直接发送最终消息，不使用 draft。

## 兼容性与约束

- 使用前核对目标 Bot API 服务和 SDK 是否支持所需方法及字段；自建 Bot API Server、代理或第三方 SDK 可能落后于 Telegram 云端版本。没有明确兼容需求时，不额外实现 `sendRichMessage` 到 `sendMessage` 的静默回退。
- Rich Message 当前上限包括 32768 个 UTF-8 字符、500 个块、16 层嵌套与 50 个媒体附件。接近限制时应先压缩内容或拆分消息，不把 Telegram 当作完整日志传输通道。
- `sendRichMessageDraft` 只用于流式 rich content；`thinking` block 不能放入最终 `sendRichMessage`。

## 官方文档

- [Bot Features: Rich Messages 与 Regular Messages](https://core.telegram.org/bots/features#advanced-formatting-options)
- [Bot API: InputRichMessage](https://core.telegram.org/bots/api#inputrichmessage)
- [Bot API: sendRichMessage](https://core.telegram.org/bots/api#sendrichmessage)

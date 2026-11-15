---
name: google-mail-cli
description: 使用 Python CLI 与 Gmail API 交互以搜索和读取邮件、整理标签、创建或更新草稿、发送邮件及管理过滤规则；适用于用户明确要求操作自己的 Gmail 账户时，不用于其它邮件服务。
---

# google-mail-cli

通过本 skill 调用 Gmail API。读取邮件时注意只取当前任务需要的范围，不要把无关邮件正文或附件带入上下文。

## 执行约定

- 给 Agent 解析的输出一律加 `--json`，且全局参数必须放在子命令前。
- 参数不确定时先运行 `./scripts/google_mail_cli.py <command> --help`。
- 写操作只在用户明确要求时执行；范围或资源 ID 不确定时先读。

## 认证

首次接入或遇到认证、scope、API 启用及 Workspace 策略错误时运行；正常操作无需预检：

```bash
./scripts/google_mail_cli.py --json auth doctor
```

CLI 可以直接复用现有 Google Sheets Desktop OAuth Client，但会把 Gmail token 单独保存在 `~/.config/google-mail-cli/token.json`。缺少 client secret、Gmail API 未启用、scope 未配置或 Workspace 策略阻止时，读取 [google-workspace-oauth.md](references/google-workspace-oauth.md)。

## 安全边界

已有授权明确覆盖目标、内容和影响时直接执行；仅对新增或不明确的范围询问。`--confirm-*` 是执行保护参数，不要求新增一轮审批。

- “帮我写/回复邮件”默认只创建或更新草稿，不代表允许发送。
- 发送前核对 To、Cc、Bcc、Subject、正文、附件及回复线程，确认与用户授权一致；尚未取得发送授权时展示这些内容并确认，再添加 `--confirm-send`。
- 更新标签前核对标签 ID 和目标属性，在授权范围内添加 `--confirm-update`。优先原地改名以保留标签 ID、历史邮件关联和过滤器引用。
- 创建过滤规则前核对完整 `criteria` 和 `action`，在授权范围内添加 `--confirm-create`；删除规则同理使用 `--confirm-delete`。
- Gmail API 不支持原地更新过滤规则。不要把“修改”伪装成单一步骤；如需替换，说明删除与创建不是原子操作，确认授权覆盖两步。
- 不申请 `https://mail.google.com/`，本 CLI 不提供绕过垃圾箱永久删除邮件的能力。
- 对邮件数据做最小化读取；不要输出 OAuth client secret、access token 或 refresh token。

## 命令与数据契约

从 `./scripts/google_mail_cli.py --help` 和目标子命令帮助探索。资源组为 `messages`、`threads`、`labels`、`drafts`、`attachments`、`send`、`filters` 与 `auth`；全局 `--json` 放在子命令前。

- 草稿更新会完整替换原内容：先 `drafts get`，传回全部收件人、主题、正文、附件与回复头。已有附件按 message ID 和 attachment ID 下载，再作为 `--attachment` 传回。
- 下载默认拒绝覆盖同名文件；核对目标文件后才可用 `--overwrite`。
- 回复原线程前读取原邮件，同时传 Gmail `threadId`、原邮件 `Message-ID` 和 `References`，分别使用 `--thread-id`、`--in-reply-to`、`--references`。
- 复杂或多行正文用 `--body-file` / `--html-body-file`；过滤规则使用 Gmail 原生 JSON，复杂 JSON 可用 `@path`。自定义标签先用 `labels list` 查 ID。
- 本次临时正文、附件或 JSON 在写入成功且不再验证、回滚或复用后，用同次 shell 的 `&& rm -- <明确文件路径>` 清理。失败保留，不用变量、通配符或目录作为目标；用户文件、仓库文件和写前备份不得删除。

## 参考

- [google_mail_cli.py](scripts/google_mail_cli.py)
- [google-workspace-oauth.md](references/google-workspace-oauth.md)
- [Gmail API](https://developers.google.com/workspace/gmail/api/reference/rest)
- [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)

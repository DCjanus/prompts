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

先运行：

```bash
./scripts/google_mail_cli.py --json auth doctor
```

CLI 可以直接复用现有 Google Sheets Desktop OAuth Client，但会把 Gmail token 单独保存在 `~/.config/google-mail-cli/token.json`。缺少 client secret、Gmail API 未启用、scope 未配置或 Workspace 策略阻止时，读取 [google-workspace-oauth.md](references/google-workspace-oauth.md)。

## 安全边界

- “帮我写/回复邮件”默认只创建或更新草稿，不代表允许发送。
- 发送前向用户展示并核对 To、Cc、Bcc、Subject、正文、附件及回复线程；得到明确发送授权后才能在命令中添加 `--confirm-send`。
- 更新标签前展示标签 ID 和目标属性，确认后添加 `--confirm-update`。优先原地改名以保留标签 ID、历史邮件关联和过滤器引用。
- 创建过滤规则前展示完整 `criteria` 和 `action`，确认后添加 `--confirm-create`；删除规则同理使用 `--confirm-delete`。
- Gmail API 不支持原地更新过滤规则。不要把“修改”伪装成单一步骤；如需替换，说明删除与创建不是原子操作并分别确认。
- 不申请 `https://mail.google.com/`，本 CLI 不提供绕过垃圾箱永久删除邮件的能力。
- 对邮件数据做最小化读取；不要输出 OAuth client secret、access token 或 refresh token。

## 常用命令

命令族：

- `auth login|doctor|logout|paths`
- `messages search|get|modify`
- `threads get|modify`
- `labels list|create|update`
- `drafts list|get|create|update`
- `attachments download`
- `send message|draft`
- `filters list|get|create|delete`

搜索并读取一封邮件：

```bash
./scripts/google_mail_cli.py --json messages search \
  --query 'from:sender@example.com newer_than:30d' \
  --max-results 10
./scripts/google_mail_cli.py --json messages get --message-id <message-id>
```

归档并标为已读：

```bash
./scripts/google_mail_cli.py --json messages modify \
  --message-id <message-id> \
  --remove-label-id INBOX \
  --remove-label-id UNREAD
```

创建草稿；复杂或多行正文优先使用临时文件：

```bash
./scripts/google_mail_cli.py --json drafts create \
  --to recipient@example.com \
  --subject '主题' \
  --body-file /tmp/gmail-body.txt \
  --attachment /tmp/report.pdf
```

更新草稿会完整替换原内容。执行前先 `drafts get`，并传回全部收件人、主题、正文、附件和回复头，不能只传局部变化。已有附件需先按草稿 message ID 和 attachment ID 下载，再作为 `--attachment` 传回：

```bash
./scripts/google_mail_cli.py --json attachments download \
  --message-id <message-id> \
  --attachment-id <attachment-id> \
  --output /tmp/original-attachment.pdf
```

下载默认拒绝覆盖本地同名文件；只有核对目标文件后才可添加 `--overwrite`。

回复到原线程时，先读取原邮件，随后同时传入 Gmail `threadId`、原邮件的 `Message-ID` 及 `References`：

```bash
./scripts/google_mail_cli.py --json drafts create \
  --to sender@example.com \
  --subject 'Re: 原主题' \
  --body-file /tmp/gmail-reply.txt \
  --thread-id <thread-id> \
  --in-reply-to '<original-message-id@example.com>' \
  --references '<original-message-id@example.com>'
```

得到明确授权后发送已有草稿：

```bash
./scripts/google_mail_cli.py --json send draft \
  --draft-id <draft-id> \
  --confirm-send
```

直接发送使用临时正文文件时，把成功后的清理放在同一次 shell 调用中：

```bash
./scripts/google_mail_cli.py --json send message \
  --to recipient@example.com \
  --subject '主题' \
  --body-file /tmp/gmail-body.txt \
  --html-body-file /tmp/gmail-body.html \
  --confirm-send \
  && rm -- /tmp/gmail-body.txt /tmp/gmail-body.html
```

过滤规则使用 Gmail API 原生 JSON。自定义标签要先用 `labels list` 查 label ID：

```bash
./scripts/google_mail_cli.py --json filters create \
  --filter-json '{"criteria":{"from":"sender@example.com"},"action":{"addLabelIds":["Label_1"],"removeLabelIds":["INBOX"]}}' \
  --confirm-create
```

复杂 JSON 可用 `@path` 读取。如果正文、附件或 JSON 文件由 Agent 为当前单次操作临时创建，且成功后不再需要验证、回滚或复用，应在同一次 shell 调用中把实际写入命令与 `rm -- <明确路径>` 用 `&&` 串行执行。写入失败时保留文件；不要使用 `;` 无条件删除，也不要用变量、通配符或目录作为清理目标。用户提供的正文、附件、仓库文件和写前备份不得自动删除。

## 参考

- [google_mail_cli.py](scripts/google_mail_cli.py)
- [google-workspace-oauth.md](references/google-workspace-oauth.md)
- [Gmail API](https://developers.google.com/workspace/gmail/api/reference/rest)
- [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)

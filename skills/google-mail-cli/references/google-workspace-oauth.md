# Google Mail CLI 的 Google Workspace OAuth 配置

只在首次配置或认证报错时读取本文。

## 凭据与 token

CLI 按以下顺序寻找 OAuth Desktop client secret：

1. 环境变量 `GOOGLE_WORKSPACE_CLIENT_SECRET` 指向的文件。
2. `$XDG_CONFIG_HOME/google-workspace-cli/client_secret.json`。
3. `$XDG_CONFIG_HOME/google-sheets-cli/client_secret.json`，用于直接复用现有 Sheets CLI 的 OAuth Client。

未设置 `XDG_CONFIG_HOME` 时使用 `~/.config`。Gmail refresh token 始终单独保存在：

```text
$XDG_CONFIG_HOME/google-mail-cli/token.json
```

不要复制 Google Sheets 的 `token.json`；它只包含 Sheets scope。Desktop app 不支持增量授权，Google Mail CLI 必须单独运行一次完整登录。

## Google Cloud 配置

可以继续使用现有 Google Cloud Project 和 Desktop OAuth Client ID：

1. 在同一 Project 中启用 Gmail API。
2. 在 Google Auth Platform 的 Data Access 中加入：
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.settings.basic`
3. 保持 OAuth Client 类型为 `Desktop app`。
4. Workspace 组织如启用了 API Controls，请让管理员允许该 Client ID 使用新增 Gmail scopes。

然后执行：

```bash
cd skills/google-mail-cli
./scripts/google_mail_cli.py auth login
./scripts/google_mail_cli.py --json auth doctor
```

`gmail.modify` 覆盖读取、草稿、发送和邮件标签整理，但不允许绕过垃圾箱永久删除邮件；`gmail.settings.basic` 用于过滤规则。两者都是 Restricted scopes。

## Audience 与验证

- 公司 Google Workspace 组织内自用时，优先把 Audience 配为 `Internal`。
- 个人 Gmail 或跨组织使用通常只能选择 `External`。Publishing status 为 Testing 且请求 Gmail Restricted scopes 时，refresh token 可能只有 7 天有效期。
- 面向其他用户发布、在服务器存储或传输 Gmail 数据时，按 Google OAuth verification、Restricted Scope 和安全评估要求处理。
- 邮件正文进入 Agent 上下文意味着数据会离开 Gmail；操作公司邮箱前确认组织数据政策允许。

## 常见问题

### `access_denied` 或未验证应用提示

确认当前账号属于允许的 Audience/Test users，并确认 consent screen 已声明两个 Gmail scopes。External 应用是否需要发布或验证取决于实际用户范围和数据处理方式。

### 401 / 403 或 `insufficientPermissions`

依次检查：

1. Gmail API 是否已在 OAuth Client 所属 Project 启用。
2. token 是否由 Google Mail CLI 生成并包含两个必要 scope。
3. Workspace API Controls 是否允许该 Client ID。
4. 当前账号是否确实有 Gmail 服务。

scope 变化后执行：

```bash
./scripts/google_mail_cli.py auth logout
./scripts/google_mail_cli.py auth login
```

### 凭据安全

- 不要把 `client_secret.json` 或 `token.json` 提交到仓库、Issue、PR 或聊天。
- Desktop client secret 不是可依赖的强机密；用户授权后的 refresh token 才是关键敏感凭据。
- token 与配置目录由 CLI 分别设为 `0600` 和 `0700`。

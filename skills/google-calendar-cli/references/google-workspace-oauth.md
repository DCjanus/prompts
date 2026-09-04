# Google Calendar CLI 的 Google Workspace OAuth 配置

只在首次配置或认证报错时读取本文。

## 凭据与 token

CLI 按以下顺序寻找 OAuth Desktop client secret：

1. 环境变量 `GOOGLE_WORKSPACE_CLIENT_SECRET` 指向的文件。
2. `$XDG_CONFIG_HOME/google-workspace-cli/client_secret.json`。
3. `$XDG_CONFIG_HOME/google-sheets-cli/client_secret.json`，用于直接复用现有 Sheets CLI 的 OAuth Client。

未设置 `XDG_CONFIG_HOME` 时使用 `~/.config`。Google Calendar refresh token 始终单独保存在：

```text
$XDG_CONFIG_HOME/google-calendar-cli/token.json
```

不要复制 Google Sheets 或 Google Mail 的 `token.json`；它们包含不同 scopes。Desktop app 不支持增量授权，Calendar CLI 必须单独运行一次完整登录。

CLI 创建配置目录时设置权限为 `0700`，并以临时文件加原子替换的方式把 token 保存为 `0600`。环境变量只应保存 client secret 的文件路径，不要直接保存 JSON 内容。

## Google Cloud 配置

可以继续使用现有 Google Cloud Project 和 Desktop OAuth Client ID：

1. 在同一 Project 中启用 Google Calendar API。
2. 在 Google Auth Platform 的 Data Access 中加入：
   - `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/calendar.events.freebusy`
3. 保持 OAuth Client 类型为 `Desktop app`。
4. Workspace 组织如启用了 API Controls，请让管理员允许该 Client ID 使用上述 scopes。

然后执行：

```bash
cd skills/google-calendar-cli
./scripts/google_calendar_cli.py auth login
./scripts/google_calendar_cli.py --json auth doctor
```

本 CLI 不请求完整的 `https://www.googleapis.com/auth/calendar`，因此不能管理 ACL、删除整个日历或清空主日历。

## Audience 与验证

- 公司 Google Workspace 组织内自用时，优先把 Audience 配为 `Internal`。
- 个人 Gmail 或跨组织使用通常只能选择 `External`。Publishing status 为 Testing 且请求用户数据 scopes 时，refresh token 可能只有 7 天有效期。
- 面向其他用户发布、在服务器存储或传输日历数据时，按 Google OAuth verification 和数据安全要求处理。
- 事件标题、描述、参会人和会议链接进入 Agent 上下文意味着数据会离开 Google Calendar；操作公司日历前确认组织数据政策允许。

## 常见问题

### `access_denied` 或未验证应用提示

确认当前账号属于允许的 Audience/Test users，并确认 consent screen 已声明三个 Calendar scopes。External 应用是否需要发布或验证取决于实际用户范围和数据处理方式。

### 401 / 403 或 `insufficientPermissions`

依次检查：

1. Calendar API 是否已在 OAuth Client 所属 Project 启用。
2. token 是否由 Google Calendar CLI 生成并包含三个必要 scope。
3. Workspace API Controls 是否允许该 Client ID。
4. 当前账号是否对目标日历和事件具有相应权限。

scope 变化后执行：

```bash
./scripts/google_calendar_cli.py auth logout
./scripts/google_calendar_cli.py auth login
```

### 本地 logout 与远端撤销

`auth logout` 只删除本机 Calendar token，不会撤销 Google Account 中的应用授权。需要远端撤销时，应在 Google Account 安全设置或 Workspace Admin Console 中操作并确认影响范围；Google 的 OAuth 撤销可能使同一 Cloud Project 下已经授予的其他 scopes 和 token 一并失效。

### 凭据安全

- 不要把 `client_secret.json` 或 `token.json` 提交到仓库、Issue、PR 或聊天。
- Desktop client secret 不是可依赖的强机密；用户授权后的 refresh token 才是关键敏感凭据。
- token 与配置目录由 CLI 分别设为 `0600` 和 `0700`。
- 设备丢失、离职或权限误授时，应尽快从 Google Account 或 Workspace Admin Console 撤销应用访问。

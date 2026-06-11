# Google Workspace OAuth Client 选择指南

本 CLI 使用 Google Sheets API 和本机 OAuth 登录。创建 Google Cloud 凭据时，按下面选择。

## 本地凭据路径

默认凭据目录遵循 XDG：

- OAuth client secret：`$XDG_CONFIG_HOME/google-sheets-cli/client_secret.json`
- OAuth token：`$XDG_CONFIG_HOME/google-sheets-cli/token.json`

若未设置 `XDG_CONFIG_HOME`，默认使用 `~/.config/google-sheets-cli/`。

脚本报认证错误时，先运行：

```bash
cd skills/google-sheets-cli
./scripts/gsheets_cli.py --json auth doctor
```

## 推荐选择

### OAuth consent screen / Audience

优先选择 `Internal`。

适用条件：

- 这个 CLI 只给公司 Google Workspace 域内账号使用。
- Google Cloud project 属于公司 Workspace 组织，Console 里能看到 `Internal` 选项。
- 不希望走面向外部用户的发布/审核流程。

如果 Console 里没有 `Internal`，通常说明当前 Cloud project 不在 Workspace 组织内，或当前账号/项目不满足内部应用条件。此时有两个选择：

- 推荐：用公司 Workspace 账号在公司组织下创建或迁移项目，再选 `Internal`。
- 临时自测：选 `External`，Publishing status 保持 testing，并把自己的公司邮箱加到 Test users。

不要为了内部 CLI 直接发布 External production app，除非团队确实要给组织外用户使用，并准备处理 Google OAuth app verification。

### OAuth Client ID / Application type

必须选择 `Desktop app`。

原因：

- `gsheets_cli.py auth login` 使用本机系统浏览器和 localhost callback。
- Google 对 installed applications 的推荐类型包含 `Desktop app`。
- 下载的 JSON 必须包含 `installed.client_id` 和 `installed.client_secret`；当前 CLI 不读取 Web application 格式的 `web.client_id`。

不要选：

- `Web application`：适合有固定后端 redirect URI 的 Web 服务，不适合这个本机 CLI。
- `Chrome extension` / `Android` / `iOS`：这些类型绑定具体平台，不适合通用命令行工具。
- `Service account`：这不是 OAuth Client ID/Secret 流程；只有在需要无人值守访问且能把表格分享给服务账号，或 Workspace 管理员明确授权 domain-wide delegation 时再单独设计。

### Scopes

当前 CLI 使用：

```text
https://www.googleapis.com/auth/spreadsheets
```

这个 scope 可以读取和修改用户有权限访问的 Google Sheets，满足 `values get/update/batch-update/append/clear`。它是 Google 标记的 Sensitive scope。

暂时不要加 Drive scope：

- 不需要搜索、分享、移动文件时，Sheets scope 已经够用。
- `https://www.googleapis.com/auth/drive` 和 `drive.readonly` 属于 Restricted scope，会引入更高审核和安全评估成本。
- `https://www.googleapis.com/auth/drive.file` 权限更窄，但它主要适合应用自己创建或由用户明确打开给应用的 Drive 文件；本 CLI 当前目标是直接按 spreadsheet ID 操作用户已有表格，所以先不用它。

如果后续要支持“按文件名搜索表格”“创建表格后分享给别人”，再评估新增 Drive scope，并同步更新 CLI、文档和认证提示。

## 创建步骤

1. 用公司 Google Workspace 账号打开 Google Cloud Console。
2. 创建或选择公司组织下的 Google Cloud project。
3. 在 API Library 里启用 Google Sheets API。
4. 配置 Google Auth platform / OAuth consent screen：
   - App name：建议 `Codex Google Sheets CLI` 或团队约定名称。
   - User support email：选择可联系到维护者的公司邮箱。
   - Audience：公司内部使用选 `Internal`；无法选 Internal 时，临时自测选 `External` + Testing。
   - Contact email：填维护者或团队邮箱。
5. 在 Data Access / Scopes 里添加：
   - `https://www.googleapis.com/auth/spreadsheets`
6. 创建 OAuth Client：
   - Application type：`Desktop app`
   - Name：建议 `Codex Google Sheets CLI Desktop`
7. 下载 OAuth client JSON。
8. 保存到 XDG 配置目录：

```bash
mkdir -p ~/.config/google-sheets-cli
chmod 700 ~/.config/google-sheets-cli
cp /path/to/downloaded-client-secret.json ~/.config/google-sheets-cli/client_secret.json
chmod 600 ~/.config/google-sheets-cli/client_secret.json
```

如果设置了 `XDG_CONFIG_HOME`，保存到：

```text
$XDG_CONFIG_HOME/google-sheets-cli/client_secret.json
```

9. 登录并生成本地 token：

```bash
cd skills/google-sheets-cli
./scripts/gsheets_cli.py auth login
```

10. 检查状态：

```bash
./scripts/gsheets_cli.py --json auth doctor
```

## 常见错误处理

### 缺少 client secret

症状：脚本提示缺少 `client_secret.json`。

处理：

1. 按本文创建 `Desktop app` OAuth Client。
2. 下载 OAuth client JSON。
3. 保存到脚本提示的 `client_secret.json` 路径。
4. 重新运行：

```bash
./scripts/gsheets_cli.py auth login
```

### 缺少 token 或 token 无效

症状：脚本提示缺少 `token.json`、token 无效或刷新失败。

处理：

```bash
./scripts/gsheets_cli.py auth login
```

如果仍失败，先删除本地 token 再重新登录：

```bash
./scripts/gsheets_cli.py auth logout
./scripts/gsheets_cli.py auth login
```

### Workspace 阻止访问

症状：登录或 API 调用返回 401 / 403，且错误看起来与公司安全策略、OAuth app access 或 insufficient permissions 相关。

处理：

1. 确认当前 Google 账号有目标 Spreadsheet 的访问权限。
2. 把 OAuth Client ID、App name 和请求 scope 发给 Workspace 管理员。
3. 让管理员按下方“Workspace 管理员可能需要配置”处理。

## Workspace 管理员可能需要配置

如果登录或 API 调用时报权限/策略错误，让 Workspace 管理员检查 Admin Console：

- 路径：Security -> Access and data control -> API controls -> Manage App Access。
- 用 OAuth Client ID 搜索这个 app。
- 对公司需要的组织单元授予访问。
- 推荐只授予需要的数据范围；如果公司策略要求，也可以把 app 标记为 Trusted。

给管理员的信息至少包括：

- App name
- OAuth Client ID
- 请求 scope：`https://www.googleapis.com/auth/spreadsheets`
- 用途：本机 CLI 读取和更新用户有权限访问的 Google Sheets
- 数据落点：OAuth client secret 和 refresh token 仅保存在用户本机 XDG 配置目录

## 安全约束

- 不要把 `client_secret.json` 或 `token.json` 提交进仓库。
- 不要把 token 发给 Agent、issue、PR 或聊天窗口。
- Desktop app 的 client secret 不能当作强机密；真正敏感的是用户授权后的 refresh token。
- 离职、设备丢失或权限误授时，在 Google Account 安全设置或 Workspace Admin Console 撤销该 app 的访问。

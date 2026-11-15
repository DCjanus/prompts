---
name: google-calendar-cli
description: 使用 Python CLI 与 Google Calendar API 交互以查看日历和事件、查询空闲忙碌时间、创建、更新或删除事件；适用于用户明确要求操作自己的 Google 日历时，不用于其它日历服务。
---

# google-calendar-cli

通过本 skill 调用 Google Calendar API。读取日程时只取当前任务需要的日历与时间范围，不要把无关事件详情、参会人或会议链接带入上下文。

## 执行约定

- 给 Agent 解析的输出一律加 `--json`，且全局参数必须放在子命令前。
- 参数不确定时先运行 `./scripts/google_calendar_cli.py <command> --help`。
- 写操作只在用户明确要求时执行；范围、日历 ID 或事件 ID 不确定时先读。

## 认证

首次接入或遇到认证、scope、API 启用及 Workspace 策略错误时运行；正常操作无需预检：

```bash
./scripts/google_calendar_cli.py --json auth doctor
```

CLI 可以复用现有 Google Workspace / Sheets Desktop OAuth Client，但 Calendar token 始终单独保存在 `$XDG_CONFIG_HOME/google-calendar-cli/token.json`。缺少 client secret、Calendar API 未启用、scope 未配置或 Workspace 策略阻止时，读取 [google-workspace-oauth.md](references/google-workspace-oauth.md)。

## 安全边界

已有授权明确覆盖目标、内容和影响时直接执行；仅对新增或不明确的范围询问。`--confirm-*` 是执行保护参数，不要求新增一轮审批。

- 创建、更新、删除事件前核对目标 calendar ID、事件 ID（如有）、主要字段、参会人、重复规则和通知范围；授权不足时展示待确认内容，获得授权后分别添加 `--confirm-create`、`--confirm-update`、`--confirm-delete`。
- `--send-updates` 默认 `none`，不会主动发参会人邮件。只有用户明确要求通知时才使用 `all` 或 `externalOnly`；即使选择 `none`，Google 仍可能在部分场景发送必要通知。
- 修改或删除重复日程前，先区分事件系列 ID 和具体 instance ID。修改单个实例会创建 exception；不要用逐实例修改代替整个系列更新。
- `events patch` 是局部更新，但 JSON 数组字段会整体替换。更新 attendees、recurrence、reminders 等数组前先 `events get` 并保留需要的元素。
- 写入成功后，用响应中的 event ID 再执行一次 `events get` 回读；删除后记录 API 成功结果和准确 event ID。
- 不申请完整 `calendar` scope，不提供修改 ACL、共享设置、清空主日历或删除整个日历的能力。
- 不要输出 OAuth client secret、access token、refresh token，或把这些文件带入 Agent 上下文。

## 命令与时间语义

从 `./scripts/google_calendar_cli.py --help` 和目标子命令帮助探索。资源组为 `calendars`、`events`、`freebusy` 与 `auth`；全局 `--json` 放在子命令前。

- 查询限定日历和时间范围；重复日程实例使用 `events instances`。
- `start.dateTime` / `end.dateTime` 使用 RFC3339 时区偏移；不带偏移时必须在对应对象提供 IANA `timeZone`。全天事件用 `date`，且 `end.date` 不包含在事件内。
- 复杂事件用 `--event-json @<path>` 传入。更新前读取事件，再传局部 patch；数组替换规则见上文。
- 仅当 JSON 文件为本次临时创建、写入成功且不再验证或回滚时，用同次 shell 的 `&& rm -- <明确文件路径>` 清理；失败保留，不用变量、通配符或目录作为目标，不删除用户文件。

## 权限范围

CLI 只请求：

- `calendar.calendarlist.readonly`：读取用户已订阅的日历列表和元数据。
- `calendar.events`：读取和管理用户有权访问的事件。
- `calendar.events.freebusy`：读取用户有权查询的忙碌时间。

这些权限不包含修改日历共享 ACL、删除整个日历或清空主日历。

## 参考

- [google_calendar_cli.py](scripts/google_calendar_cli.py)
- [google-workspace-oauth.md](references/google-workspace-oauth.md)
- [Google Calendar API](https://developers.google.com/workspace/calendar/api/v3/reference)
- [Google Calendar API scopes](https://developers.google.com/workspace/calendar/api/auth)
- [Recurring events](https://developers.google.com/workspace/calendar/api/guides/recurringevents)

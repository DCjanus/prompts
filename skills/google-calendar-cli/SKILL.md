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

先运行：

```bash
./scripts/google_calendar_cli.py --json auth doctor
```

CLI 可以复用现有 Google Workspace / Sheets Desktop OAuth Client，但 Calendar token 始终单独保存在 `$XDG_CONFIG_HOME/google-calendar-cli/token.json`。缺少 client secret、Calendar API 未启用、scope 未配置或 Workspace 策略阻止时，读取 [google-workspace-oauth.md](references/google-workspace-oauth.md)。

## 安全边界

- 创建、更新、删除事件前，先展示目标 calendar ID、事件 ID（如有）、主要字段、参会人、重复规则和通知范围；得到明确授权后分别添加 `--confirm-create`、`--confirm-update`、`--confirm-delete`。
- `--send-updates` 默认 `none`，不会主动发参会人邮件。只有用户明确要求通知时才使用 `all` 或 `externalOnly`；即使选择 `none`，Google 仍可能在部分场景发送必要通知。
- 修改或删除重复日程前，先区分事件系列 ID 和具体 instance ID。修改单个实例会创建 exception；不要用逐实例修改代替整个系列更新。
- `events patch` 是局部更新，但 JSON 数组字段会整体替换。更新 attendees、recurrence、reminders 等数组前先 `events get` 并保留需要的元素。
- 写入成功后，用响应中的 event ID 再执行一次 `events get` 回读；删除后记录 API 成功结果和准确 event ID。
- 不申请完整 `calendar` scope，不提供修改 ACL、共享设置、清空主日历或删除整个日历的能力。
- 不要输出 OAuth client secret、access token、refresh token，或把这些文件带入 Agent 上下文。

## 常用命令

命令族：

- `auth login|doctor|logout|paths`
- `calendars list|get`
- `events list|get|instances|create|patch|delete`
- `freebusy query`

列出日历与事件：

```bash
./scripts/google_calendar_cli.py --json calendars list
./scripts/google_calendar_cli.py --json events list \
  --calendar-id primary \
  --time-min '2026-09-04T00:00:00+08:00' \
  --time-max '2026-09-11T00:00:00+08:00' \
  --query '项目同步'
```

查询多人空闲时间：

```bash
./scripts/google_calendar_cli.py --json freebusy query \
  --calendar-id 'first@example.com' \
  --calendar-id 'second@example.com' \
  --time-min '2026-09-04T09:00:00+08:00' \
  --time-max '2026-09-04T18:00:00+08:00' \
  --time-zone 'Asia/Shanghai'
```

创建普通事件。`start.dateTime` / `end.dateTime` 应包含 RFC3339 时区偏移；不带偏移时必须在对应对象内提供 IANA `timeZone`。全天事件改用 `date`，且 `end.date` 是不包含在事件内的结束日期：

```bash
./scripts/google_calendar_cli.py --json events create \
  --calendar-id primary \
  --event-json '{"summary":"项目同步","start":{"dateTime":"2026-09-05T10:00:00+08:00"},"end":{"dateTime":"2026-09-05T10:30:00+08:00"}}' \
  --confirm-create
```

带参会人与重复规则的复杂事件优先使用临时 JSON 文件：

```bash
./scripts/google_calendar_cli.py --json events create \
  --calendar-id primary \
  --event-json @/tmp/calendar-event.json \
  --send-updates all \
  --confirm-create \
  && rm -- /tmp/calendar-event.json
```

只有当 JSON 文件由 Agent 为本次操作临时创建、写入成功后不再需要验证或回滚时，才能按上例用 `&& rm -- <明确路径>` 清理。失败时保留文件；不要使用 `;`、变量、通配符或目录作为清理目标，也不要删除用户提供的文件。

更新前先读取事件，再传递局部 patch：

```bash
./scripts/google_calendar_cli.py --json events get \
  --calendar-id primary --event-id <event-id>
./scripts/google_calendar_cli.py --json events patch \
  --calendar-id primary \
  --event-id <event-id> \
  --event-json '{"summary":"新的标题"}' \
  --confirm-update
```

查看重复事件实例：

```bash
./scripts/google_calendar_cli.py --json events instances \
  --calendar-id primary \
  --event-id <recurring-event-id> \
  --time-min '2026-09-01T00:00:00+08:00' \
  --time-max '2026-10-01T00:00:00+08:00'
```

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

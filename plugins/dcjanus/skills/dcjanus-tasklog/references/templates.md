# 模板与周期事项

创建或调整普通模板、周期 Issue、每周提醒时读取。普通 Issue、Project、Document 和周期 Issue 都使用 Linear 原生 Template；CLI 直接映射 `template list/get/create/update/delete`。

## 查找和修改

周期事项先用 `template list --team KEY --type recurringIssue` 查重，不只搜索已生成的 Issue。Issue 的 `recurringIssueTemplate` 提供所属模板 ID，用 `template get ID` 读取规则。

`templateData` 是模板目标实体的数据；模板本身的 `name/description` 与 `templateData.title/description` 各有用途，不会联动修改。通过 `--template-data-file` 提供完整 JSON object，具体字段结构交给 Linear 校验。

更新会完整替换 `templateData`，不做合并。先回读现有数据并保留未修改字段，尤其是周期模板的起始日期、`schedule.lastRecurredAt` 和正文富文本 `descriptionData`。若改用 Markdown `description` 替换正文，应移除旧 `descriptionData`，避免同时提交冲突的正文表示。

## 创建周期模板

原生周期模板的 `type` 为 `recurringIssue`，规则在 `templateData.schedule`。例如每周一复盘（将日期和各 UUID 替换为已核对的值）：

```json
{
  "title": "每周复盘",
  "description": "处理上一自然周的问题并记录遗留项。",
  "teamId": "TEAM_UUID",
  "stateId": "STATE_UUID",
  "assigneeId": "USER_UUID",
  "schedule": {"startAt": "2026-11-02", "interval": 1, "type": "weeks"}
}
```

```bash
./scripts/linear_cli.py template create --team KEY --name '每周复盘' \
  --type recurringIssue --template-data-file /tmp/weekly-template.json
```

确认预览、获得授权后加 `--yes`。`schedule.type` 使用 `days`、`weeks`、`months`、`years`，`interval` 是重复间隔；`startAt` 是团队时区下的首次到期日，周几由日期决定。

## 生成与验收边界

创建周期模板后，Linear 自动生成首期 Issue，不要再手工创建首期。后续实例由 Linear 按到期日生成，无需本机定时任务；模板变化不修改已生成的实例。删除周期模板会停止后续生成，已有 Issue 保留。

GraphQL 只将 `templateData` 声明为 JSON，没有强类型约束内部周期结构。修改现有计划以实际回读数据为基准。模板写入回读成功与下一期实际生成是两个结果，报告时区分；需要验收后者时核对真实实例。[官方周期事项说明](https://linear.app/docs/creating-issues#create-recurring-issues)。

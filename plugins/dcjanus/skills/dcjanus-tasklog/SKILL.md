---
name: dcjanus-tasklog
description: 查询或管理 DCjanus 的 Linear 事项、长期文档、模板（含周期事项）、视图或团队配置，以及按个人任务模型整理目标、进展和关联时使用。
---

# DCjanus Tasklog

把 Linear 作为个人目标、注意力与长期参考资料的索引。使用 [linear_cli.py](scripts/linear_cli.py) 操作 Linear 原生资源；一个 Issue 承载可独立判断结果的目标，长期资料放 Document。

## 共同约定

- 查询、查重和草拟直接执行；外部写入需要用户授权。写前读取当前对象、核对目标并展示具体预览；已有授权无需重复确认。创建前在目标容器查重，不能只比较标题。
- 写操作默认预览，获授权后加 `--yes`。写后核对实际改变的字段；多步操作分别报告结果。响应不明或回读失败时先查实际状态，不把请求失败解释成未写入，也不盲目重试。
- 团队以显式 `--team` 或已配置的默认值为准；都没有时先确定目标，不猜业务团队。不要输出凭据或从浏览器提取登录凭据。
- 个人 Linear 与外部交付物默认单向关联：在个人记录中引用外部证据；除非用户明确要求公开关联，不在公开 PR/MR、Issue、commit 或评论中写入个人 Linear 标识或 URL。

## 从当前需求进入

只读当前场景需要的文档；简单查询无需预先加载其它 reference。

| 当前需求 | 入口与按需阅读 |
| --- | --- |
| 查找或查看 Issue、进展、关联 | `issue search/get/list`、`issue comment`、`issue relation`；用下方查询约定与 CLI 帮助 |
| 创建、编辑、拆分、关联、收尾 Issue，或记录进展 | 先读 [事项与进展](references/issues.md) |
| 保存、搜索或更新长期资料 | 读 [长期文档](references/documents.md)，使用 `document` |
| 创建或调整模板、周期事项、每周提醒 | 读 [模板与周期事项](references/templates.md)，使用 `template` |
| 查看或调整视图、标签、工作流状态、团队自动化 | 读 [视图与团队设置](references/settings.md) |
| 首次接入、认证失败、配置默认团队 | 读 [认证与本地配置](references/authentication.md) |
| CLI 未覆盖能力，需要核对或扩展 API 支持 | 读 [API 能力与扩展](references/api.md) |

## 查询与命令发现

入口是本 skill 目录的 `scripts/linear_cli.py`。从任意工作目录都可用其绝对路径执行；以下命令相对本 skill 目录：

```bash
./scripts/linear_cli.py --help
./scripts/linear_cli.py issue --help
./scripts/linear_cli.py issue create --help
```

按标题、描述或评论查找事项用 `issue search`，不先导出全部 Issue 再过滤。需要历史事项时包含归档；分页结果尚有下一页时继续翻页，不用首页下全量结论。批量读取只需部分字段时用 `issue list --fields`。参数、默认值和互斥规则以对应子命令帮助为准。

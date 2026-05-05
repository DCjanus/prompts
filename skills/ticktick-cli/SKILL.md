---
name: ticktick-cli
description: 使用 Python CLI 与 Dida365 Open API 交互以管理滴答清单任务/项目，适用于需要通过脚本或命令行调用滴答清单接口的场景（如项目/任务的查询、创建、更新、完成、删除）。
---

以下命令均以当前 `SKILL.md` 所在目录为 workdir：

```bash
cd skills/ticktick-cli
./scripts/ticktick_cli.py --json project list
```

不要用 `uv run python` 或 `python` 直接调用脚本。

## 使用约定

- 输出给 Agent 解析时，在脚本后、子命令前加 `--json`。
- 冷门参数先查 `./scripts/ticktick_cli.py <command> --help`，再查官方 OpenAPI 文档。
- 删除项目/任务前要谨慎确认，`delete` 是真实删除操作。

## 认证

- 先用 `./scripts/ticktick_cli.py --json auth doctor` 检查当前 token、区域和 API base URL。
- 没有 token 时，运行 `./scripts/ticktick_cli.py auth login`；CLI 会输出官方授权链接，默认不自动打开浏览器，并默认等待 5 分钟完成登录。需要自动打开时显式加 `--open`。
- 本地 OAuth token 默认保存到 `~/.config/ticktick-cli/token.json`；后续命令会从 token 元数据推断区域和 API base URL，可用 `TICKTICK_TOKEN_FILE` 覆盖。
- 登录默认使用中国区 `dida365`；国际版用 `./scripts/ticktick_cli.py auth login --region ticktick`。
- 远程 SSH 登录时，浏览器 callback 需要能访问运行 CLI 的机器；必要时在目标机器本地登录，或自行做端口转发。

## 常用命令

- `auth login|doctor|logout`
- `project list|get|data|create|update|delete`
- `task get|create|update|complete|delete`

创建或更新 checklist 子任务时，简单标题可重复传 `--item`；复杂字段用 `--item-json` 传 JSON 数组或 `@path` 文件。

## 概念

- Project：任务容器，支持 list / kanban / timeline 等视图。
- Task：隶属于 Project，可包含时间、提醒、优先级、重复规则、标签与子任务。
- ChecklistItem：Task 下的子任务项。
- Column：看板列，仅在 kanban 场景常用。
- ProjectData：项目详情聚合，包含项目、未完成任务和列信息。

## 参考

- [ticktick_cli.py](scripts/ticktick_cli.py)
- [滴答清单 OpenAPI](https://developer.dida365.com/docs/index.html#/openapi)
- [TickTick OpenAPI](https://developer.ticktick.com/docs/index.html#/openapi)

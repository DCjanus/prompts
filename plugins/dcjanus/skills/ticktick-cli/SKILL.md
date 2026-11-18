---
name: ticktick-cli
description: 管理滴答清单（Dida365）或国际版 TickTick 的任务、项目、习惯打卡与专注记录。
---

# ticktick-cli

通过本 skill 调用滴答清单 / TickTick Open API。默认中国区 Dida365；国际版只在登录时显式选择。

## 执行约定

- 给 Agent 解析的输出一律加 `--json`，并且全局参数必须放在子命令前。
- 删除项目或任务前先确认用户意图；`delete` 会真实删除远端数据。
- 参数不确定时先查 `./scripts/ticktick_cli.py <command> --help`。

## 认证

默认假设本地 token 有效，直接执行用户请求的操作；不要在每次操作前先跑 `auth doctor`。

只有命令失败且报错指向认证、token、权限、区域或 API base URL 问题时，再诊断当前本地 token：

```bash
./scripts/ticktick_cli.py --json auth doctor
```

确实没有 token、token 失效或用户要求重新登录时再登录：

```bash
./scripts/ticktick_cli.py auth login
```

- 国际版登录用 `./scripts/ticktick_cli.py auth login --region ticktick`。
- 默认只输出授权链接，不自动打开浏览器；需要自动打开时加 `--open`。
- 登录会启动 localhost callback，默认等待 5 分钟；看到链接后应尽快完成授权。
- token 默认保存到 `~/.config/ticktick-cli/token.json`，可用 `TICKTICK_TOKEN_FILE` 覆盖。
- 后续命令只读本地 token 文件，并从 token 元数据推断区域和 API base URL。
- 远程 SSH 场景下，浏览器 callback 必须能访问运行 CLI 的机器；必要时在目标机器本地登录，或自行做端口转发。

## 日常操作

从 `./scripts/ticktick_cli.py --help` 选择 `project`、`task`、`habit` 或 `focus`。项目聚合详情用 `project data`，包含项目、未完成任务和看板列；精确读取一条任务时，向 `task get` 同时提供 project ID 和 task ID。

创建或更新 checklist 子任务：

- 简单标题：重复传 `--item`。
- 复杂字段：用 `--item-json` 传 JSON 数组，或传 `@path` 读取文件。
- 任务标签：创建/更新任务时重复传 `--tag`。
- 复杂 habit payload：用 `--payload-json` 传 JSON 对象，或传 `@path` 读取文件。

如果 JSON 文件由 Agent 为当前单次写操作临时创建，且成功后不再复用，在同一次 shell
调用中把写操作与 `rm -- <明确路径>` 用 `&&` 串行执行。写操作失败时保留文件，不要
使用 `;` 无条件删除，也不要用变量、通配符或目录作为清理目标。用户提供的 JSON 和
后续更新或校验仍需复用的文件不得自动清理。例如：

```bash
./scripts/ticktick_cli.py --json task create \
  --project-id <project-id> \
  --title "任务标题" \
  --item-json @/tmp/ticktick-items.json \
  && rm -- /tmp/ticktick-items.json
```

## 参考

- [ticktick_cli.py](scripts/ticktick_cli.py)
- [滴答清单 OpenAPI](https://developer.dida365.com/docs/index.html#/openapi)

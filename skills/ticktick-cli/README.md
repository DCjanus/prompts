# ticktick-cli 记录

## 背景
- 目标：通过 Python CLI（供 Codex 调用）管理滴答清单账号。
- 技术栈：uv script + Typer + Pydantic + httpx。
- API 文档：[滴答清单 OpenAPI](https://developer.dida365.com/docs/index.html#/openapi)（更新较少，需自行验证）。
- CLI 入口：[ticktick_cli.py](scripts/ticktick_cli.py)。

## 认证现状
- CLI 已可正常调用（依赖可用的 OAuth Token）。
- 仍需：在开发者平台注册 OAuth app，并部署服务端逻辑获取 OAuth Token（Worker 路径见下）。

## CLI 进度
- 已支持项目/任务的增删改查与完成。
- 已支持更新 Checklist 子任务，推荐使用 JSON 方式：`--item-json`（可传 JSON 字符串或 `@path` 文件）。
- 典型场景：按剧集/章节拆分追踪，每集一个子任务并写入 `startDate`。

## OAuth Worker 运行所需信息
- `TICKTICK_CLIENT_ID`：在 [Dida365 Developer Center](https://developer.dida365.com/manage) 创建 OAuth 应用后获得。
- `TICKTICK_CLIENT_SECRET`：同上，用于 server-to-server 交换 token。
- `TICKTICK_REDIRECT_URI`：在开发者后台配置的回调地址，需与 Worker 的 `/callback` 地址一致。

## 计划
- 使用 Cloudflare Worker 部署 OAuth 服务端逻辑，预计单文件 JS。
- Worker 脚本占位文件：[ticktick-oauth-worker.js](skills/ticktick-cli/assets/ticktick-oauth-worker.js)。
- 部署方式倾向手动，避免使用官方工具（如 wrangler）引入过多文件。
- OAuth app 部署完成后在本地跑通流程，再回头优化 [SKILL.md](SKILL.md) 并用简单用例验证 CLI 可用性。

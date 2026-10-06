# 通知实现与维护

运行时行为由 [notify.py](../scripts/notify.py) 及其测试定义；修改排版或会话入口时保留以下设计约束。

- 标题、结论、待处理项和 footer 由脚本生成，输入字段始终为纯文本。
- 会话入口使用独立的两行文本和完整 HTTPS URL，前面保留空行；不要换成隐藏目标的链接文字或按钮，以免触发 Telegram 的额外确认。
- 使用合法的 `CODEX_SESSION_ID` 返回当前 agent tree 的根任务；缺失或无效时省略，不回退到 subagent 的 `CODEX_THREAD_ID`。
- 用 `--json preview` 检查 `rich_message`。字段定义参考 Telegram 官方 [Rich Messages](https://core.telegram.org/bots/features#rich-messages) 和 [Bot API](https://core.telegram.org/bots/api#sendrichmessage)。

## 深链 bridge

配套 Worker 位于 [worker](../worker)，生产地址为 `https://codex-thread-bridge.dcjanus.workers.dev`。它只接受 `/codex/open-thread/<UUID>`，并直接返回指向对应 `codex://threads/<UUID>` 的 `302`；无效路径返回 `404`，因此不能被用作任意 URL 的开放重定向器。重定向响应允许浏览器缓存 1 天，以减少同一链接重复点击产生的 Worker 请求。Cloudflare Static Assets 的重定向规则不允许 `codex://` 目标，因此该 bridge 必须执行一段最小 Worker 脚本；每个未命中浏览器缓存的点击会产生一次 Worker 请求。

Worker 使用独立 pnpm package，需要 Node.js 22+。`cloudflare.config.ts` 管理 Worker，`wrangler.config.ts` 保留现有 bundler。以下命令在本 skill 目录执行：

```bash
pnpm --dir worker install --frozen-lockfile
pnpm --dir worker test
pnpm --dir worker build
pnpm --dir worker exec cf deploy --dry-run
pnpm --dir worker deploy
```

首次部署前执行 `pnpm --dir worker exec cf auth login`；cf 不复用 Wrangler 登录。CI 继续使用 `CLOUDFLARE_API_TOKEN` 和 `CLOUDFLARE_ACCOUNT_ID`。本地开发用 `pnpm --dir worker dev`，实时日志仍可执行 `pnpm --dir worker exec wrangler tail codex-thread-bridge`。

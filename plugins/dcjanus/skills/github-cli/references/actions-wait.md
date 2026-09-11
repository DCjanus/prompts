# GitHub Actions 等待

当 Agent 需要阻塞等待 GitHub Actions，并希望获得低噪声输出、统一超时或稳定退出码时，使用 `scripts/github_actions_wait.py`。脚本只读取 GitHub 状态，不会取消、重跑 workflow，也不会修改 PR 或 check。

## 选择原则

- 人工临时观察完整 step 进度：使用 `gh run watch`；需要失败退出时加 `--exit-status`。
- 人工观察 PR checks：可使用 `gh pr checks --watch --fail-fast`。
- Agent 阻塞等待、单 job、按名称筛选、超时控制、NDJSON 或只在状态变化时输出：使用本脚本。

脚本轮询 REST API，不是真正的 webhook 事件流。两次轮询之间出现又消失的状态可能不可见，事件时间表示脚本观察到状态的时间，而不是 GitHub 服务端状态产生的时间。

## 命令接口

从本 skill 目录运行：

```bash
./scripts/github_actions_wait.py --repo owner/repo --run 123
./scripts/github_actions_wait.py --repo owner/repo --job 456
./scripts/github_actions_wait.py --repo owner/repo --pr 789
./scripts/github_actions_wait.py --repo owner/repo --pr 789 --fail-fast
./scripts/github_actions_wait.py --repo owner/repo --pr 789 --check 'test-*'
./scripts/github_actions_wait.py --repo owner/repo --run 123 --job-name 'test-*'
./scripts/github_actions_wait.py --repo owner/repo --run 123 --interval 60 --timeout 30m --format ndjson
```

目标参数 `--run`、`--job` 和 `--pr` 三选一。`--job-name` 只能和 `--run` 一起使用，用于等待该 run 中匹配的 jobs；`--check` 只能和 `--pr` 一起使用。筛选参数可重复，采用区分大小写的 shell glob（例如 `test-*`）；任一 pattern 命中即保留。没有匹配项时保持 pending，直到匹配项出现或超时。

`--fail-fast` 只用于 PR：任一匹配 check 失败或取消时立即退出，不等待其它 check。默认轮询间隔为 30 秒，默认超时为 30 分钟；时长接受秒数或 `s`、`m`、`h` 后缀。

## 状态模型

脚本把 GitHub 的 run、job、check run 和 commit status 归一成四种状态：

| 状态 | 含义 |
| --- | --- |
| `pending` | 尚未出现匹配项，或至少一项 queued/in progress |
| `success` | 全部匹配项成功；`neutral` 和 `skipped` 也视为成功完成 |
| `failure` | 至少一项为 failure、timed out、action required、startup failure 或 stale |
| `cancelled` | 至少一项取消，且没有失败项 |

PR 模式同时读取 head SHA 的 check runs 和 commit statuses。未知的新状态不会被误报为成功，而会保持 pending 直至超时。

## 输出契约

默认 `human` 输出每行一个观察事件，不使用动态终端界面。`ndjson` 每行一个 JSON object，稳定字段为：

- `event`：`state`、`retry`、`timeout`、`interrupted` 或 `error`；
- `time`：UTC ISO 8601 观察时间；
- `target`：`run`、`job` 或 `pr`；
- `id`：目标 ID 或 PR number；
- `state`：状态事件的归一化状态；
- `status`、`conclusion`、`name`、`url`、`items`、`sha`：目标适用时出现的详情。

第一次读取会输出 `state`；之后只有完整状态快照变化时才再次输出。连续相同的临时 API 错误只输出一次 `retry`。HTTP 429 或临时服务错误会遵循数值形式的 `Retry-After`，否则按 `--interval` 重试。

## 退出码

| 退出码 | 结果 |
| --- | --- |
| `0` | 成功 |
| `1` | 失败 |
| `2` | 命令行参数错误 |
| `3` | 取消 |
| `4` | 超时 |
| `5` | 收到 Ctrl-C 或中断信号 |
| `6` | 鉴权、配置或不可重试的 API 错误 |

## 认证、host 与条件请求

仓库接受 `OWNER/REPO`、`HOST/OWNER/REPO` 或完整 repository URL。未显式给出 host 时遵循 `GH_HOST`，否则默认 `github.com`。GitHub.com 使用 `https://api.github.com`；GitHub Enterprise Server 使用 `https://HOST/api/v3`。

脚本只直接读取一个认证环境变量 `GH_TOKEN`，适用于 GitHub.com 和 Enterprise host；没有时执行 `gh auth token --hostname HOST`，因此自然遵循 `GH_CONFIG_DIR` 和该 host 当前选择的账号。GitHub Actions 中需要显式映射，例如 `GH_TOKEN: ${{ github.token }}`。脚本不直接读取名称更宽泛的 `GITHUB_TOKEN` 或 Enterprise 专用变量，避免同一环境中多个账号来源不明确。错误与 NDJSON 不包含响应正文或 token。

每个成功 GET 的响应若包含 ETag，后续请求会发送 `If-None-Match`；收到 304 时复用缓存。端点不返回 ETag 时会安全退回普通轮询。

官方接口依据：

- [Get a workflow run](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run)
- [Get a job for a workflow run](https://docs.github.com/en/rest/actions/workflow-jobs#get-a-job-for-a-workflow-run)
- [List check runs for a Git reference](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference)
- [Get the combined status for a specific reference](https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference)
- [REST API conditional requests](https://docs.github.com/en/rest/guides/best-practices-for-using-the-rest-api#use-conditional-requests-if-appropriate)
- [GitHub Enterprise Server API version](https://docs.github.com/en/enterprise-server/rest/about-the-rest-api/api-versions)

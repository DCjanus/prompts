---
name: codex-thread-namer
description: 为当前 Codex thread 设置名称；仅当用户手动调用或明确要求命名、重命名、整理当前 Codex 会话标题时使用，永远不要自动调用。
---

# Codex Thread Namer

用户点名本 skill（包括无附加文字的调用）或明确要求给当前会话命名，即可设置标题。结合任务和仓库上下文确定项目名，使用 `Project: 标题`，目标约 20–30 个可见字符，最多 36 个。

默认直接运行：

```bash
./scripts/set_current_thread_name.py "Project: 标题"
```

只有用户要求候选名时，才给出 3 个按推荐顺序排列的编号选项，不另标推荐项。请用户选择 1/2/3；说明只回复确认时采用第 1 项。收到选择后调用同一脚本。

脚本依赖当前环境的 `CODEX_THREAD_ID`，缺失时报告无法定位会话。

## Known Limitation

- Codex Desktop GUI 可能不会实时刷新外部 app-server 写入的 thread 名称；设置成功后名称已持久化，但可能需要重启 Desktop 才显示新标题。需要排查或说明背景时，读取 [codex-desktop-thread-name-refresh.md](references/codex-desktop-thread-name-refresh.md)。

# Codex Desktop Thread Name Refresh

## 现象

通过 `codex app-server --listen stdio://` 调用 `thread/name/set` 可以成功设置当前 thread 名称，且名称会持久化。Codex Desktop 重启后能显示新标题。

但 Codex Desktop 已打开的 GUI 可能不会实时刷新标题，仍显示旧名称直到重启。

## 本地源码结论

Codex CLI/app-server 的 `thread/name/set` 会发送 `thread/name/updated` 通知。该通知会广播给同一个 app-server 进程内已经初始化的连接。

Codex Desktop 运行自己的 bundled app-server 进程，并通过私有 stdio pipe 连接。外部脚本启动的是另一个 app-server 进程，因此外部脚本触发的通知不会到达 Desktop GUI。

这说明当前限制更像是 Desktop 对跨 app-server 进程写入缺少实时刷新或失效通知，而不是 `thread/name/set` 完全没有发送更新事件。

## 相关 Issue

- [#24202 Expose supported hook to update Codex Desktop thread titles live](https://github.com/openai/codex/issues/24202)
- [#21743 Codex Desktop open thread view does not refresh after another app-server client appends a turn](https://github.com/openai/codex/issues/21743)
- [#11907 Codex App: add manual refresh button (or auto-sync) for archived and cross-surface conversations](https://github.com/openai/codex/issues/11907)
- [#13470 Keep thread name in sync across CLI and app](https://github.com/openai/codex/issues/13470)

## 当前实践

调用脚本后，如果输出成功但 Desktop 标题没有变化，先按“已持久化但 GUI 未刷新”理解。需要确认时，可以重启 Codex Desktop，或用 app-server 的 read 类接口读取 thread 元数据。

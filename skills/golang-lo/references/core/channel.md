# Core / Channel

- 分发：`ChannelDispatcher(src, workers, cap, strategy)` 支持 RoundRobin/Random/WeightedRandom/First/Least/Most。
- 转换：`SliceToChannel`（生成只读 chan）；`ChannelToSlice`（收集）；`Generator`（函数产出到 chan）。
- 广播：`Broadcast` 将上游广播到下游多个通道。
- 批量：`BufferWithContext` / `BufferWithTimeout` 按数量或超时批量读。

## 示例
```go
children := lo.ChannelDispatcher(src, 5, 16, lo.DispatchingStrategyRoundRobin[int])
vals := lo.ChannelToSlice(lo.SliceToChannel(2, []int{1,2,3}))
items, n, _, ok := lo.BufferWithTimeout(src, 100, time.Second)
bus := lo.Broadcast(src)
```

## 注意
- 上游关闭会关闭下游；下游满会阻塞分发，合理设置 `cap` 或选择非阻塞策略。
- `BufferWith*` 返回 (items, len, duration, ok)，`ok` 表示通道未关闭。
- `Broadcast` 在任一下游堵塞时暂停广播，消费端需及时读取。

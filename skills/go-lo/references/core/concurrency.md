# Core / Concurrency

- 去抖/限流：`NewDebounce` / `NewDebounceBy`；`NewThrottle` / `NewThrottleWithCount` / `NewThrottleBy*`。
- 并发执行：`Async` / `Async0-6`（goroutine 返回 channel）；`Synchronize`（互斥包装）；`Attempt*`/`AttemptWithDelay*`/`AttemptWhile*`（重复尝试直到成功/条件）。
- 等待条件：`WaitFor` / `WaitForWithContext`（轮询布尔条件）；`BufferWithContext` / `BufferWithTimeout`（通道批量读取）。
- 事务补偿：`Transaction`（Saga 风格 Then/rollback 链）。

## 示例
```go
debounce, cancel := lo.NewDebounce(100*time.Millisecond, fn)
throttle, reset := lo.NewThrottle(100*time.Millisecond, fn)
ch := lo.Async(func() error { return work() })
iterations, _, ok := lo.WaitFor(func(i int) bool { return i>5 }, 10*time.Millisecond, time.Millisecond)
_, _ = lo.AttemptWithDelay(3, time.Second, risky)
```

## 注意
- `Debounce/Throttle` 需在结束时调用 `cancel/reset` 清理。
- `Async*` 返回的 channel 需消费避免 goroutine 泄漏。
- `Attempt*` 默认 panic 也会导致失败重试；若副作用不可重入需谨慎。
- `WaitFor` 间隔与总时长需匹配，否则可能忙等或超时过慢。

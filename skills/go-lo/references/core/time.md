# Core / Time

- 最早/最晚：`Earliest` / `EarliestBy`，`Latest` / `LatestBy`（空集合返回零值）。
- 时间范围相关可复用 math 中 `Min/Max` 处理 `time.Duration`。

## 示例
```go
earliest := lo.Earliest(time.Now(), time.Time{})
latest := lo.LatestBy(events, func(e Event) time.Time { return e.At })
```

## 注意
- `Earliest/Latest` 对空输入返回零值 `time.Time{}`，使用前可判空。

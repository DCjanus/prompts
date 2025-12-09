# Core / Error Handling

- 断言：`Validate`（返回 error 切片）；`Assert` / `Assertf`；`ErrorsAs`。
- 快速失败：`Must` / `Must0-6` 遇 `error`/`false` panic，可带格式化消息。
- 安全尝试：`Try` / `Try0-6` 捕获 panic 和 error，返回 `ok bool`。
- 回退默认：`TryOr` / `TryOr0-6` 失败时返回 fallback。
- 捕获处理：`TryCatch` / `TryCatchWithErrorValue`；`TryWithErrorValue` 返回 panic 值。

## 示例
```go
t := lo.Must(time.Parse(time.RFC3339, input))
val, ok := lo.TryOr(func() (int, error) { return work(), nil }, 0)
_ = lo.TryCatch(func() error { return errors.New("boom") }, func(err error) { log.Println(err) })
errs := lo.Validate(func() error { return nil }, func() error { return errors.New("bad") })
```

## 注意
- `Must` 族适合初始化/测试，线上路径可换 `Try*` 降低 panic 风险。
- `Try` 会吞掉 panic，需保留栈信息时在回调里自行记录或用 `TryCatch`。

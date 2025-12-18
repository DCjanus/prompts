# Core / Function

- 偏函数：`Partial` / `Partial2-5` 预绑定部分参数。
- 重复：`Times`（返回结果切片，带 index），并行版见 parallel。
- 验证：`Validate` 也可视为函数列表执行，见 error-handling。

## 示例
```go
add := func(a,b int) int { return a+b }
add5 := lo.Partial(add, 5)
res := add5(3) // 8
vals := lo.Times(3, func(i int) string { return fmt.Sprint(i) })
```

## 注意
- 偏函数对闭包捕获的可变变量敏感，确保线程安全。
- `Times` 迭代次数为 n，index 从 0 开始。

# Parallel / Slice (lop)

- 并行版本：`lop.Map` / `lop.Filter` / `lop.ForEach` / `lop.Reduce` / `lop.Times` 等，与 core API 类似但在 goroutine 执行。
- 顺序：多数返回值保持输入顺序（Map/Reduce/Times），但运行时仍并发；若顺序严格依赖副作用，避免并发。
- 控制并发度：默认按 CPU 核数，可通过 `runtime.GOMAXPROCS` 或自管 goroutine。

## 示例
```go
import lop "github.com/samber/lo/parallel"
res := lop.Map([]int{1,2,3,4}, func(x int, _ int) int { return x*x })
```

## 注意
- 回调应是并发安全的；避免写共享可变状态。
- 相比 core 版本有 goroutine 开销，小数据量时性能可能下降。

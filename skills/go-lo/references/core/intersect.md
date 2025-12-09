# Core / Intersect

- 交集：`Intersect`（按值）; `IntersectBy`（自定义映射后取交集）。可接收多集合。

## 示例
```go
lo.Intersect([]int{0,1,2,3,4,5}, []int{0,2})        // [0 2]
lo.Intersect([]int{0,3,5,7}, []int{3,5}, []int{0,3}) // [3 5]
lo.IntersectBy(func(v int) int { return v%3 }, []int{0,1,2,3}, []int{2,5})
```

## 注意
- 输入有重复时输出去重；`IntersectBy` 根据映射值比较。

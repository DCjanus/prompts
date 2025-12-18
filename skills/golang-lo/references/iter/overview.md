# Iter 包概览

- 提供惰性迭代器接口，适合流式或大集合逐步处理，API 按类别拆分：`sequence`（生成器/范围）、`slice`、`map`、`channel`、`find`、`intersect`、`string`、`tuple`、`type`。
- 调用方式：`loi := "github.com/samber/lo/it"`，常见模式是创建迭代器后链式 `Map/Filter/Take/Drop/Collect`。

## 示例
```go
import loi "github.com/samber/lo/it"
iter := loi.FromSlice([]int{1,2,3,4}).Filter(func(v int) bool { return v%2==0 }).Map(func(v int) int { return v*v })
res := iter.Collect() // []int{4,16}
```

## 注意
- 迭代器惰性求值，需 `Collect` / `ForEach` 等终止操作才执行。
- 不保证并发安全；与并发组合时自行同步。
- 大部分功能与 core 等价，除需流式/无限序列外优先 core 以简化。

# Core / Slice

## 常用 helper
- 迭代：`Map` / `Filter` / `FilterMap` / `FlatMap` / `Reduce` / `ReduceRight` / `ForEach` / `ForEachWhile` / `Times`。
- 去重/分组：`Uniq` / `UniqBy`；`GroupBy` / `GroupByMap`。
- 拆分/重排：`Chunk` / `PartitionBy` / `Flatten` / `Interleave` / `Shuffle` / `Reverse`。
- 构造：`Fill` / `Repeat` / `RepeatBy` / `Concat`。
- 取/切：`Slice` / `Drop*` / `Splice` / `Cut*` / `Trim*` / `Replace*` / `Clone` / `Nth/NthOr/NthOrZero`。
- 键值转换：`KeyBy`，`SliceToMap(Associate)` / `FilterSliceToMap` / `Keyify`。
- 统计：`Count*` / `Subset` / `IsSorted*` / `Contains*` / `Difference*` / `Without*`。

## 示例
```go
// 过滤并平方偶数
out := lo.Map(lo.Filter(nums, func(x int, _ int) bool { return x%2==0 }),
    func(x int, _ int) int { return x*x })

// 分组+计数
byAge := lo.GroupBy(users, func(u User) int { return u.Age })
ageCount := lo.MapValues(byAge, func(v []User) int { return len(v) })

// 安全取倒数第一个
last := lo.NthOr(items, -1, "fallback")
```

## 注意
- `Compact` 会移除零值 (0, "", nil, false)；需保留零值请用 `Filter`。
- `Slice`/`Drop*` 越界 panic；用 `NthOr/NthOrZero` 更安全。
- `lop.*` 并发版本不保证顺序（见 parallel/slice）。

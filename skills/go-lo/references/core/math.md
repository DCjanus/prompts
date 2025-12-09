# Core / Math

- 范围：`Range` / `RangeFrom` / `RangeWithSteps`（步长可负，方向需匹配区间）。
- 约束：`Clamp`。
- 聚合：`Sum` / `SumBy` / `Product` / `ProductBy` / `Mean` / `MeanBy` / `Mode`。
- 极值：`Min/MinBy/MinIndex/MinIndexBy`，`Max/MaxBy/MaxIndex/MaxIndexBy`。

## 示例
```go
xs := lo.Range(0, 5)            // [0 1 2 3 4]
clamped := lo.Clamp(15, 0, 10)  // 10
avg := lo.MeanBy(users, func(u User) float64 { return u.Score })
min, idx := lo.MinIndex([]int{3,1,2}) // 1, 1
```

## 注意
- 空切片时聚合/极值返回零值，Index 系列返回 -1；必要时先检查长度。

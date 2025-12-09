# Core / Map

## 常用 helper
- 基础：`Keys` / `Values` / `UniqKeys` / `UniqValues` / `HasKey` / `ValueOr`。
- 选择/剔除：`PickBy*`，`OmitBy*`。
- 合并/变换：`Assign`（后覆盖前），`MapKeys` / `MapValues` / `MapEntries`，`Entries/ToPairs` ↔ `FromEntries/FromPairs`，`MapToSlice` / `FilterMapToSlice`。
- 其他：`Invert`（值重复会覆盖）；`ChunkEntries`；`FilterKeys` / `FilterValues`。

## 示例
```go
merged := lo.Assign(map[string]int{"a":1}, map[string]int{"b":2}, map[string]int{"a":3})
onlyA  := lo.PickByKeys(merged, []string{"a"})
upper  := lo.MapKeys(merged, func(v int, k string) string { return strings.ToUpper(k) })
```

## 注意
- `Assign` 重复键保留最后一个。
- `Invert` 值重复会被后值覆盖。
- 遍历顺序不保证；顺序敏感时先排序。

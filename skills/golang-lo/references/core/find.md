# Core / Find & Search

- 单个：`Find` / `FindIndexOf` / `FindLastIndexOf` / `FindOrElse`。
- 键查找：`FindKey` / `FindKeyBy`（map）。
- 唯一与重复：`FindUniques` / `FindUniquesBy`；`FindDuplicates` / `FindDuplicatesBy`。

## 示例
```go
v, ok := lo.Find(nums, func(x int) bool { return x%2==0 })
idx := lo.FindLastIndexOf([]string{"a","b","a"}, "a")
uniq := lo.FindUniques([]int{1,2,2,3})      // [1 3]
dups := lo.FindDuplicates([]int{1,2,2,3,3}) // [2 3]
```

## 注意
- 未找到时 `Find` 返回零值、`ok=false`；`FindOrElse` 可给默认。
- `FindDuplicates*` 只返回出现超过一次的元素。

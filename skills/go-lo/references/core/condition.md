# Core / Condition

- 三元：`Ternary`（两支都会求值），`TernaryF`（惰性）。
- 链式条件：`If/ElseIf/Else` 与 `IfF`（惰性）。
- 判空类：`IsEmpty` / `IsNotEmpty`，`Coalesce*`（值/切片/map 取首个非空）。

## 示例
```go
id := lo.TernaryF(ptr==nil, func() string { return uuid.New().String() }, func() string { return *ptr })
val := lo.If(len(xs)>0, xs[0]).Else(0)
name := lo.Coalesce("", "fallback") // "fallback"
```

## 注意
- 避免副作用重复执行时使用惰性版本。
- `Coalesce*` 定义的“空”包含零值/空切片/空 map；需要严格判定时自定义条件。

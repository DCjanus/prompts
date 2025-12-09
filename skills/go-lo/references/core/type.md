# Core / Type & Pointer

- 指针构造：`ToPtr`；零值转 nil：`EmptyableToPtr`。
- 解引用：`FromPtr`（nil 返回零值），`FromPtrOr`（自定义默认）。
- 切片指针：`ToSlicePtr`，`FromSlicePtr` / `FromSlicePtrOr`。

## 示例
```go
p := lo.ToPtr("hi")
v := lo.FromPtrOr(p, "fallback") // "hi"
optional := lo.EmptyableToPtr("") // nil
vals := lo.FromSlicePtrOr([]*string{lo.ToPtr("a"), nil}, "x") // ["a", "x"]
```

## 注意
- `EmptyableToPtr` 将空串/0/nil slice/map/false 视为“空”；若需保留零值用 `ToPtr`。

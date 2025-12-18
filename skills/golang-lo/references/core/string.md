# Core / String

- `RandomString(length, charset...)` 生成随机串。
- `Substring(s, start, length)` 按 rune 截取，负索引从尾部。
- `ChunkString(s, size)` 按长度切块。
- `Truncate` / `TruncateWithLength` 按字节截断并追加省略符。

## 示例
```go
id := lo.RandomString(12)
head := lo.Substring("你好，lo", 0, 2) // "你好"
parts := lo.ChunkString("abcdef", 2)  // ["ab","cd","ef"]
short := lo.Truncate("多字节示例", 5, "...")
```

## 注意
- `Truncate*` 按字节截断，含多字节字符时可能截断半个 rune；需安全截断可先转 rune 切片。

# Core / Tuple

- 结构：`Tuple2`..`Tuple6` 提供命名字段 `A,B,...`。
- 打包/解包：`Pack*`（返回 Tuple），`Unpack*`（Tuple -> 多返回值）。
- 解压切片：`Zip*` / `Unzip*` / `ZipWith` / `UnzipWith`（按最短对齐，多余位置补零值）。

## 示例
```go
t := lo.Tuple2[string,int]{"a",1}
a,b := lo.Unpack2(t)
paired := lo.Zip2([]string{"a","b"}, []int{1,2}) // []Tuple2
s1,s2 := lo.Unzip2(paired)
```

## 注意
- 输入长度不等时 Zip/Unzip 使用零值填充缺口。

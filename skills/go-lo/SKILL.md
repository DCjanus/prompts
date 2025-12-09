---
name: go-lo
description: Go >= 1.18 项目中希望用 samber/lo（Lodash 风格泛型库）简化集合/映射/字符串、错误处理、重试/节流/防抖、通道并发或指针空值场景时使用。
---

# lo Go 工具库速用指南

## 快速上手
- 安装：`go get github.com/samber/lo@v1`。
- 常用导入：
```go
import (
    "github.com/samber/lo"
    lop "github.com/samber/lo/parallel"
    lom "github.com/samber/lo/mutable"
    loi "github.com/samber/lo/it"
)
```
- 常用函数速览：
```go
// Filter: 按条件保留
lo.Filter(nums, func(x int, _ int) bool { return x%2==0 })
// Map: 映射生成新切片
lo.Map(nums, func(x int, _ int) int { return x*x })
// Find: 找到首个满足条件的元素
v, ok := lo.Find(nums, func(x int) bool { return x > 10 })
// Uniq: 去重并保持顺序
uniq := lo.Uniq([]string{"a","a","b"})
// GroupBy: 按键分组
groups := lo.GroupBy(users, func(u User) int { return u.Age })
// Must: 遇 err/false panic，常用于初始化
t := lo.Must(time.Parse(time.RFC3339, ts))
```

## 资源（按官方 docs/docs 结构，树状索引）
- core/
  - slice.md
  - map.md
  - string.md
  - math.md
  - time.md
  - condition.md
  - type.md
  - error-handling.md
  - concurrency.md
  - channel.md
  - find.md
  - intersect.md
  - function.md
  - tuple.md
- parallel/
  - slice.md
- mutable/
  - slice.md
- iter/
  - overview.md

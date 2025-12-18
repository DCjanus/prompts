# Mutable / Slice (lom)

- In-place 版本：`lom.Map` / `lom.Filter` / `lom.ForEach` 等直接修改底层切片，减少分配。

## 示例
```go
import lom "github.com/samber/lo/mutable"
list := []int{1,2,3,4}
newList := lom.Filter(list, func(x int) bool { return x%2==0 })
// list 现在可能被重排；newList 指向过滤后的视图
```

## 注意
- 原切片会被修改且可能重排，不可再依赖旧顺序或长度。
- 返回的新切片与原切片共享底层数组，后续修改需谨慎复制。

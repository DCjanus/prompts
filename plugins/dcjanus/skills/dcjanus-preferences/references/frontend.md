# 前端技术偏好

- 前端语言默认 TypeScript。新建 React Web 项目优先采用 React + Vite；已有项目沿用其既定技术栈。语言、框架和依赖优先选满足项目约束的较新稳定版本，不为了追新而破坏兼容性或顺带升级无关依赖。
- 路由、服务端状态、复杂表格和长列表按实际需要分别优先考虑 TanStack Router、Query、Table 和 Virtual；不要为了统一而安装没有用到的包。TanStack Table、Form 等提供状态和逻辑，不代替组件的语义、键盘交互或焦点管理。
- 日期与时间处理优先使用 dayjs。
- URL query、表单输入、API 响应等不可信数据边界优先考虑 Zod：定义运行时 schema 并推导 TypeScript 类型；TanStack Router 的搜索参数可直接使用 Zod v4 schema。不要为已经由类型系统约束的内部数据重复添加解析。
- 若服务端 API 由 Protobuf 定义并用 AIP-127 `google.api.http` 映射到 HTTP，优先从 `.proto` 直接生成 TypeScript 消息、schema 和适用的调用代码，避免先转 OpenAPI 再生成时丢失 `int64` 等契约信息。遵循 ProtoJSON：线上 `int64/uint64` 用十进制字符串，前端解析为 `bigint`；`Timestamp` 用 RFC3339。生成消息类型不等于生成 AIP-127 HTTP 方法：调用代码生成器须处理注解中的路径、query、body 等映射；若服务端另行提供 Connect 协议，可使用生成的服务描述和 Connect 客户端，但不能把它直接当成 AIP-127 路由客户端。具体 Protobuf 字段语义另见 `protobuf.md`。
- 优先采用现成 UI 组件，减少自行实现交互。首版界面优先以 HeroUI 作为可见控件和设计风格的主要来源；其交互底层是 React Aria Components。
- shadcn/ui 留作需要更深度定制时的候选，先评估具体控件再决定是否引入；若引入，优先选择基于 Radix Primitives 的版本。Radix 是 React 中与 Reka UI 最接近的无障碍组件基础设施。
- 如果最终混用，同一类控件只选择一个来源，并统一颜色、字重、圆角、间距和焦点样式等设计 token；不要让两套默认主题直接并排出现。即使用了组件库，也要检查页面自身的语义、标签、键盘操作、焦点顺序和可见焦点。

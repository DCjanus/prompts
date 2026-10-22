# 前端偏好

- 前端语言默认 TypeScript。新建 React Web 项目优先采用 React + Vite；已有项目沿用其既定技术栈。语言、框架和依赖优先选满足项目约束的较新版本，不为了追新而破坏兼容性或顺带升级无关依赖。
- 前端能力有满足需求的 TanStack 对应产品时优先使用：路由使用 Router，服务端数据获取与缓存使用 Query，表单使用 Form，表格使用 Table，虚拟化使用 Virtual，客户端共享状态使用 Store；其他能力同样先核对 TanStack 是否覆盖实际需求，再选择外部库，不安装未用到的包。使用 TanStack 的无头组件时，仍需确保语义、键盘交互和焦点管理。
- 同一能力优先复用项目已有依赖，避免引入职责重叠的组件库、图标库、动画库或状态库；确有能力缺口时再补充，并明确各自边界。不为凑齐技术栈预装整套依赖，也不为消除间接依赖中的重复版本强行覆盖不兼容的版本约束。
- 状态按职责归属：服务端数据获取与缓存优先使用 [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/guides/does-this-replace-client-state)，有分享或恢复价值的浏览状态以 URL 为准，组件局部状态使用 React 自带能力。确需独立的跨组件客户端 store 时，优先使用 [TanStack Store](https://tanstack.com/store/latest)，React 使用 `@tanstack/react-store`。通过 selector 订阅需要的状态，不把 Query 缓存或 URL 状态复制到 store 中维护第二份事实来源。
- 页面中影响内容展示、且有分享或恢复价值的状态，例如当前 tab、搜索条件、筛选项、排序和分页，应同步到 URL，并在直接打开链接、刷新及浏览器前进／后退时正确恢复。URL 与界面状态应双向同步；短暂的交互状态，例如悬停、焦点和未提交的输入，无需写入 URL。恢复浏览状态以相同权限和可用数据为前提。
- 状态持久化、分享与恢复应保留用户选择的条件及其原本语义，而不是擅自替换为某次求值的结果或快照。优先保存能表达用户意图的源状态，恢复时按原语义重新求值；只有用户明确选择固定结果、绝对值或快照时才冻结。例如“最近 7 天”应保留相对范围，取数时按当前时刻展开，不能为了同步到 URL 自动改成固定的绝对起止时间。
- 程序内部与 URL 中的视图、列、排序键等结构性标识采用固定的英文 ASCII 标识，与面向用户的显示文案分离。例如界面显示“耗时”，排序键使用 `duration_ms`；这样可减少中文编码噪声，保持浏览器中的链接可读性，并避免显示语言变化影响状态恢复。搜索词等用户内容保留原文，不适用此约束。
- 日期与时间处理优先使用 dayjs。
- URL query、表单输入、API 响应等不可信数据边界优先考虑 Zod：定义运行时 schema 并推导 TypeScript 类型；TanStack Router 的搜索参数可直接使用 Zod v4 schema。不要为已经由类型系统约束的内部数据重复添加解析。
- 服务端 API 由 Protobuf 定义时，优先采用 Connect 生态：从 `.proto` 直接生成 TypeScript 消息和服务描述，再用 Connect 客户端调用；避免先转 OpenAPI 而丢失 `int64` 等契约信息。确认服务端所用 Connect 实现支持需要的协议及普通 gRPC 客户端接入。浏览器原生图片标签、Prometheus 抓取等要求原始媒体类型的端点，可保留薄的 HTTP 适配层。字段语义、Buf 依赖和入参校验另见 `protobuf.md`。
- 优先通过分组、位置、间距和视觉层级表达内容归属与操作关系，避免添加重复标题、不必要的辅助标签和复述界面的说明文字。布局已能清楚表达的信息无需再用文案解释；帮助用户理解业务含义、输入要求、异常状态或操作后果的文字，以及必要的控件标签和无障碍名称，应予保留。
- 优先采用成熟、可复用的 UI 组件，减少自行实现交互；需要定制时优先选择可将组件源码纳入项目维护的方案。新建 React 界面优先使用 shadcn/ui，并默认选择 Mira 风格；已有项目沿用其设计系统，用户明确指定的风格优先。
- shadcn/ui 优先选择基于 Radix Primitives 的版本，复用其键盘交互和焦点管理等无障碍基础能力。
- 如果混用组件来源，同一类控件只选择一个来源，并统一颜色、字重、圆角、间距和焦点样式等设计 token。即使用了组件库，也要检查页面自身的语义、标签、键盘操作、焦点顺序和可见焦点。
- 图标默认统一使用 [Lucide](https://lucide.dev/guide/react/) 的 `lucide-react`，按名称导入用到的图标，统一尺寸与描边风格。装饰图标对辅助技术隐藏，仅图标按钮提供可访问名称；品牌标识等缺失图形可单独补充，不因此再引入一整套通用图标库。
- 动画优先复用组件已有行为和 CSS transition；需要进入／退出、布局、手势或编排动画时，统一使用 [Motion for React](https://motion.dev/docs/react)（`motion` 包、`motion/react` 入口）。尊重 `prefers-reduced-motion`，按需通过 [useReducedMotion](https://motion.dev/docs/react-use-reduced-motion) 调整或关闭动画。
- 表格列宽调整使用 [TanStack Table 的列宽能力](https://tanstack.com/table/latest/docs/framework/react/guide/column-sizing)。需要用户拖动调整页面分栏尺寸时，优先使用 [react-resizable-panels](https://github.com/bvaughn/react-resizable-panels)；使用 shadcn/ui 的项目优先复用其 [Resizable](https://ui.shadcn.com/docs/components/radix/resizable) 封装，保持设计 token 和键盘操作一致。普通响应式布局使用 CSS Grid／Flex，不为静态布局引入分栏库。
- 列表排序、看板及跨容器拖放优先使用 [dnd-kit](https://dndkit.com/react/quickstart/)，结合现有组件和设计 token 实现界面；表格行列排序由 TanStack Table 管理顺序状态，拖放交互结合 dnd-kit，参考其 [官方示例](https://tanstack.com/table/latest/docs/framework/react/examples/column-dnd)。按所选版本使用对应文档与 API，避免混用新旧包体系；支持指针、触摸和键盘操作，并提供可理解的操作提示与结果反馈。Motion 的拖动手势用于视觉交互，业务排序和投放逻辑由 dnd-kit 负责。

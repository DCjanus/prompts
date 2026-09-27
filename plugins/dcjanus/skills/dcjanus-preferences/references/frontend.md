# React 前端技术偏好

- 新建 React Web 项目优先采用 React + Vite。已有项目沿用其既定技术栈。
- 路由、服务端状态、复杂表格和长列表按实际需要分别优先考虑 TanStack Router、Query、Table 和 Virtual；不要为了统一而安装没有用到的包。TanStack Table、Form 等提供状态和逻辑，不代替组件的语义、键盘交互或焦点管理。
- 日期与时间处理优先使用 dayjs。
- 优先采用现成 UI 组件，减少自行实现交互。需要可组合、可定制的组件时采用 shadcn/ui，并优先选择基于 Radix Primitives 的版本；Radix 是 React 中与 Reka UI 最接近的无障碍组件基础设施。需要更完整的现成视觉组件时可采用 HeroUI。
- 同一类控件在 shadcn/ui 与 HeroUI 中选择一个来源，避免重复组件体系。即使用了组件库，也要检查页面自身的语义、标签、键盘操作、焦点顺序和可见焦点。

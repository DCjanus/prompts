# React 前端技术偏好

- 新建 React Web 项目优先采用 React + Vite。已有项目沿用其既定技术栈。
- 路由、服务端状态、复杂表格和长列表按实际需要分别优先考虑 TanStack Router、Query、Table 和 Virtual；不要为了统一而安装没有用到的包。TanStack Table、Form 等提供状态和逻辑，不代替组件的语义、键盘交互或焦点管理。
- 日期与时间处理优先使用 dayjs。
- 优先采用现成 UI 组件，减少自行实现交互。用户偏好 HeroUI 的默认视觉表现时，以 HeroUI 作为可见控件和设计风格的主要来源；其交互底层是 React Aria Components。
- HeroUI 缺少需要的控件、或控件需要深度组合时，再采用 shadcn/ui，并优先选择基于 Radix Primitives 的版本。Radix 是 React 中与 Reka UI 最接近的无障碍组件基础设施。
- 混用时，同一类控件只选择一个来源，并统一颜色、字重、圆角、间距和焦点样式等设计 token；不要让两套默认主题直接并排出现。即使用了组件库，也要检查页面自身的语义、标签、键盘操作、焦点顺序和可见焦点。

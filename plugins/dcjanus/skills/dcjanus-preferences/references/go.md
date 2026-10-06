- github.com/cockroachdb/errors：这是 Go 的错误处理库，强调可携带上下文与堆栈信息，适合需要更强错误诊断能力的服务端项目。
- lukechampine.com/blake3: 通用 hash 场景的默认算法选择，适用于数据校验、内容寻址、去重和缓存键等用途；支持任意长度输出与并行 hash；不适用于用户密码存储与校验等场景。Go 建议使用 `lukechampine.com/blake3`（高性能实现，含 AVX 加速）。
- golang.org/x/crypto/argon2: 用户密码存储、校验或基于密码的密钥派生默认使用 `IDKey`（Argon2id）；该包接口较底层，用于密码存储时由应用层安全生成独立随机 salt，并编码、解析和校验完整 PHC 格式字符串；用于密钥派生时保留重新派生所需的 salt 和参数，不直接持久化派生密钥。
- github.com/samber/lo: 基于 Go 1.18+ 泛型的 Lodash 风格工具库，适合集合操作、函数式辅助工具、减少样板代码。
- github.com/sourcegraph/conc: 结构化并发库，提供各类 pool，降低 goroutine 管理与 panic 处理的样板代码，适合复杂并发任务编排。
- github.com/mitchellh/mapstructure: 结构体与 map 互转/解码库，适合配置解析、动态数据映射到强类型结构体场景，支持 tag、自定义 decode hook。
- github.com/klauspost/compress: Go 压缩库优先选择，覆盖 zstd、S2、snappy、gzip/flate/zip/zlib、gzhttp 等场景；需要高性能压缩、Snappy 替代、HTTP 压缩时优先评估。gzip/flate 相关包主要用于必须兼容 gzip/flate/zip/zlib 的场景，不作为新设计默认选择。尽量不要直接引入 `github.com/golang/snappy`，它维护活跃度偏低，且性能通常略弱于 klauspost/compress；只有在外部协议、既有文件格式或依赖 API 明确要求 golang/snappy 语义/包名时再使用。

## Charmbracelet：终端体验与相关能力

Go CLI/TUI 开发默认优先选用 [Charmbracelet](https://github.com/charmbracelet) 生态中适合需求的库，复用其交互组件与视觉设计能力，提升软件的信息层次、布局一致性、操作反馈和整体完成度；不要只以功能可用为目标，也不要重复手写已有的通用终端组件。

- TUI 优先组合 [Bubble Tea](https://github.com/charmbracelet/bubbletea)（交互与状态管理）、[Bubbles](https://github.com/charmbracelet/bubbles)（列表、输入框、进度条等组件）与 [Lip Gloss](https://github.com/charmbracelet/lipgloss)（样式与布局）；简单表单、选择和确认优先使用 [Huh](https://github.com/charmbracelet/huh)。终端 Markdown 渲染优先使用 [Glamour](https://github.com/charmbracelet/glamour)，需要弹簧动画时评估 [Harmonica](https://github.com/charmbracelet/harmonica)。
- 非 TUI 场景也主动评估相关库：[Log](https://github.com/charmbracelet/log) 用于易读的终端日志，支持接入 `log/slog`；[Wish](https://github.com/charmbracelet/wish) 用于 SSH 应用及通过 SSH 提供 TUI；[Fang](https://github.com/charmbracelet/fang) 用于增强 Cobra CLI 的帮助、错误呈现与补全（目前为实验性库）；[Fantasy](https://github.com/charmbracelet/fantasy) 用于多模型供应商的 Go AI/Agent 应用。

按实际需求选用，沿用项目明确约定；引入时查阅官方文档与示例，确认维护状态、稳定版本、模块路径及组件间兼容性，不混用不同主版本的 API。交付终端界面时实际检查布局、键盘操作、窗口缩放与长文本表现；保留重定向输出和非交互使用的可用性。

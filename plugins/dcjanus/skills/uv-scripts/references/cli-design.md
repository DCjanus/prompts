# CLI 设计

- 依赖库偏好：

| 场景 | 优先选择 | 说明 |
| --- | --- | --- |
| 命令行 | `Typer` | 用来定义 CLI、参数和子命令 |
| 人类可读输出 | `Rich` | 用来做表格、提示和更清晰的终端输出 |
| 结构化输入校验 | `Pydantic` | 用来校验 Typer 解析后的复合业务对象 |

### CLI 接口契约

- 目标是让调用方只看 `--help` 就能确定参数的语义、格式、可选值、默认行为及重复或互斥规则，不需要阅读实现或借助额外文档。
- 优先用 `Annotated` 的最窄语义 Python 类型和 Typer/Click 内建约束定义参数，例如 `Path`、带 `formats` 的 `datetime`、数值范围、`Enum` 和可重复集合；让解析层直接拒绝无效值，并在 help metavar 中展示格式。不要把有语义的参数退化为 `str` 后再手工解析。
- Typer 没有内建类型的单个领域值使用 `parser` 转成语义类型，并设置能表达输入形状的 `metavar`；参数 callback 只做无副作用的单值校验，不输出信息，避免干扰 shell completion。
- 自定义 option `metavar` 时同时显式声明真实选项名，例如 `typer.Option("--state-id", metavar="STATE_ID")`；不依赖 Typer 根据参数名的隐式推导，避免 metavar 被误渲染成 option 名。
- `help` 文案补充类型无法表达的业务语义，尤其是默认值来源、参数间关系和显式退出开关。只有跨参数关系、结构化输入或 Typer 无法表达的业务规则才使用 Pydantic 或手工校验。
- 参数较多时才使用 `rich_help_panel` 按用途分组；不为了视觉形式拆分简短帮助。自定义选项名、布尔 flag 对或 metavar 时，以用户实际输入的命令形状为准。
- 测试除成功路径外，还要验证 `--help` 中真实选项名、关键格式或可选值可见，以及解析层会拒绝代表性非法输入。Rich help 断言前先用 `Text.from_ansi(output).plain` 去掉 ANSI 样式，不要让终端颜色环境影响文本契约测试。
- 参数和输出保持稳定；需要机器可读输出时提供 `--json`
- 能通过参数传入的路径、仓库目录、配置，不要偷偷依赖当前 shell cwd
- 模块、函数、类型写简短中文 docstring


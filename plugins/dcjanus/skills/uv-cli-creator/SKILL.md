---
name: uv-cli-creator
description: 创建或修改基于 PEP 723、由 uv 管理且可直接执行的单文件 Python CLI。一次性分析脚本和一般执行环境问题使用 python-execution。
---

## 设计目标

目标很简单：

- 不手动安装依赖，也不依赖宿主机已经准备好的 Python 环境
- 默认只依赖 `uv`；直接执行还要求 Unix 环境支持 `env -S`
- 方便修改和版本控制
- 环境支持时优先直接执行脚本；`uv run --script` 作为通用执行方式

## 初始化与维护

新脚本使用 [init_cli.py](scripts/init_cli.py) 初始化。该入口自身已有可执行权限和 uv shebang，正常情况下像 shell 命令一样直接调用，不要使用 `python`、`python3` 或额外的 `uv run --with typer` 包裹：

```bash
skills/uv-cli-creator/scripts/init_cli.py <目标路径> [--dependency <依赖>] [--python <版本或解释器>]
```

`--dependency` 可重复，用于添加依赖；`--python` 用于指定 Python 版本。未指定版本时沿用 uv 的解释器发现规则，由 uv 自动填写最低版本要求，不额外筛选最新版。脚本自动完成 PEP 723 初始化、shebang 和执行权限设置，拒绝覆盖已有文件。

为 skill 创建的入口放在该 skill 的 `scripts/` 目录下；初始化后直接编写业务逻辑。后续依赖通过 `uv add --script` / `uv remove --script` 管理，不手工编辑依赖块。

在支持 `/usr/bin/env -S`、脚本有执行权限且文件系统允许执行的 Unix 环境中，优先用脚本路径直接运行（当前目录下如 `./xxxx.py`）。Windows、缺少 `env -S`、执行权限或文件系统禁止执行时，使用 `uv run --script <脚本路径>`。

## 细节偏好

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
- 被入口脚本 import 的普通模块不要写 shebang，不要写 `/// script`
- 参数和输出保持稳定；需要机器可读输出时提供 `--json`
- 能通过参数传入的路径、仓库目录、配置，不要偷偷依赖当前 shell cwd
- 模块、函数、类型写简短中文 docstring

## 验证

- 优先验证直接执行入口，同时验证 `uv run --script`；无法直接执行的环境只验证脚本模式。
- `uvx ruff check <path>`
- `uvx ruff format --check <path>`

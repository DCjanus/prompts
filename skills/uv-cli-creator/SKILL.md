---
name: uv-cli-creator
description: 创建或修改基于 PEP 723、由 uv run --script 管理的可复用单文件 Python CLI。一次性分析脚本和一般执行环境问题使用 python-execution。
---

## 设计目标

目标很简单：

- 不手动安装依赖，也不依赖宿主机已经准备好的 Python 环境
- 默认只依赖 `uv`；直接执行还要求 Unix 环境支持 `env -S`
- 方便修改和版本控制
- 始终可以通过 `uv run --script` 执行；环境支持时也可以像可执行文件一样直接执行

## 初始化与维护

新脚本使用 [init_cli.py](scripts/init_cli.py) 初始化：传入目标路径，按需用 `--dependency`（可重复）添加依赖、用 `--python` 指定 Python 版本。未指定版本时沿用 uv 的解释器发现规则，由 uv 自动填写最低版本要求，不额外筛选最新版。脚本自动完成 PEP 723 初始化、shebang 和执行权限设置，拒绝覆盖已有文件。

为 skill 创建的入口放在该 skill 的 `scripts/` 目录下；初始化后直接编写业务逻辑。后续依赖通过 `uv add --script` / `uv remove --script` 管理，不手工编辑依赖块。

不支持 `env -S` 的 Unix 环境以及 Windows 使用 `uv run --script` 执行。

## 细节偏好

- 依赖库偏好：

| 场景 | 优先选择 | 说明 |
| --- | --- | --- |
| 命令行 | `Typer` | 用来定义 CLI、参数和子命令 |
| 人类可读输出 | `Rich` | 用来做表格、提示和更清晰的终端输出 |
| 参数校验 | `Pydantic` | 用来做输入校验和更清晰的错误信息 |

- 被入口脚本 import 的普通模块不要写 shebang，不要写 `/// script`
- 参数和输出保持稳定；需要机器可读输出时提供 `--json`
- 能通过参数传入的路径、仓库目录、配置，不要偷偷依赖当前 shell cwd
- 模块、函数、类型写简短中文 docstring

## 验证

- 验证脚本模式；提供可执行入口时，同时验证该入口。
- `uvx ruff check <path>`
- `uvx ruff format --check <path>`

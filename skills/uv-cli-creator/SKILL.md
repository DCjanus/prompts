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

## 怎么实现

入口脚本的基本流程：

```bash
uv init --script scripts/foo.py
uv add --script scripts/foo.py <package>
```

`uv init --script` 不会生成 shebang。需要直接执行时，在 PEP 723 metadata 前添加：

```python
#!/usr/bin/env -S uv run --script
#
# /// script
```

然后设置执行权限：

```bash
chmod +x scripts/foo.py
```

`env -S` 不是 POSIX 标准；不支持它的 Unix 环境以及 Windows 应使用 `uv run --script scripts/foo.py`。

依赖管理规则：

- 添加依赖：`uv add --script scripts/foo.py <package>`
- 移除依赖：`uv remove --script scripts/foo.py <package>`
- 不手工编辑头部 `/// script` 依赖块

入口脚本放在对应 skill 的 `scripts/` 目录下。

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

---
name: uv-cli-creator
description: 创建或修改 uv --script 风格的 Python CLI；当需要把重复命令封装成 `./scripts/...` 直接执行的工具，或需要统一这类脚本约定时使用。
---

## 设计目标

目标很简单：

- 不手动安装依赖，也不依赖宿主机已经准备好的 Python 环境
- 默认只依赖一个 `uv`
- 方便修改和版本控制
- 脚本可以像可执行文件一样直接执行：`./scripts/foo.py`

## 怎么实现

入口脚本的基本流程：

```bash
uv init --script scripts/foo.py
uv add --script scripts/foo.py <package>
chmod +x scripts/foo.py
./scripts/foo.py --help
```

依赖管理规则：

- 添加依赖：`uv add --script scripts/foo.py <package>`
- 移除依赖：`uv remove --script scripts/foo.py <package>`
- 不手工编辑头部 `/// script` 依赖块

调用规则：

- 入口脚本放在对应 skill 的 `scripts/` 目录下
- 入口脚本默认应能直接执行：`./scripts/foo.py`
- 不要在 skill 文档里把入口脚本写成 `python ...` 或 `uv run python ...`

## 给其他 skill 用时

如果某个 skill 会调用这个脚本，下面这段模板应直接写进那个 skill 自己的 `SKILL.md`，作为调用约定保留下来：

````markdown
说明：以下脚本调用均以当前 `SKILL.md` 所在文件夹为 workdir。

脚本调用方式（必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`）：

```bash
cd skills/<skill-name> && ./scripts/<tool>.py --help
```

错误示例：

```bash
uv run python skills/<skill-name>/scripts/<tool>.py --help
python skills/<skill-name>/scripts/<tool>.py --help
```
````

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

- `./scripts/foo.py --help`
- `uv run ruff check <path>`
- `uv run ruff format --check <path>`

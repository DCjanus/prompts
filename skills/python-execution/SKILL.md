---
name: python-execution
description: 编写或运行 PEP 723 临时 Python 脚本、处理 Python 执行环境，以及选择 Python 格式与 lint 检查方式时使用。已有 CLI 按其自身入口运行；创建具有稳定接口的单文件 CLI 使用 uv-cli-creator。
---

# Python 执行与检查

## 执行环境

- 本机默认已安装 uv；首次使用或遇到找不到命令时核实。同一目标环境内复用已确认的结果。
- 远端服务器和容器单独检查 uv，不把本机工具前提套用到远端。有 uv 时优先使用 uv；没有时沿用目标已有工具链，不为一次性任务擅自安装或修改远端环境。
- 项目已有解释器、虚拟环境或执行入口时遵守项目约定；已有 PEP 723 脚本使用可执行入口或 `uv run --script`，不要用 `uv run python` 绕过脚本依赖声明。

## 临时脚本

- 多步结构化数据处理、复杂循环或转义逻辑优先写成临时 Python，避免拼成复杂 shell；简单命令不必改写。
- 用目标执行环境的临时目录保存脚本和中间文件，默认不写入目标仓库。通过参数传入输入、输出和目标项目路径，避免依赖启动 Codex 时的 cwd。
- 临时脚本也采用 PEP 723，将 Python 要求和依赖声明保存在脚本头部，统一使用 `uv run --script <临时脚本路径> ...`。不通过运行时 `--with` 参数补充依赖，方便之后直接复用脚本。
- 用 `uv init --script <临时脚本路径>` 初始化脚本；标准库脚本保留工具生成的空依赖列表，外部依赖用 `uv add --script <临时脚本路径> <包>...` 添加，移除时使用 `uv remove --script`，不手工编辑依赖块。
- 独立分析使用脚本声明的环境，不依赖启动目录下的项目依赖；需要调用项目代码时遵守项目已有入口与环境约定。
- 执行结束且不再需要时，清理自己创建的临时文件。保留用户文件、交付物和仍需复用的诊断材料。
- 需要面向用户的稳定参数、输出契约或可执行入口时，使用 [SKILL.md](../uv-cli-creator/SKILL.md) 定义 CLI；仅采用 PEP 723 不需要额外加载 CLI 创作流程。

```bash
uv init --script /tmp/example.py
uv add --script /tmp/example.py <package>
uv run --script /tmp/example.py
```

只用标准库时省略添加依赖这一步；脚本逻辑直接编辑，依赖由 uv 管理。

## 检查

修改 Python 后优先使用项目既有检查命令与配置。项目未指定时，对改动文件执行：

```bash
uvx ruff format --check <paths>
uvx ruff check <paths>
```

检查失败时只修正当前任务相关问题；测试范围按全局约定和项目要求选择。

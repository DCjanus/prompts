---
name: uv-scripts
description: 编写、运行或维护由 uv 管理的独立 Python 脚本与单文件 CLI，以及处理相关执行环境和检查问题时使用。
---

# uv 脚本与 CLI

## 执行环境

- 项目已有解释器、虚拟环境或执行入口时遵守项目约定；已有 CLI 按自身入口运行。
- 本机默认已安装 uv；首次使用或遇到找不到命令时核实。同一目标环境内复用已确认的结果。
- 远端服务器和容器单独检查 uv。有 uv 时优先使用 uv；没有时沿用目标已有工具链，不为一次性任务擅自安装或修改远端环境。
- 独立分析使用脚本声明的环境，不依赖启动目录下的项目依赖；需要调用项目代码时遵守项目已有入口与环境约定。
- 通过参数传入输入、输出、配置和目标项目路径，避免依赖启动 Agent 时的 cwd。

## 临时脚本

- 用目标执行环境的临时目录保存脚本和中间文件，默认不写入目标仓库。
- 采用 PEP 723，将 Python 要求和依赖声明保存在脚本头部，使用 `uv run --script <脚本路径> ...`。不通过运行时 `--with` 参数补充依赖，方便之后直接复用脚本。
- 使用 [init_script.py](scripts/init_script.py) 的 `--temporary` 模式生成 PEP 723、shebang 和执行权限，随后编写业务逻辑。依赖默认只传包名，确有兼容性需要时传入版本约束；无需手写固定文件头。
- 无版本约束时，由 uv 按运行环境和依赖关系解析可用版本，默认优先最新版本；缓存或已有环境可能被复用，不要求每次运行都刷新。确有兼容性需求时再添加必要的版本约束。
- 执行结束且不再需要时，清理自己创建的临时文件。保留用户文件、交付物和仍需复用的诊断材料。

```bash
scripts/init_script.py <临时脚本路径> --temporary --dependency httpx
```

依赖字符串遵循 [Python 依赖声明规范](https://packaging.python.org/en/latest/specifications/dependency-specifiers/)；不限制版本时省略版本部分，不写 `=*` 或 `==*`。

## 长期维护的独立脚本

- 放在项目或 skill 的正式维护位置，沿用已有入口；为 skill 创建的入口放在该 skill 的 `scripts/` 目录下。
- 依赖通过 `uv add --script` / `uv remove --script` 管理，不手工编辑依赖块；版本选择遵循 [依赖管理](../dependency-management/SKILL.md)。
- 长期保留本身不要求引入 CLI 框架。需要向用户或自动化提供稳定参数、帮助和输出时，读取 [CLI 设计](references/cli-design.md)。
- 新建可直接执行的入口使用 [init_script.py](scripts/init_script.py)：

```bash
scripts/init_script.py <目标路径> [--dependency <依赖>] [--python <版本或解释器>]
```

示例中的初始化器路径均相对于本 skill 目录。该入口正常情况下直接调用，无需用 `python`、`python3` 或额外的 `uv run --with typer` 包裹。

`--dependency` 可重复；`--python` 指定 Python 版本。未指定版本时沿用 uv 的解释器发现规则，不额外筛选最新版。初始化器设置 PEP 723、shebang 和执行权限，拒绝覆盖已有文件；初始化后编写业务逻辑。

在支持 `/usr/bin/env -S`、脚本有执行权限且文件系统允许执行的 Unix 环境中，优先用脚本路径直接运行。其它环境使用 `uv run --script <脚本路径>`。

被入口脚本 import 的普通模块不要写 shebang 或 `/// script`。

## 检查

修改 Python 后优先使用项目既有检查命令与配置。项目未指定时，对改动文件执行：

```bash
uvx ruff format --check <paths>
uvx ruff check <paths>
```

检查失败时只修正当前任务相关问题；测试范围按全局约定和项目要求选择。创建或修改可执行入口时，验证直接执行及 `uv run --script`；无法直接执行的环境只验证脚本模式。CLI 接口验证要求见 [CLI 设计](references/cli-design.md)。

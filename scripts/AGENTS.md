## 目录约束
- 本目录内所有 Python 脚本必须使用 uv 的 script 模式：首行 shebang 为 `#!/usr/bin/env -S uv run --script`。
- 新建脚本推荐：`uv init --script <file.py>`，会写入 shebang 与空的 `/// script` 元数据块。
- 依赖声明：使用 `uv add --script <file.py> <依赖...>` 生成/更新文件头部 `/// script` 元数据块中的 `dependencies`。
- 元数据块（含 shebang 与 `/// script` 部分）是唯一依赖声明位置，禁止手工编辑。
- 运行方式：为脚本添加执行权限（`chmod +x <file.py>`）后直接运行 `./<file.py>`。
- 命令行参数定义优先使用 Typer，提供更友好的 CLI 体验；输出信息尽量用 rich 提升可读性与美观度；数据校验/模型定义尽量用 pydantic。
- 脚本内每个模块、函数与类型都必须包含简短中文文档字符串。
- 依赖项必须按需添加；移除依赖项的引用后，若确认不再使用，需同步移除该依赖。
- 脚本完成后优先用 uv 调用 ruff 做质量检查与格式化：`uv run ruff check scripts`；格式化：`uv run ruff format scripts`。对单文件可替换为具体路径。

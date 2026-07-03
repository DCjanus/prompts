---
name: tampermonkey-cli
description: 通过 Tampermonkey Editors 管理浏览器里的 Tampermonkey userscript；适用于需要从 Codex 安装、更新、读取、列出或删除本机油猴脚本，或把本地 .user.js 同步到 Tampermonkey 时使用。
---

通过 Tampermonkey Editors 的本地 WebSocket 协议管理浏览器里的 userscript。

## 调用约定

说明：以下脚本调用均以当前 `SKILL.md` 所在文件夹为 workdir。

脚本调用方式必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`：

```bash
cd skills/tampermonkey-cli
./scripts/tampermonkey.py --help
```

错误示例：

```bash
uv run python skills/tampermonkey-cli/scripts/tampermonkey.py --help
python skills/tampermonkey-cli/scripts/tampermonkey.py --help
```

## 工作流

1. 确认浏览器已安装 Tampermonkey 和 Tampermonkey Editors。
2. 启动常驻桥接：

```bash
./scripts/tampermonkey.py serve
```

3. 把输出的 `Tampermonkey Editors connection code` 输入 Tampermonkey Editors。
4. 保持 `serve` 进程运行。
5. 在其它 shell 或后续 Codex 命令中复用默认 socket 调用：

```bash
./scripts/tampermonkey.py status
./scripts/tampermonkey.py list
./scripts/tampermonkey.py get '<script-path>/source' --output /tmp/example.user.js
./scripts/tampermonkey.py put /path/to/example.user.js
./scripts/tampermonkey.py patch '<script-path>/source' /path/to/example.user.js
```

## Socket 约定

- 控制面使用 Unix Domain Socket，不使用 localhost HTTP。
- 默认 socket 路径优先使用 `$XDG_RUNTIME_DIR/codex-tampermonkey.sock`。
- 如果 `$XDG_RUNTIME_DIR` 不存在，则使用 `$XDG_CACHE_HOME/codex/codex-tampermonkey.sock`。
- 如果 `$XDG_CACHE_HOME` 也不存在，则使用 `~/.cache/codex/codex-tampermonkey.sock`。
- 需要覆盖默认路径时，所有命令都支持 `--socket <path>`。

## 命令

- `serve`：启动桥接进程，打印一次 connection code，并持有 Tampermonkey Editors 连接。
- `status`：查看 `serve` 是否存在、Tampermonkey Editors 是否已连接。
- `list`：列出浏览器中已安装的 userscript；支持 `--pattern` 和重复的 `--include-pattern`。
- `get <path> --output <file>`：读取脚本内容并写入本地文件；`path` 来自 `list` 输出。不要直接把脚本文本输出到终端。
- `put <file>`：创建新 userscript。
- `patch <path> <file>`：用本地文件覆盖已有 userscript。
- `delete <path>`：删除指定 userscript。
- `shutdown`：请求 `serve` 进程退出。

## 注意事项

- `serve` 只生成一次 connection code；后续命令通过同一个 socket 复用连接。
- `path` 是 Tampermonkey Editors 返回的内部路径，通常形如 `<script-id>/source`，不要自己猜。
- `get` 必须指定 `--output`；读取后用 `sed`、`rg`、`diff`、编辑器等常规文件工具查看内容。
- `put`、`patch` 和 `delete` 会修改浏览器里的 Tampermonkey 脚本；执行前确认目标文件内容是最终版本。
- 如果 `put` 或 `delete` 返回 `405 Method Not Allowed`，这是 Tampermonkey Editors 端拒绝该 action；先在 Tampermonkey UI 中手动创建脚本，再用 `list` 找到 path，并用 `patch` 覆盖内容。
- 如果命令提示无法连接 socket，先运行 `serve` 并完成 Tampermonkey Editors 连接。

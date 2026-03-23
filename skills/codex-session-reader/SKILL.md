---
name: codex-session-reader
description: 读取 Codex 的单个 session/thread；当已知 thread id 且需要查看或摘要会话内容时使用。
---

只读查看单个 Codex session/thread 的 skill，底层通过 `codex app-server` 官方接口读取。

默认输出全部 turns；如只想看局部，可用 `--turns` 传 0-based、接近 Python 的切片表达式。

## Quick start

```bash
cd skills/codex-session-reader
./scripts/codex_session_reader.py read <thread-id>
```

## 环境注意事项

- 这个 skill 依赖本机可直接执行的 `codex` 命令，底层会调用 `codex app-server`。
- 对当前 Codex 环境，工具执行不一定沿用交互式 `fish`，可能回退到 `zsh -lc`。
- 所以只在 `fish` 里设置 `PNPM_HOME` 不够；必须让 `zsh` 启动时的 `PATH` 里也包含 `PNPM_HOME`，否则会报“未找到 `codex`”。
- 推荐按 pnpm 官方风格在 zsh 配置里同时设置：

```zsh
export PNPM_HOME="$HOME/Library/pnpm"
case ":$PATH:" in
  *":$PNPM_HOME:"*) ;;
  *) export PATH="$PNPM_HOME:$PATH" ;;
esac
```

## 何时使用

- 用户要求查看某个 Codex thread/session。
- 用户给出 thread id，希望读取完整上下文。
- 需要把某个 Codex 会话内容转成可继续摘要或分析的 Markdown。

## 常用命令

```bash
./scripts/codex_session_reader.py read <thread-id>                    # 读取完整 thread
./scripts/codex_session_reader.py read <thread-id> --preview-only     # 只看 preview 和元信息
./scripts/codex_session_reader.py read <thread-id> --turns :5         # 前 5 个 turns
./scripts/codex_session_reader.py read <thread-id> --turns -5:        # 后 5 个 turns
./scripts/codex_session_reader.py read <thread-id> --turns 10:-1      # 从第 10 个到倒数第 1 个之前
./scripts/codex_session_reader.py read <thread-id> --turns 13         # 只看第 13 个 turn
./scripts/codex_session_reader.py read <thread-id> --turns 13:15      # 读取第 13 到第 14 个 turns
./scripts/codex_session_reader.py read <thread-id> --format json      # 输出 JSON
```

## 输出约定

- 默认输出 `markdown`，适合继续交给 Codex 阅读或摘要。
- 默认输出全部 turns。
- `--format json` 输出 app-server 返回的结构化结果，便于脚本处理。
- 若发生区间裁剪，JSON 会额外包含 `truncated` 字段说明实际输出的是哪一段。
- `--turns` 不支持 step；`1:10:2` 这类表达式会报错。

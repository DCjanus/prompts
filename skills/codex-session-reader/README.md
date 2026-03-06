# codex-session-reader

一个仅面向 Codex 的只读 session/thread 阅读 skill。

## 作用

这个 skill 用来读取单个 Codex thread。

实现上只支持 Codex，并通过 `codex app-server` 的官方 JSON-RPC 接口交互，不解析 `~/.codex` 下的 rollout JSONL 或 sqlite。当前范围也刻意收窄为只读，不提供 thread 写入、续写、fork 或归档能力；读取区间则通过 `--turns` 的 0-based 切片表达式控制。

## 来历

这个 skill 的问题定义与使用体验明显受到 [Xuanwo/xurl](https://github.com/Xuanwo/xurl) 启发，尤其是“把 agent/thread 读取包装成一个可直接给 Codex 使用的能力”这一点。

但当前实现没有复用 xurl 的 Rust 多 provider 架构，也没有沿用它的本地 session 解析逻辑；这里改为只支持 Codex，并通过 Codex 官方 `app-server` 的 `thread/list`、`thread/read` 等接口读取数据，以尽量降低对底层持久化格式的耦合。

`xurl` 使用 Apache 2.0 许可：
- [Xuanwo/xurl](https://github.com/Xuanwo/xurl)
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)

## 文件

- [SKILL.md](SKILL.md)：给 agent 的使用说明与命令约定
- [codex_session_reader.py](scripts/codex_session_reader.py)：实际 CLI 实现

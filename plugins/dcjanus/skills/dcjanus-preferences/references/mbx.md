# mbx 与 Cargo

mbx 为 Rust 构建提供跨项目、跨 worktree 的共享缓存，并管理构建产物的磁盘占用。日常继续输入 `cargo build`、`cargo test` 和 `cargo clippy`；mbx 的 Cargo shim 转交命令给 mbx，再由 Cargo 执行原有工作。缓存管理使用 `mbx stats`、`mbx tui`、`mbx gc --dry-run` 等命令。项目已指定构建入口时遵循项目约定。

## 安装与接入

先通过 rustup 安装项目要求的 Rust 工具链。已有 `cargo-binstall` 时优先安装 mbx 的预编译版本；否则直接用 Cargo 安装，不为 mbx 单独安装 `cargo-binstall`：

```sh
if command -v cargo-binstall >/dev/null 2>&1; then
  cargo binstall mbx --no-confirm
else
  cargo install mbx --locked
fi
mbx --version
env -u MISE_SHELL -u MISE_CONFIG_FILE mbx setup
```

清除 mise 的激活环境变量，可让 `mbx setup` 安装自带的稳定 Cargo shim，而不改动 mise 配置。setup 还会为 rust-analyzer 配置使用该 shim 的后台检查。setup 会提示 shim 路径和当前 shell 的 PATH 写法；之后也可用 `mbx setup --status` 查看 shim 路径。以下配置一律使用它报告的目录，不推测系统默认路径。

### zsh

把 setup 报告的 shim 目录放到 `~/.zshenv` 的 PATH 前端，让 Codex 等非交互 zsh 进程也能使用。若 `~/.zshrc` 会运行 `mise activate zsh`，在它之后再次把同一目录置于 PATH 前端，确保交互 shell 中的优先级。

### fish

在 `~/.config/fish/config.fish` 中用 `fish_add_path --path --move --prepend` 将 setup 报告的 shim 目录置于 PATH 前端；若启用了 `mise activate fish | source`，把这一行放在它之后。`--path` 只调整当前进程的 PATH，避免把路径永久写进 fish 的通用变量。

安装 fish 补全：

```sh
mkdir -p "$HOME/.config/fish/completions"
mbx completion fish > "$HOME/.config/fish/completions/mbx.fish"
```

## 验证与日常使用

新开 fish 和 zsh 进程分别运行 `command -s cargo`（fish）或 `command -v cargo`（zsh），应得到 mbx setup 输出的 shim 路径；`mbx` 应来自独立安装目录。再运行：

```sh
env -u MISE_SHELL -u MISE_CONFIG_FILE mbx setup --status
mbx doctor
cargo build
```

`setup --status` 应报告 shim 已安装且为当前版本，`doctor` 的 setup 检查应通过。日常仍用 `cargo`；需要查看缓存节省量时用 `mbx stats`，预览清理时用 `mbx gc --dry-run`。升级时按是否已有 `cargo-binstall` 选择上述安装命令；稳定 shim 会跟随新的 mbx 可执行文件。

更多设置见 [mbx 安装文档](https://mr-boxington.jdx.dev/installation) 和 [setup 文档](https://mr-boxington.jdx.dev/setup)。

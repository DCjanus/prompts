# 开发工具与用户数据目录

- 自己编写且可决定文件布局的用户级程序，尽量遵循上游的 [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)；包括在 macOS 上运行的个人 CLI 和脚本。macOS/Windows 原生应用、项目内文件及已有路径契约按相应平台或项目约定处理，不机械迁移。
- 项目开发工具及运行时版本优先使用 mise 管理，在 `mise.toml` 中共享配置；Rust 工具链默认使用 rustup 和项目级 `rust-toolchain.toml` 管理，不在 mise 中重复声明。已有工具链和语言包管理器沿用项目约定。

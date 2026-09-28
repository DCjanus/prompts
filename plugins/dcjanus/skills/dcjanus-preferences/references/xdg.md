# 用户级程序的 XDG 目录偏好

为自己维护、可自行决定文件布局的用户级 CLI、脚本和开发工具，默认采用 [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/0.8/)。这也是 macOS 上此类个人工具的偏好；不要把它解释成所有平台和应用都必须使用 XDG。

| 用途 | 环境变量 | 未设置时的目录 |
| --- | --- | --- |
| 用户配置 | `XDG_CONFIG_HOME` | `~/.config` |
| 需要保留的应用数据 | `XDG_DATA_HOME` | `~/.local/share` |
| 跨启动保留的本机状态，如历史和日志 | `XDG_STATE_HOME` | `~/.local/state` |
| 可重新生成的缓存 | `XDG_CACHE_HOME` | `~/.cache` |
| 会话期 socket、锁和临时运行文件 | `XDG_RUNTIME_DIR` | 无固定家目录默认值；只在目录可用且满足生命周期与权限要求时使用 |

- 在 base directory 下使用能识别程序的子目录。读取 XDG 环境变量时只接受绝对路径；未设置、空值或相对路径时使用对应规范默认值。`XDG_RUNTIME_DIR` 缺失时按运行环境选择安全的临时目录，不把会话期文件持久化到 state 或 cache。日志轮转、保留期和容量限制由程序自行定义，目录规范不代替这些策略。
- 用户主动选择的文档和输出文件、仓库内约定的配置与构建产物，按用户指定位置或项目工具链放置；现有程序的路径契约与迁移成本优先于统一目录形式。系统级服务、容器和受部署系统管理的文件按其服务规范处理。
- 原生 macOS GUI 或沙盒应用优先使用 Apple 的 [`Library` 与应用容器约定](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/MacOSXDirectories/MacOSXDirectories.html)；Windows 原生应用使用系统提供的[应用数据目录](https://learn.microsoft.com/en-us/windows/apps/develop/files/file-access-permissions)。跨平台程序分别适配目标平台，不在这些环境中强行套用 Unix 家目录。

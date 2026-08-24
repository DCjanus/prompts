这个仓库只是我个人在 Codex 中使用的提示词备份，内容会根据日常需求随时增删，未必完整，也不保证对所有场景都适用。如果你正好有类似需求，欢迎参考或复制现有结构自行扩展。

目前仓库只保留与 Codex 直接相关的提示词与技能说明：早期为 Cursor 准备的内容已经删除，若需要历史记录可参考 [deprecated/cursor](https://github.com/DCjanus/prompts/releases/tag/deprecated%2Fcursor) 归档。

技能编写可参考 Claude 官方的 [技能创作最佳实践](https://platform.claude.com/docs/zh-CN/agents-and-tools/agent-skills/best-practices) 文档。

## 使用方式

我当前在 fish 里使用两条 Codex alias（定义在 `~/.config/fish/config.fish`）：

```fish
alias codex='env EDITOR="zed --wait --new" command codex'
alias codex_tmp='env EDITOR="zed --wait --new" command codex -C /tmp'
```

这样配置的原因：

- `EDITOR="zed --wait --new"`：让 Codex 在需要打开编辑器时统一使用 zed，并等待编辑器关闭后再继续，便于我直接用鼠标做复制粘贴和局部修改。
- `codex_tmp` 额外带上 `-C /tmp`：需要临时开新会话、做一次性实验或避免把工作目录绑在当前仓库时，我会直接切到 `/tmp` 启动。

日常开发中经常需要复制文件或目录的绝对路径，因此我还在 fish 中定义了一个 `pcp` 函数：

```fish
function pcp --description 'Copy absolute path to clipboard without trailing newline'
    printf %s (realpath -- $argv) | pbcopy
end
```

例如，在仓库根目录执行：

```fish
pcp README.md
pcp skills/
pcp .
```

`pcp` 会先通过 `realpath` 将传入的单个文件或目录转换成规范化的绝对路径，再用 `pbcopy` 将结果写入系统剪贴板；`printf %s` 可以避免复制结果末尾带上换行。路径包含空格时，需要使用引号或 fish 的转义语法。由于该函数依赖 macOS 自带的 `pbcopy`，因此仅适用于 macOS。

我当前在 `~/.codex/config.toml` 里还会额外配置 TUI 主题和通知：

```toml
sandbox_mode = "danger-full-access"
approval_policy = "never"

[tui]
theme = "dracula"
notifications = true
notification_method = "bel"
```

这样配置的原因：

- `sandbox_mode = "danger-full-access"` 与 `approval_policy = "never"`：把 Codex 的高权限执行行为集中放在配置文件里，alias 只负责设置编辑器与工作目录，方便同步到其它设备。
- `theme = "dracula"`：和我平时在终端与编辑器里的配色更接近，切到 Codex TUI 时视觉更统一。
- 我平时使用 Ghostty。对我来说，`bel` 比默认的 `auto` 更直观，因为 Ghostty 会在标签页标题栏展示一个 `🔔` 标记。
- 并行开多个 Codex tab 做任务时，我可以很快看出哪些 tab 已经有通知、哪些任务已经就绪，不用来回切换逐个确认。

## 运行前提

本仓库内的所有脚本与 skills 默认假设当前环境已安装最新版 [`uv`](https://github.com/astral-sh/uv)。

## 仓库结构

- [`AGENTS.md`](AGENTS.md)：Codex 中所有代理共享的基础约束与工作流
- [`skills/`](skills)：按功能分类的技能库，详情见下方技能列表
- [`scripts/`](scripts)：放置 uv script 模式的工具脚本（规范见 [SKILL.md（uv-cli-creator）](skills/uv-cli-creator/SKILL.md)）
  - [`chatgpt_usage.py`](scripts/chatgpt_usage.py)：复用本机 Codex CLI 的 ChatGPT 登录态，展示 Codex 额度窗口，并通过 DuckDB 增量索引活跃与已归档 Thread，统计最近 7 天 Token 用量和每日输入缓存命中率；自动在支持 Kitty 图片协议的终端中展示图片看板，其它环境回退到紧凑 Rich 输出
  - [`run_tests.py`](scripts/run_tests.py)：统一发现并运行仓库内所有脚本与 skill 的 Python 测试，同时兼容 unittest 与 pytest 测试
  - [`script_deps.py`](scripts/script_deps.py)：检查或升级仓库内 PEP 723 / uv script 依赖声明，对比 PyPI 最新版本，并在 GitHub Actions 中报告依赖下限落后或声明不一致
  - [`upstream_skills.py`](scripts/upstream_skills.py)：根据 [`upstream-skills.toml`](upstream-skills.toml) 检查第三方 skill 的上游目录是否出现新 commit；优先使用 CI 的 `GITHUB_TOKEN`，本地回退到已登录的 `gh`，并在 stderr 输出凭据来源；发现变更或查询失败时返回非 0，并写入 GitHub Actions summary

额度看板会结合 TTY 状态与 Ghostty、Kitty 等终端标识自动选择图片模式；图片渲染失败时自动回退到原有 Rich 文本界面。默认省略低使用频率的 Codex Spark 额度桶，`--verbose` 仍可查看服务端返回的完整额度与本地索引命中情况。本地用量索引默认保存在系统缓存目录，DuckDB 数据使用 zstd 压缩；归档 rename 只更新路径，未变化的 Thread 不重扫，追加内容只解析新增字节，并按 Thread 与日期聚合后落盘。`--history-days` 可选择 1–365 天，默认 7 天；缓存覆盖范围只扩不缩，首次请求更长范围时补建一次，之后切回较短范围不会重复扫描。

图片默认使用除行尾一列外的可用终端宽度，避免 Unicode placeholder 触发额外自动换行，也可用 `--image-width` 指定列数。默认看板把最近 7 天用量放在主体位置，以等高日期卡展示 Token 和缓存命中率，额度窗口压缩为下方摘要；`--verbose` 则恢复多模型双轨对比与精确诊断。uv 会自动安装 `resvg_py` 与 `kittytgp`，不要求宿主机额外安装 SVG 转换器或图片查看器。SVG 默认以 2× 像素密度栅格化，在高分屏上保持清晰，同时由终端按 cell placement 控制实际显示尺寸。`kittytgp` 使用 Kitty Graphics Protocol 的 Unicode placeholder placement，使图片能够随终端文本滚动，并兼容已开启 passthrough 的 tmux：

```bash
./scripts/chatgpt_usage.py
./scripts/chatgpt_usage.py --text
./scripts/chatgpt_usage.py --history-days 30
./scripts/chatgpt_usage.py --text --verbose
./scripts/chatgpt_usage.py --image --image-width 72
./scripts/chatgpt_usage.py --image --save-svg /tmp/chatgpt-usage.svg
```

`--image` 与 `--text` 可分别强制使用图片或文本输出；`--save-svg` 可独立保存原始矢量图。

### 技能列表

| 技能 | 说明 |
| --- | --- |
| [`codex-session-reader`](skills/codex-session-reader/SKILL.md) | 读取 Codex 的单个 session/thread；当已知 thread id 且需要查看或摘要会话内容时使用。 |
| [`codex-thread-namer`](skills/codex-thread-namer/SKILL.md) | 为当前 Codex thread 设置名称；默认根据上下文直接重命名，仅在用户明确要求时提供候选名。 |
| [`confluence-cli`](skills/confluence-cli/SKILL.md) | 查询、检索与阅读 Confluence 文档/页面。 |
| [`jira-cli`](skills/jira-cli/SKILL.md) | 通过内置 Python CLI 查询和管理 Jira Issue、Saved Filter、流转与评论。 |
| [`uv-cli-creator`](skills/uv-cli-creator/SKILL.md) | 创建或修改基于 PEP 723、由 `uv run --script` 管理的单文件 Python CLI，并在环境支持时提供直接执行入口。 |
| [`dcjanus-preferences`](skills/dcjanus-preferences/SKILL.md) | 记录 DCjanus 在不同语言中偏好的第三方库与使用场景，供 AI 在选型、引入依赖或替换库时优先参考。适用于 Python/Rust/Go 的库选择、技术方案对比、或需要遵循 DCjanus 个人偏好进行开发的场景。 |
| [`domain-modeling`](skills/domain-modeling/SKILL.md) | 构建并持续校准领域模型，明确领域术语与边界，并在必要时记录重要架构决策。 |
| [`fetch-url`](skills/fetch-url/SKILL.md) | 获取并提取链接正文（默认 Markdown）；内置 X/Twitter URL 处理，提升受限页面的抓取成功率。 |
| [`review-fix-loop`](skills/review-fix-loop/SKILL.md) | 用三个相互隔离的干净 subagent 并行做代码审查，由主 agent 判断审查意见价值、修复有效问题并提交推送，直到同一批三个 reviewer 都没有有价值审查意见；仅在显式调用时启用。 |
| [`repository-workflow`](skills/repository-workflow/SKILL.md) | 处理从本地 Git 变更到 GitHub/GitLab 协作发布的完整流程，包括语义化提交、Issue/PR/MR 文案与 inline review reply。 |
| [`github-cli`](skills/github-cli/SKILL.md) | GitHub CLI 使用指引，面向 GitHub 资源交互（如 repo、issue、PR、comment、release、workflow） |
| [`gitlab-cli`](skills/gitlab-cli/SKILL.md) | GitLab CLI（glab）使用指引，面向 GitLab 资源交互（如 project、issue、MR、comment、wiki） |
| [`grill-me`](skills/grill-me/SKILL.md) | 针对计划、决策或想法按决策树前沿分轮追问，对用户的思路做压力测试；仅在显式调用时启用。 |
| [`teach-me`](skills/teach-me/SKILL.md) | 以学习者控制的节奏自顶向下逐层讲解复杂主题，每轮只展开一个概念并等待追问；仅在显式调用时启用。 |
| [`golang-lo`](skills/golang-lo/SKILL.md) | Go >= 1.18 项目中希望用 samber/lo（Lodash 风格泛型库）简化集合/映射/字符串、错误处理、重试/节流/防抖、通道并发或指针空值场景时使用。 |
| [`upstream-pr-staging`](skills/upstream-pr-staging/SKILL.md) | 为 GitHub 上游 PR 先创建 fork 内部 draft、低干扰收敛方案与 CI；必要时构造 red/green 回归测试证据链。 |
| [`ticktick-cli`](skills/ticktick-cli/SKILL.md) | 使用 Python CLI 与 Dida365 Open API 交互以管理滴答清单任务/项目，适用于需要通过脚本或命令行调用滴答清单接口的场景（如项目/任务的查询、创建、更新、完成、删除）。 |
| [`tampermonkey-cli`](skills/tampermonkey-cli/SKILL.md) | 通过 Tampermonkey Editors 管理浏览器里的 Tampermonkey userscript，支持安装、更新、读取、列出和删除脚本。 |

## 第三方来源与许可

### grill-me

本仓库中的 [`grill-me`](skills/grill-me/SKILL.md) 改编自 Matt Pocock 的原始 [`grilling`](https://github.com/mattpocock/skills/blob/85f83d3fde1d3a90d5c9a657f6998c79a6c37308/skills/productivity/grilling/SKILL.md)，基于上游 commit [`85f83d3fde1d3a90d5c9a657f6998c79a6c37308`](https://github.com/mattpocock/skills/commit/85f83d3fde1d3a90d5c9a657f6998c79a6c37308)，按 [MIT License](licenses/grill-me/LICENSE) 使用和修改。

### domain-modeling

本仓库中的 [`domain-modeling`](skills/domain-modeling/SKILL.md) 翻译自 Matt Pocock 的[原始 skill](https://github.com/mattpocock/skills/blob/321658273cb1d20b76026717d027d505790106d4/skills/engineering/domain-modeling/SKILL.md)，基于上游 commit [`321658273cb1d20b76026717d027d505790106d4`](https://github.com/mattpocock/skills/commit/321658273cb1d20b76026717d027d505790106d4)，按 [MIT License](licenses/domain-modeling/LICENSE) 使用和修改。

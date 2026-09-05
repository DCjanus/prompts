这个仓库只是我个人在 Codex 中使用的提示词备份，内容会根据日常需求随时增删，未必完整，也不保证对所有场景都适用。如果你正好有类似需求，欢迎参考或复制现有结构自行扩展。

目前仓库只保留与 Codex 直接相关的提示词与技能说明：早期为 Cursor 准备的内容已经删除，若需要历史记录可参考 [deprecated/cursor](https://github.com/DCjanus/prompts/releases/tag/deprecated%2Fcursor) 归档。

提示词维护参考 OpenAI 官方的 [GPT-6 Astra 提示词建议](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra#prompting-best-practices)和 [AGENTS.md 加载规则](https://developers.openai.com/codex/guides/agents-md)。技能编写遵循 OpenAI 官方的 [skills 编写指南](https://developers.openai.com/codex/skills)。

## 使用方式

本仓库是本机个人提示词的受管来源，不是目标业务项目的规则目录。当前安装方式：

- `~/.codex/AGENTS.md` 软链接到本仓库的 [AGENTS.md](AGENTS.md)，提供跨项目的个人默认。
- `~/.codex/skills` 软链接到本仓库的 [skills](skills)；`~/.agents/skills` 保持为独立目录，容纳其它工具管理的技能，避免自动写入污染本仓库。
- 全局文件只保留个人偏好、工作边界和短路由；操作步骤放入相应 skill，按任务加载，项目的明确约定优先。
- 调用 skill 脚本时，从实际加载的 SKILL.md 定位资源，目标项目单独通过参数指定；不要假设当前目录就是本仓库。

审阅 worktree 或 PR 时，既有软链接仍指向原 checkout。仅修改 worktree 不会切换本机生效版本；采用变更时需同时更新全局文件及其引用的 skills，并在新会话中核对加载结果。仓库根目录也有 AGENTS.md，因此在本仓库工作时可能同时加载全局和项目两份约定。

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

本仓库内的脚本与 skills 默认假设本机已安装 [`uv`](https://github.com/astral-sh/uv)。远端服务器或容器的工具单独核实，沿用目标项目的工具链，不从本机安装情况推断远端环境。

## 仓库结构

- [`AGENTS.md`](AGENTS.md)：本机跨项目的个人默认、工作边界和按需 skill 路由
- [`skills/`](skills)：按功能分类的技能库，详情见下方技能列表
- [`scripts/`](scripts)：放置 uv script 模式的工具脚本（规范见 [SKILL.md（uv-cli-creator）](skills/uv-cli-creator/SKILL.md)）
  - [`chatgpt_usage.py`](scripts/chatgpt_usage.py)：复用本机 Codex CLI 的 ChatGPT 登录态，展示 Codex 额度窗口，并通过 DuckDB 增量索引活跃与已归档 Thread，统计最近 7 天 Token 用量、每日输入缓存命中率和按当前标准 API 单价折算的美元成本；自动在支持 Kitty 图片协议的终端中展示图片看板，其它环境回退到紧凑 Rich 输出
  - [`run_tests.py`](scripts/run_tests.py)：统一发现并运行仓库内所有脚本与 skill 的 Python 测试，同时兼容 unittest 与 pytest 测试
  - [`script_deps.py`](scripts/script_deps.py)：检查或升级仓库内 PEP 723 / uv script 依赖声明，对比 PyPI 最新版本，并在 GitHub Actions 中报告依赖下限落后或声明不一致
  - [`upstream_skills.py`](scripts/upstream_skills.py)：根据 [`upstream-skills.toml`](upstream-skills.toml) 检查第三方 skill 的上游目录是否出现新 commit；优先使用 CI 的 `GITHUB_TOKEN`，本地回退到已登录的 `gh`，并在 stderr 输出凭据来源；发现变更或查询失败时返回非 0，并写入 GitHub Actions summary

额度看板会结合 TTY 状态与 Ghostty、Kitty 等终端标识自动选择图片模式；图片渲染失败时自动回退到原有 Rich 文本界面。默认省略低使用频率的 Codex Spark 额度桶，`--verbose` 仍可查看服务端返回的完整额度与本地索引命中情况；额度消耗快于时间进度时，还会提示预计休息多久可以恢复持平。看板同时展示当前可用的 Bank Reset 次数，以及按到期时间排序的最近 3 个可用 Reset。本地用量索引默认保存在系统缓存目录，DuckDB 数据使用 zstd 压缩；归档 rename 只更新路径，未变化的 Thread 不重扫，追加内容只解析新增字节。首次建索引时会在有界线程池中按 Thread 并行扫描，并按固定大小事件批次提交；中断后只重建未完成的 Thread，不会用一个覆盖全部历史的大事务占满内存。`--history-days` 可选择 1–365 天，默认 7 天；缓存覆盖范围只扩不缩，首次请求更长范围时补建一次，之后切回较短范围不会重复扫描。

金额是根据本地 rollout 中记录的模型、service tier、普通输入、缓存命中、缓存写入和输出 Token，按当前 OpenAI API 单价计算出的等价成本；它用于比较用量价值，不代表 ChatGPT/Codex 订阅的实际账单。脚本优先从 [models.dev](https://models.dev/) 更新价格目录并缓存 24 小时，响应不完整或网络不可用时会依次使用过期缓存和内置价格，因此离线运行不会影响 Token 统计。每次展示时都会用当前价格重算已缓存的逐请求 Token 事实，价格更新不需要重新扫描 rollout；`priority` / Fast 请求在官方已公布价格时会应用对应费率，`--json` 同时区分 Fast 与非 Fast Token。单次请求输入超过 272K Token 时，对已公布长上下文价格的模型按整次请求的长上下文单价估算；未知模型不会套用猜测价格，JSON 输出会保留对应模型明细与未估价 Token 数。

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
| [`python-execution`](skills/python-execution/SKILL.md) | 使用 PEP 723 保存临时 Python 脚本依赖，统一通过 uv run --script 执行，并处理目标环境和格式/lint 检查。 |
| [`dependency-management`](skills/dependency-management/SKILL.md) | 按项目工具链管理依赖与项目版本，核对 manifest 和锁文件的变更范围。 |
| [`dcjanus-preferences`](skills/dcjanus-preferences/SKILL.md) | 记录 DCjanus 的跨语言技术选型、哈希与无序集合摘要、Protobuf 契约以及 Python/Rust/Go 第三方库偏好，适用于存储、分析、压缩、归档、协议设计、依赖选择与技术方案对比。 |
| [`domain-modeling`](skills/domain-modeling/SKILL.md) | 构建并持续校准领域模型，明确领域术语与边界，并在必要时记录重要架构决策。 |
| [`fetch-url`](skills/fetch-url/SKILL.md) | 获取并提取链接正文（默认 Markdown）；内置 X/Twitter URL 处理，提升受限页面的抓取成功率。 |
| [`google-mail-cli`](skills/google-mail-cli/SKILL.md) | 使用 Gmail API 搜索和读取邮件、整理标签、管理草稿、发送邮件及配置过滤规则。 |
| [`google-calendar-cli`](skills/google-calendar-cli/SKILL.md) | 使用 Google Calendar API 查看日历和事件、查询空闲忙碌时间，以及创建、更新或删除事件。 |
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
| [`notify-via-telegram`](skills/notify-via-telegram/SKILL.md) | 在用户明确订阅后，通过本地安全配置发送当前长任务的最终结果或待处理 Telegram 通知。 |

## 第三方来源与许可

### grill-me

本仓库中的 [`grill-me`](skills/grill-me/SKILL.md) 改编自 Matt Pocock 的原始 [`grilling`](https://github.com/mattpocock/skills/blob/85f83d3fde1d3a90d5c9a657f6998c79a6c37308/skills/productivity/grilling/SKILL.md)，基于上游 commit [`85f83d3fde1d3a90d5c9a657f6998c79a6c37308`](https://github.com/mattpocock/skills/commit/85f83d3fde1d3a90d5c9a657f6998c79a6c37308)，按 [MIT License](licenses/grill-me/LICENSE) 使用和修改。

### domain-modeling

本仓库中的 [`domain-modeling`](skills/domain-modeling/SKILL.md) 翻译自 Matt Pocock 的[原始 skill](https://github.com/mattpocock/skills/blob/321658273cb1d20b76026717d027d505790106d4/skills/engineering/domain-modeling/SKILL.md)，基于上游 commit [`321658273cb1d20b76026717d027d505790106d4`](https://github.com/mattpocock/skills/commit/321658273cb1d20b76026717d027d505790106d4)，按 [MIT License](licenses/domain-modeling/LICENSE) 使用和修改。

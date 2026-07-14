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
  - [`token_count.py`](scripts/token_count.py)：基于 [tiktoken](https://github.com/openai/tiktoken) 的 token 计数 CLI
  - [`token_tree.py`](scripts/token_tree.py)：统计仓库内所有 Git 跟踪文本文件的 token 数，按树状结构输出；支持全局比例进度条、对齐条形显示与百分比，可用 `--bar-width` 调整条形宽度
  - [`codex_usage.py`](scripts/codex_usage.py)：统计 Codex JSONL session 的 token 用量和预估价格，默认同时读取 `~/.codex/sessions` 与 `~/.codex/archived_sessions`，价格信息缓存到 XDG cache 且最多复用 7 天
  - [`install_codex_cli.py`](scripts/install_codex_cli.py)：从 [openai/codex](https://github.com/openai/codex/releases) 最新 release 下载当前平台的 Codex CLI 预编译 binary，安装到用户级 XDG binary 目录，并为当前 shell 同步安装 Codex completion；可用 `--completion-shell fish` 显式指定目标 shell，可跳过下载时复用本地状态
  - [`script_deps.py`](scripts/script_deps.py)：检查或升级仓库内 PEP 723 / uv script 依赖声明，对比 PyPI 最新版本，并在 GitHub Actions 中报告依赖下限落后或声明不一致
  - [`upstream_skills.py`](scripts/upstream_skills.py)：根据 [`upstream-skills.toml`](upstream-skills.toml) 检查第三方 skill 的上游目录是否出现新 commit；发现变更或查询失败时返回非 0，并写入 GitHub Actions summary

### 技能列表

| 技能 | 说明 |
| --- | --- |
| [`codex-thread-renamer`](skills/codex-thread-renamer/SKILL.md) | 为当前 Codex thread 设置名称；默认根据上下文直接重命名，仅在用户明确要求时提供候选名。 |
| [`confluence-cli`](skills/confluence-cli/SKILL.md) | 查询、检索与阅读 Confluence 文档/页面。 |
| [`uv-cli-creator`](skills/uv-cli-creator/SKILL.md) | 为本仓库创建或修改 uv --script 风格的 Python CLI；当需要把重复命令封装成 `./scripts/...` 直接执行的工具时使用。 |
| [`dcjanus-preferences`](skills/dcjanus-preferences/SKILL.md) | 记录 DCjanus 在不同语言中偏好的第三方库与使用场景，供 AI 在选型、引入依赖或替换库时优先参考。适用于 Python/Rust/Go 的库选择、技术方案对比、或需要遵循 DCjanus 个人偏好进行开发的场景。 |
| [`domain-modeling`](skills/domain-modeling/SKILL.md) | 构建并持续校准领域模型，明确领域术语与边界，并在必要时记录重要架构决策。 |
| [`fetch-url`](skills/fetch-url/SKILL.md) | 获取并提取链接正文（默认 Markdown）；内置 X/Twitter URL 处理，提升受限页面的抓取成功率。 |
| [`change-request-writing`](skills/change-request-writing/SKILL.md) | 编写或更新 GitHub/GitLab Issue、PR、MR 的标题与正文；聚焦 final net diff、Breaking Change、避免低价值验证噪声与本地路径泄露。 |
| [`review-fix-loop`](skills/review-fix-loop/SKILL.md) | 用三个相互隔离的干净 subagent 并行做代码审查，由主 agent 判断审查意见价值、修复有效问题并提交推送，直到同一批三个 reviewer 都没有有价值审查意见。 |
| [`git-workflow`](skills/git-workflow/SKILL.md) | 处理 git 提交、推送、分支命名与提交信息规范；当任务涉及 commit、push、起分支或整理 commit message 时使用。 |
| [`github-cli`](skills/github-cli/SKILL.md) | GitHub CLI 使用指引，面向 GitHub 资源交互（如 repo、issue、PR、comment、release、workflow） |
| [`gitlab-cli`](skills/gitlab-cli/SKILL.md) | GitLab CLI（glab）使用指引，面向 GitLab 资源交互（如 project、issue、MR、comment、wiki） |
| [`grilling`](skills/grilling/SKILL.md) | 针对计划、决策或想法逐项深入追问，每次聚焦一个问题，对用户的思路做压力测试。 |
| [`golang-lo`](skills/golang-lo/SKILL.md) | Go >= 1.18 项目中希望用 samber/lo（Lodash 风格泛型库）简化集合/映射/字符串、错误处理、重试/节流/防抖、通道并发或指针空值场景时使用。 |
| [`upstream-pr-staging`](skills/upstream-pr-staging/SKILL.md) | 为 GitHub 上游 PR 先创建 fork 内部 draft、低干扰收敛方案与 CI；必要时构造 red/green 回归测试证据链。 |
| [`ticktick-cli`](skills/ticktick-cli/SKILL.md) | 使用 Python CLI 与 Dida365 Open API 交互以管理滴答清单任务/项目，适用于需要通过脚本或命令行调用滴答清单接口的场景（如项目/任务的查询、创建、更新、完成、删除）。 |
| [`tampermonkey-cli`](skills/tampermonkey-cli/SKILL.md) | 通过 Tampermonkey Editors 管理浏览器里的 Tampermonkey userscript，支持安装、更新、读取、列出和删除脚本。 |

## 第三方来源与许可

### grilling

本仓库中的 [`grilling`](skills/grilling/SKILL.md) 翻译自 Matt Pocock 的[原始 skill](https://github.com/mattpocock/skills/blob/697d4ce9742da558fd1ba6697c8e9775e2e302dd/skills/productivity/grilling/SKILL.md)，基于上游 commit [`697d4ce9742da558fd1ba6697c8e9775e2e302dd`](https://github.com/mattpocock/skills/commit/697d4ce9742da558fd1ba6697c8e9775e2e302dd)，按 [MIT License](licenses/grilling/LICENSE) 使用和修改。

### domain-modeling

本仓库中的 [`domain-modeling`](skills/domain-modeling/SKILL.md) 翻译自 Matt Pocock 的[原始 skill](https://github.com/mattpocock/skills/blob/697d4ce9742da558fd1ba6697c8e9775e2e302dd/skills/engineering/domain-modeling/SKILL.md)，基于上游 commit [`697d4ce9742da558fd1ba6697c8e9775e2e302dd`](https://github.com/mattpocock/skills/commit/697d4ce9742da558fd1ba6697c8e9775e2e302dd)，按 [MIT License](licenses/domain-modeling/LICENSE) 使用和修改。

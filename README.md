这个仓库只是我个人在 Codex 中使用的提示词备份，内容会根据日常需求随时增删，未必完整，也不保证对所有场景都适用。如果你正好有类似需求，欢迎参考或复制现有结构自行扩展。

目前仓库只保留与 Codex 直接相关的提示词与技能说明：早期为 Cursor 准备的内容已经删除，若需要历史记录可参考 [deprecated/cursor](https://github.com/DCjanus/prompts/releases/tag/deprecated%2Fcursor) 归档。

技能编写可参考 Claude 官方的 [技能创作最佳实践](https://platform.claude.com/docs/zh-CN/agents-and-tools/agent-skills/best-practices) 文档。

## 使用方式

我当前在 fish 里使用两条 Codex alias（定义在 `~/.config/fish/config.fish`）：

```fish
alias codex='env EDITOR="zed --wait --new" command codex --dangerously-bypass-approvals-and-sandbox'
alias codex_tmp='env EDITOR="zed --wait --new" command codex --dangerously-bypass-approvals-and-sandbox -C /tmp'
```

这样配置的原因：

- `EDITOR="zed --wait --new"`：让 Codex 在需要打开编辑器时统一使用 zed，并等待编辑器关闭后再继续，便于我直接用鼠标做复制粘贴和局部修改。
- `codex_tmp` 额外带上 `-C /tmp`：需要临时开新会话、做一次性实验或避免把工作目录绑在当前仓库时，我会直接切到 `/tmp` 启动。

我当前在 `~/.codex/config.toml` 里还会额外配置 TUI 主题和通知：

```toml
[tui]
theme = "dracula"
notifications = true
notification_method = "bel"
```

这样配置的原因：

- `theme = "dracula"`：和我平时在终端与编辑器里的配色更接近，切到 Codex TUI 时视觉更统一。
- 我平时使用 Ghostty。对我来说，`bel` 比默认的 `auto` 更直观，因为 Ghostty 会在标签页标题栏展示一个 `🔔` 标记。
- 并行开多个 Codex tab 做任务时，我可以很快看出哪些 tab 已经有通知、哪些任务已经就绪，不用来回切换逐个确认。

## 运行前提

本仓库内的所有脚本与 skills 默认假设当前环境已安装最新版 [`uv`](https://github.com/astral-sh/uv)。

## 仓库结构

- [`AGENTS.md`](AGENTS.md)：Codex 中所有代理共享的基础约束与工作流
- [`skills/`](skills)：按功能分类的技能库，详情见下方技能列表
- [`scripts/`](scripts)：放置 uv script 模式的工具脚本（规范见 [SKILL.md（create-skill）](skills/create-skill/SKILL.md) 的 scripts 章节）
  - [`token_count.py`](scripts/token_count.py)：基于 [tiktoken](https://github.com/openai/tiktoken) 的 token 计数 CLI
  - [`token_tree.py`](scripts/token_tree.py)：统计仓库内所有 Git 跟踪文本文件的 token 数，按树状结构输出；支持全局比例进度条、对齐条形显示与百分比，可用 `--bar-width` 调整条形宽度

### 技能列表

| 技能 | 说明 |
| --- | --- |
| [`codex-session-reader`](skills/codex-session-reader/SKILL.md) | 读取 Codex 的单个 session/thread；当已知 thread id 且需要查看或摘要会话内容时使用。 |
| [`confluence-cli`](skills/confluence-cli/SKILL.md) | 查询、检索与阅读 Confluence 文档/页面。 |
| [`create-skill`](skills/create-skill/SKILL.md) | 当你要创建/新增一个 skill，或重写/更新某个 skill 的 SKILL.md（结构、约定、模板）时使用。 |
| [`dcjanus-preferences`](skills/dcjanus-preferences/SKILL.md) | 记录 DCjanus 在不同语言中偏好的第三方库与使用场景，供 AI 在选型、引入依赖或替换库时优先参考。适用于 Python/Rust/Go 的库选择、技术方案对比、或需要遵循 DCjanus 个人偏好进行开发的场景。 |
| [`fetch-url`](skills/fetch-url/SKILL.md) | 获取并提取链接正文（默认 Markdown）；内置 X/Twitter URL 处理，提升受限页面的抓取成功率。 |
| [`git-commit`](skills/git-commit/SKILL.md) | 处理 git 提交/推送/分支命名与提交信息规范；当任务涉及 commit、push、起分支或整理 commit message 时使用。 |
| [`github-cli`](skills/github-cli/SKILL.md) | GitHub CLI 使用指引，面向 GitHub 资源交互（如 repo、issue、PR、comment、release、workflow） |
| [`gitlab-cli`](skills/gitlab-cli/SKILL.md) | GitLab CLI（glab）使用指引，面向 GitLab 资源交互（如 project、issue、MR、comment、wiki） |
| [`golang-lo`](skills/golang-lo/SKILL.md) | Go >= 1.18 项目中希望用 samber/lo（Lodash 风格泛型库）简化集合/映射/字符串、错误处理、重试/节流/防抖、通道并发或指针空值场景时使用。 |
| [`ticktick-cli`](skills/ticktick-cli/SKILL.md) | 使用 Python CLI 与 Dida365 Open API 交互以管理滴答清单任务/项目，适用于需要通过脚本或命令行调用滴答清单接口的场景（如项目/任务的查询、创建、更新、完成、删除）。 |

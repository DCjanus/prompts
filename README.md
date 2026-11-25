# prompts

一组可在 Codex 和 Antigravity CLI 中使用的 skills，把开发协作、工具操作和个人偏好整理成可以重复使用的工作流。

你可以用它让 Codex 协助处理 GitHub 和 GitLab 上的工作、管理依赖、探索领域模型，或与 Gmail、Google Calendar、Linear 等服务交互。这里也有用于拆解复杂问题、逐步学习和审视方案的 skills。

这套工具根据我的工作方式编写，部分 skill 包含个人偏好或需要单独配置服务凭据。欢迎浏览 [skills 目录](plugins/dcjanus/skills)，挑选适合自己的部分。

## 开始使用

### Codex

需要支持 plugin 命令的 Codex CLI、Git 和 [uv](https://github.com/astral-sh/uv)。安装 marketplace 和 plugin：

```bash
codex plugin marketplace add DCjanus/prompts --ref master
codex plugin add dcjanus@dcjanus-plugins
```

安装后，Codex 可以按任务选择适用的 skill；也可以显式调用，例如 `$dcjanus:github-cli`。使用外部服务的 skill 需要在本机配置相应的凭据和工具。

更新插件：

```bash
codex plugin marketplace upgrade dcjanus-plugins --json
```

### Antigravity CLI

直接从 GitHub 安装同一套 skills：

```bash
agy plugin install https://github.com/DCjanus/prompts/tree/master/plugins/dcjanus
```

在 `agy` 中输入 `/skills` 查看可用技能。部分依赖 Codex 专用命令或工具的工作流需要在 Codex 中运行。

## 其他资源

- [AGENTS.md](AGENTS.md)：我在本机使用的 Agent 工作约定，可单独配置。
- [Codex 用量工具](scripts/chatgpt_usage.py)：查看额度与本地用量。
- [终端字体](docs/terminal-fonts.md)：DCjanus Mono SC 的生成说明。
- [macOS Amphetamine 配置检查](docs/amphetamine-checklist.md)：借助 Computer Use 检查电源相关设置。
- [贡献指南](CONTRIBUTING.md)：开发和依赖维护约定。

## 第三方来源

- [grill-me](plugins/dcjanus/skills/grill-me/SKILL.md) 改编自 Matt Pocock 的 [grilling](https://github.com/mattpocock/skills/blob/7739eaed7f8f3915437a8def198a6d0d7206dbc7/skills/productivity/grilling/SKILL.md)，按 [MIT License](plugins/dcjanus/licenses/grill-me/LICENSE) 使用。
- [domain-modeling](plugins/dcjanus/skills/domain-modeling/SKILL.md) 翻译自 Matt Pocock 的 [domain-modeling](https://github.com/mattpocock/skills/blob/2b7ab8c9471fad3fca0a9c0c9e1f52153408172b/skills/engineering/domain-modeling/SKILL.md)，按 [MIT License](plugins/dcjanus/licenses/domain-modeling/LICENSE) 使用。
- [grafana-cli](plugins/dcjanus/skills/grafana-cli/SKILL.md) 复用 Grafana 官方 [gcx skill](https://github.com/grafana/gcx/blob/117b2311909cb3ece0f5f71f10ed5a24823074d6/claude-plugin/skills/gcx/SKILL.md)，按 [Apache License 2.0](plugins/dcjanus/licenses/grafana-cli/LICENSE) 分发。

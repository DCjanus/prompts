# prompts

DCjanus 的个人 skills，既包装为 Codex plugin，也通过同一份 `plugins/dcjanus/skills` 作为原生 Pi package，均借助 Git 在多台电脑上安装和更新。

- [dcjanus](plugins/dcjanus)：plugin 及其 skills、脚本和第三方许可。
- [marketplace.json](.agents/plugins/marketplace.json)：`dcjanus-plugins` marketplace。
- [package.json](package.json)：复用同一套 skills 的 Pi package manifest。
- [AGENTS.md](AGENTS.md)：独立维护的全局个人约定，不由 plugin 自动加载，新电脑按需单独配置。

## 安装与更新

每台电脑需要支持 plugin 命令的 Codex CLI（已验证 `0.153.4`）、Git 和 [uv](https://github.com/astral-sh/uv)。首次安装：

```bash
codex plugin marketplace add DCjanus/prompts --ref master
codex plugin add dcjanus@dcjanus-plugins
```

Codex app-server 启动时会尝试刷新配置的 Git marketplace 及已安装插件；本仓库不安装定时任务。合并 PR 后希望立即更新时运行：

```bash
codex plugin marketplace upgrade dcjanus-plugins --json
```

检查输出中的 `errors`，更新后用新任务验证。内容更新不要求每次修改 plugin 版本号；不要直接编辑安装缓存。外部服务凭据和所需工具仍由各台电脑独立配置。

支持自动触发的 skill 可由 Codex 按需求选择；显式调用使用 `$dcjanus:github-cli` 等完整名称，也可在技能选择器中搜索短名称后选中。

## Pi

同一份 `plugins/dcjanus/skills` 通过 [package.json](package.json) 的 `pi` manifest 作为原生 [Pi](https://pi.dev/) package 分发。每台电脑安装 Pi 后：

```bash
pi install git:github.com/DCjanus/prompts
```

Pi 会加载 `pi.skills` 声明的全部 skill，显式调用使用 `/skill:github-cli` 这样的名称，没有 Codex 的 `$dcjanus:` 命名空间。内容更新后运行 `pi update --extensions`；Pi 只在启动时提示包更新，不会自动应用。Codex 专有的 skill（如 `codex-session-reader`、`codex-thread-namer`）也会被加载，可用 `pi config` 单独关闭。`AGENTS.md` 与 Codex 的情形一致，不由 package 自动加载，需要按需软链到 `~/.pi/agent/AGENTS.md`。

## 开发

开发时修改 Git checkout 并创建 PR；提交前遵循 [贡献指南](CONTRIBUTING.md)，使用 [run_tests.py](scripts/run_tests.py) 运行脚本测试并检查脚本依赖。安装 Codex CLI 后，它还会在独立临时配置中验证插件安装、技能发现与调用入口，以及同版本 Git 更新，不修改日常安装。

## 工具入口

- [chatgpt_usage.py](scripts/chatgpt_usage.py)：查看 Codex 额度与本地用量，本地统计按 provider 拆分（默认 `openai`，可用 `--provider` 切换，`providers` 子命令列出本机可用 provider）。模型价格未知时，终端和 SVG 会标出未估价 Token 与模型；JSON 的 `estimated_cost_usd` 为 `null`，`priced_cost_usd` 仅表示已知价格的小计，`unpriced_models` 列出未估价模型。
- [run_tests.py](scripts/run_tests.py)：运行仓库测试。
- [script_deps.py](scripts/script_deps.py)：检查或升级脚本依赖。
- [upstream_skills.py](scripts/upstream_skills.py)：按 [upstream-skills.toml](upstream-skills.toml) 检查上游 skill 更新。

## 编写指南

提示词参考 OpenAI 官方的 [GPT-6 Astra 提示词建议](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra#prompting-best-practices)和 [AGENTS.md 加载规则](https://developers.openai.com/codex/guides/agents-md)；技能编写遵循 [OpenAI skills 指南](https://developers.openai.com/codex/skills)。

## 第三方来源与许可

- [grill-me](plugins/dcjanus/skills/grill-me/SKILL.md)：改编自 Matt Pocock 的 [grilling](https://github.com/mattpocock/skills/blob/85f83d3fde1d3a90d5c9a657f6998c79a6c37308/skills/productivity/grilling/SKILL.md)，按 [MIT License](plugins/dcjanus/licenses/grill-me/LICENSE) 使用。
- [domain-modeling](plugins/dcjanus/skills/domain-modeling/SKILL.md)：翻译自 Matt Pocock 的 [domain-modeling](https://github.com/mattpocock/skills/blob/321658273cb1d20b76026717d027d505790106d4/skills/engineering/domain-modeling/SKILL.md)，按 [MIT License](plugins/dcjanus/licenses/domain-modeling/LICENSE) 使用。

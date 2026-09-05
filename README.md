# prompts

我在本机 Codex 中使用的个人提示词、skills 和工具脚本，按日常需要维护。

- [AGENTS.md](AGENTS.md)：跨项目的个人默认、工作边界和按需 skill 路由。
- [skills](skills)：各技能的用途、触发条件和约定见其 SKILL.md。
- [scripts](scripts)：额度查看、测试与维护工具。

## 本机安装

- `~/.codex/AGENTS.md` 软链接到本仓库的 [AGENTS.md](AGENTS.md)。
- `~/.codex/skills` 软链接到本仓库的 [skills](skills)。
- `~/.agents/skills` 保持独立，容纳其它工具管理的技能。

本机脚本依赖 [uv](https://github.com/astral-sh/uv)；远端环境单独核实，项目明确约定优先。修改 worktree 不会切换既有软链接指向的生效版本。

## 工具入口

- [chatgpt_usage.py](scripts/chatgpt_usage.py)：查看 Codex 额度与本地用量。
- [run_tests.py](scripts/run_tests.py)：运行仓库测试。
- [script_deps.py](scripts/script_deps.py)：检查或升级脚本依赖。
- [upstream_skills.py](scripts/upstream_skills.py)：按 [upstream-skills.toml](upstream-skills.toml) 检查上游 skill 更新。

## 编写指南

提示词参考 OpenAI 官方的 [GPT-6 Astra 提示词建议](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra#prompting-best-practices)和 [AGENTS.md 加载规则](https://developers.openai.com/codex/guides/agents-md)；技能编写遵循 [OpenAI skills 指南](https://developers.openai.com/codex/skills)。

## 第三方来源与许可

- [grill-me](skills/grill-me/SKILL.md)：改编自 Matt Pocock 的 [grilling](https://github.com/mattpocock/skills/blob/85f83d3fde1d3a90d5c9a657f6998c79a6c37308/skills/productivity/grilling/SKILL.md)，按 [MIT License](licenses/grill-me/LICENSE) 使用。
- [domain-modeling](skills/domain-modeling/SKILL.md)：翻译自 Matt Pocock 的 [domain-modeling](https://github.com/mattpocock/skills/blob/321658273cb1d20b76026717d027d505790106d4/skills/engineering/domain-modeling/SKILL.md)，按 [MIT License](licenses/domain-modeling/LICENSE) 使用。

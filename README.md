这个仓库只是我个人在 Codex 中使用的提示词备份，内容会根据日常需求随时增删，未必完整，也不保证对所有场景都适用。如果你正好有类似需求，欢迎参考或复制现有结构自行扩展。

目前仓库只保留与 Codex 直接相关的提示词与技能说明：早期为 Cursor 准备的内容已经删除，若需要历史记录可参考 [deprecated/cursor](https://github.com/DCjanus/prompts/releases/tag/deprecated%2Fcursor) 归档。

技能编写可参考 Claude 官方的 [技能创作最佳实践](https://platform.claude.com/docs/zh-CN/agents-and-tools/agent-skills/best-practices) 文档。

## 使用方式

我当前在 fish 里使用两条 Codex alias（定义在 `~/.config/fish/config.fish`）：

```fish
alias codex='env EDITOR="zed" command codex --dangerously-bypass-approvals-and-sandbox -m gpt-5.3-codex -c model_reasoning_effort="medium"'
alias codex_deep='env EDITOR="zed" command codex --dangerously-bypass-approvals-and-sandbox -m gpt-5.2 -c model_reasoning_effort="high"'
```

这样配置的原因：

- `EDITOR="zed"`：让 Codex 在需要打开编辑器时统一使用 zed，便于我直接用鼠标做复制粘贴和局部修改。
- 手动 `-m` 指定模型：我使用的是 API 接入 Codex。新模型发布后的前几周，常常不会立刻出现在 API 的 model list 里；但我用的中转服务一般会及时支持这些模型，所以会直接手动指定模型名。
- `codex` 与 `codex_deep` 分工：前者使用 codex 后缀模型 + `medium` 思考强度，适合日常开发；后者使用非 codex 模型 + `high` 思考强度，适合复杂、需要深入推理的任务。

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
| [`github-pr-issue`](skills/github-pr-issue/SKILL.md) | GitHub CLI 使用指引（issue/PR 查看、编辑与创建，含团队 PR 规范） |
| [`gitlab-mr-issue`](skills/gitlab-mr-issue/SKILL.md) | GitLab CLI（glab）使用指引（issue/MR 查看、编辑与创建，含团队 MR/issue 规范） |
| [`dcjanus-preferences`](skills/dcjanus-preferences/SKILL.md) | DCjanus 在不同语言中偏好的第三方库与使用场景清单 |
| [`golang-lo`](skills/golang-lo/SKILL.md) | Go ≥ 1.18 项目使用 samber/lo 的速用指南 |
| [`pwdebug`](skills/pwdebug/SKILL.md) | 通过命令行复用浏览器会话进行前端调试 |
| [`tech-doc`](skills/tech-doc/SKILL.md) | 技术协作文档的统一写作指南 |
| [`fetch-url`](skills/fetch-url/SKILL.md) | 渲染 URL 并输出多格式内容或原始 HTML（Playwright + trafilatura） |
| [`ticktick-cli`](skills/ticktick-cli/SKILL.md) | 通过 CLI 调用滴答清单 Open API 管理任务与项目（API 文档：[Dida365 Open API](https://developer.dida365.com/docs/index.html#/openapi)） |
| [`create-skill`](skills/create-skill/SKILL.md) | 编写/新增本仓库 skills 的规范与最小模板（SKILL.md / scripts / references / assets / token 控制） |

这个仓库只是我个人在 Codex 中使用的提示词备份，内容会根据日常需求随时增删，未必完整，也不保证对所有场景都适用。如果你正好有类似需求，欢迎参考或复制现有结构自行扩展。

目前仓库只保留与 Codex 直接相关的提示词与技能说明：早期为 Cursor 准备的内容已经删除，若需要历史记录可参考 [deprecated/cursor](https://github.com/DCjanus/prompts/releases/tag/deprecated%2Fcursor) 归档。

技能编写可参考 Claude 官方的 [技能创作最佳实践](https://platform.claude.com/docs/zh-CN/agents-and-tools/agent-skills/best-practices) 文档。

## 使用方式

为了方便在当前环境中调用 Codex，可以在 shell 中新增以下 alias：

```bash
alias codex='codex --dangerously-bypass-approvals-and-sandbox --enable skills --enable web_search_request'
```

## 仓库结构

- [`AGENTS.md`](AGENTS.md)：Codex 中所有代理共享的基础约束与工作流
- [`skills/`](skills)：按功能分类的技能库，供 Codex 在需要时加载
  - [`github-pr-issue/`](skills/github-pr-issue)：GitHub CLI 使用指引（issue/PR 查看、编辑与创建，含团队 PR 规范）
    - [`SKILL.md`](skills/github-pr-issue/SKILL.md)：查看/修改 issue 与 PR，包含标题/正文格式及非交互创建命令
  - [`gitlab-pr-issue/`](skills/gitlab-pr-issue)：GitLab CLI（glab）使用指引（issue/MR 查看、编辑与创建，含团队 MR/issue 规范）
    - [`SKILL.md`](skills/gitlab-pr-issue/SKILL.md)：查看/评论/修改 issue、MR，包含标题/正文格式及非交互创建命令，适配自建 GitLab 实例
  - [`golang-lo/`](skills/golang-lo)：Go ≥ 1.18 项目使用 samber/lo 的速用指南
    - [`SKILL.md`](skills/golang-lo/SKILL.md)：速用指南，含安装/导入示例与官方函数清单获取方式
  - [`skill-creator/`](skills/skill-creator)：Claude 官方技能模板与打包脚本
    - [`SKILL.md`](skills/skill-creator/SKILL.md)：目录复制自 [anthropics/skills skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)（2025-12-06 获取）
  - [`tech-doc/`](skills/tech-doc)：技术协作文档的统一写作指南
    - [`SKILL.md`](skills/tech-doc/SKILL.md)：撰写与维护高质量技术文档的指引
- [`scripts/`](scripts)：放置 uv script 模式的工具脚本（约束见 `scripts/AGENTS.md`）
  - [`token_count.py`](scripts/token_count.py)：基于 [tiktoken](https://github.com/openai/tiktoken) 的 token 计数 CLI
  - [`token_tree.py`](scripts/token_tree.py)：统计仓库内所有 Git 跟踪文本文件的 token 数，按树状结构输出；支持全局比例进度条、对齐条形显示与百分比，可用 `--bar-width` 调整条形宽度

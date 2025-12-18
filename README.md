这个仓库只是我个人在 Codex 中使用的提示词备份，内容会根据日常需求随时增删，未必完整，也不保证对所有场景都适用。如果你正好有类似需求，欢迎参考或复制现有结构自行扩展。

目前仓库只保留与 Codex 直接相关的提示词与技能说明：早期为 Cursor 准备的内容已经删除，若需要历史记录可参考 [deprecated/cursor](https://github.com/DCjanus/prompts/releases/tag/deprecated%2Fcursor) 归档。

## 使用方式

为了方便在当前环境中调用 Codex，可以在 shell 中新增以下 alias：

```bash
alias codex='codex --dangerously-bypass-approvals-and-sandbox'
```

## 仓库结构

- [`AGENTS.md`](AGENTS.md)：Codex 中所有代理共享的基础约束与工作流
- [`skills/`](skills)：按功能分类的技能库，供 Codex 在需要时加载
  - [`gh-cli/`](skills/gh-cli)：GitHub CLI 使用指引
    - [`SKILL.md`](skills/gh-cli/SKILL.md)：查看 issue/PR 与创建 PR 的操作指南
  - [`glab-cli/`](skills/glab-cli)：GitLab CLI（glab）使用指引
    - [`SKILL.md`](skills/glab-cli/SKILL.md)：查看/评论 issue、MR 与非交互创建 MR/issue，适配自建 GitLab 实例
  - [`go-lo/`](skills/go-lo)：Go ≥ 1.18 项目使用 samber/lo 的速用指南
    - [`SKILL.md`](skills/go-lo/SKILL.md)：包含按官方 docs 划分的参考文件
  - [`partial-git-commit/`](skills/partial-git-commit)：在禁用 `git add -p` 场景下筛选并提交改动
    - [`SKILL.md`](skills/partial-git-commit/SKILL.md)：自动生成/应用 patch 的脚本说明
  - [`skill-creator/`](skills/skill-creator)：Claude 官方技能模板与打包脚本
    - [`SKILL.md`](skills/skill-creator/SKILL.md)：目录复制自 [anthropics/skills skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)（2025-12-06 获取）
  - [`tech-doc/`](skills/tech-doc)：技术协作文档的统一写作指南
    - [`SKILL.md`](skills/tech-doc/SKILL.md)：撰写与维护高质量技术文档的指引

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
  - [`skills/gh-cli/SKILL.md`](skills/gh-cli/SKILL.md)：使用 GitHub CLI 查看 issue/PR 与创建 PR 的操作指引
- [`skills/glab-cli/SKILL.md`](skills/glab-cli/SKILL.md)：使用 GitLab CLI（glab）查看/评论 issue、MR 与非交互创建 MR/issue 的操作指引，适配自建 GitLab 实例
- [`skills/tech-doc/SKILL.md`](skills/tech-doc/SKILL.md)：技术协作文档的统一写作指南
- [`skills/skill-creator/SKILL.md`](skills/skill-creator/SKILL.md)：Claude 官方的技能模板与打包脚本，目录完整复制自 [anthropics/skills skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)（2025-12-06 获取）
- [`skills/go-lo/SKILL.md`](skills/go-lo/SKILL.md)：Go ≥ 1.18 项目使用 samber/lo 简化集合/映射/字符串、错误处理、重试/防抖/节流、通道并发或指针空值场景的速用指南（含按官方 docs 划分的参考文件）
- [`skills/partial-git-commit/SKILL.md`](skills/partial-git-commit/SKILL.md)：在禁用 `git add -p` 的场景下，使用脚本按 hunk 级别筛选并直接提交改动（含自动生成/应用 patch）

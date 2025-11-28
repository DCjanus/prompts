这个仓库只是我个人在 Codex 中使用的提示词备份，内容会根据日常需求随时增删，未必完整，也不保证对所有场景都适用。如果你正好有类似需求，欢迎参考或复制现有结构自行扩展。

仓库最初建立时我主要使用 Cursor，因此曾包含针对 Cursor 的提示词；目前已不再使用，相关文件已删除。如需了解历史用法，可访问 https://github.com/DCjanus/prompts/releases/tag/deprecated%2Fcursor 。

## 使用方式

为了方便在当前环境中调用 Codex，可以在 shell 中新增以下 alias：

```bash
alias codex='codex --dangerously-bypass-approvals-and-sandbox'
```

## 仓库结构

- `AGENTS.md`：记录我在 Codex 里共用的全局代理约束
- `TECH_DOC_BEST_PRACTICES.md`：技术文档写作最佳实践（简明版）

---
name: coderabbit-cli
description: 指导如何使用 CodeRabbit CLI 进行 Code Review。
---

让 AI agent 调用本地 `coderabbit` CLI，对当前改动做代码审查。重点是选对 diff 范围，并优先使用 `--prompt-only`。

## 使用约定

- 这是给 AI agent 用的 review 工具，不是让 agent 代替人类交互式操作 TUI。
- 默认优先 `--prompt-only`，让 CodeRabbit 直接产出给 AI agent 的提示内容。
- 只有在确实需要阅读纯文本 review 原文时，才使用 `--plain`。
- 每次只 review 和当前任务直接相关的 diff，避免把无关改动混进审查范围。
- 单次 review 可能较慢，且存在频率限制；不要在短时间内重复触发多轮无意义审查。
- 当前 CLI 未提供明确的流式输出、进度或超时参数；将 `coderabbit review` 视为长任务处理，不要假设会持续输出日志。
- 运行长时间 review 前，先向用户说明可能需要数分钟到更久；执行期间定期汇报仍在等待结果，避免用户误以为已卡死。
- 如需外层超时控制，使用 shell 的超时机制包裹命令，而不是假设 `coderabbit` 自带 `--timeout`。
- 对用户汇报时，优先总结 CodeRabbit 的有效发现，不要直接大段转储原始输出。
- 向用户汇报整理后的待处理项时，使用数字编号，方便用户按编号指定后续处理项。
- 如果 CodeRabbit 的建议与代码现状或任务目标冲突，agent 应自行判断并说明取舍理由。
- 若最终没有采纳某条建议，应明确写出不采纳原因，例如误报、已有覆盖、与既定约束冲突。
- 推荐流程：先确认当前任务涉及的改动范围，再选择合适的 `review` 参数并运行 `coderabbit review --prompt-only ...`；将输出整理为可执行项，能直接修复的就修复，需要用户决策的再汇报；大改后如有必要，再补一轮 review，默认不要超过 1 到 2 轮。

## 常用命令

```bash
coderabbit review --prompt-only --type uncommitted # 审查当前未提交改动
coderabbit review --prompt-only --base <default-branch> # 审查当前分支相对仓库默认分支的改动
coderabbit review --prompt-only --base-commit HEAD~3 # 审查 HEAD~3 之后引入的改动
coderabbit review --prompt-only --base <default-branch> --config coderabbit.yaml # 基于默认分支审查，并追加仓库内 review 指令文件
coderabbit review --prompt-only --cwd /abs/path/to/repo --base <default-branch> # 指定目标仓库目录，并相对默认分支审查
timeout 30m coderabbit review --prompt-only --base <default-branch> # 在 shell 外层限制最长等待时间
```

## 参考

- 查看主命令帮助：`coderabbit --help`
- 查看 review 参数：`coderabbit review --help`
- 官方页面：[CodeRabbit CLI page](https://www.coderabbit.ai/cli)

---
name: codex-thread-renamer
description: 为当前 Codex thread 设置名称；仅当用户手动调用或明确要求命名、重命名、整理当前 Codex 会话标题时使用，永远不要自动调用。
---

# Codex Thread Renamer

用于给当前 Codex thread 设置名称。这个 skill 永远不要自动调用；只有用户手动调用或明确要求重命名当前会话时才使用。

如果用户手动调用了这个 skill，即使没有提供任何额外描述，也视为已经明确要求重命名当前 Codex thread；不要再询问“是否要重命名”。默认根据当前上下文直接生成名称并调用脚本设置，不展示候选项，也不等待用户确认。只有用户明确要求提供候选名或让其选择时，才进入候选流程。

## Workflow

1. 根据当前任务、cwd、仓库或项目上下文生成名称。
2. 名称格式固定为 `Project: 标题`，例如 `prompts: 新增会话命名 skill`。
3. 完整名称长度以 `prompts: 新增 Codex 会话命名 skill` 这种长度为宜，目标约 20-30 个可见字符，最多不超过 36 个可见字符；过长时压缩措辞。
4. Project 名由模型结合上下文判断，不要机械使用 cwd basename。
5. 用户未明确要求候选名时，直接调用脚本设置生成的名称，不要先展示名称、征求确认或要求选择。
6. 用户明确要求候选名或让其选择时，草拟 3 个候选名，按推荐程度从高到低排列，编号为 `1`、`2`、`3`，但不要在列表项里标注推荐项，然后要求用户输入数字选择：

   ```text
   1. prompts: 新增会话命名 skill
   2. prompts: Codex thread 命名脚本
   3. prompts: 当前会话标题治理

   请选择 1/2/3。若直接确认，默认会选第一项。
   ```

7. 在候选流程中，如果用户只回复“同意”“可以”“ok”“就这样”等确认语，没有给数字，则选择第 1 个推荐项。
8. 用户选择后，调用脚本设置当前 thread 名称：

   ```bash
   cd /Users/dcjanus/Code/prompts/skills/codex-thread-renamer
   ./scripts/set_current_thread_name.py "Project: 标题"
   ```

## Script Contract

- 脚本只接收 1 个位置参数：完整 thread 名称。
- 脚本不负责生成候选名、不询问用户、不选择标题。
- 如果当前环境没有 `CODEX_THREAD_ID`，脚本会报错并说明无法判断要设置哪个 Codex 会话。

## Known Limitation

- Codex Desktop GUI 可能不会实时刷新外部 app-server 写入的 thread 名称；设置成功后名称已持久化，但可能需要重启 Desktop 才显示新标题。需要排查或说明背景时，读取 [codex-desktop-thread-name-refresh.md](references/codex-desktop-thread-name-refresh.md)。

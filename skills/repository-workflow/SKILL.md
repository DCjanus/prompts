---
name: repository-workflow
description: 处理从本地 Git 变更到 GitHub/GitLab 协作发布的完整工作流；适用于创建或更新分支、语义化 commit message、commit、push、Issue/PR/MR 文案、inline review reply、Breaking Change 与提交范围核对。纯只读的平台查询不使用本 skill。
---

# Repository Workflow

统一管理仓库变更的准备、记录和发布。GitHub/GitLab 的资源读取与平台写入仍交给 [SKILL.md](../github-cli/SKILL.md) / [SKILL.md](../gitlab-cli/SKILL.md)。

## 路由

- 涉及 commit 或 commit message 时，先完整读取 [commit-messages.md](references/commit-messages.md)。
- 涉及 Issue、PR/MR 标题或正文、Breaking Change 展示、inline review reply 时，先完整读取 [change-requests.md](references/change-requests.md)。PR/MR 标题还要读取 [commit-messages.md](references/commit-messages.md)。
- 只涉及 branch、push、merge 或历史管理时，使用本文件即可。
- 只读查看、搜索、状态检查或 CI 日志不使用本 skill，直接使用对应平台或 CI skill。

## 授权边界

- 修改或实现代码只授权工作区文件变更，不自动授权 commit、push 或平台写入。
- commit、push、创建或更新 Issue/PR/MR、发送 inline reply、resolve thread 都需要用户明确授权。
- 用户一次明确要求连续动作（如“提交并推送”）时，可连续完成，无需逐步重复确认。
- 草拟文案不等于授权发送。
- PR/MR 默认创建为正式状态；只有用户明确要求时才创建 draft。

## 工作区与提交范围

1. 先运行 `git status -sb`，确认当前分支、上游关系和 dirty worktree。
2. 区分当前任务改动与用户已有改动，只处理当前任务负责的路径。
3. 不要为了当前任务 stash、restore、reset 或清理无关改动。
4. 如果同一文件混有无法安全分离的改动，停止提交并说明情况。
5. 新文件可以先精确 stage；已有文件优先通过 `git commit --only -- <paths>` 限定提交范围。

## 创建 commit

1. 完整读取 [commit-messages.md](references/commit-messages.md)，并根据最终待提交内容生成 message。
2. 把结构化提交描述写入仓库外的临时 YAML 文件。默认只写 `subject` 和 `paths`；仅当标题与 diff 无法充分解释必要的动机、约束或影响时才添加 `body`，不要机械生成提交正文。需要正文时也不要在 shell 参数中拼接多行文本。YAML 格式与正文判断标准见 [commit-messages.md](references/commit-messages.md)。
3. 从本 skill 目录运行提交脚本，并显式传入目标仓库。支持 `env -S` 时直接执行；不要使用 `python` 或 `uv run python`：

```bash
./scripts/commit_from_yaml.py /tmp/commit.yaml --repo /path/to/repository
```

不支持 `env -S` 时使用：

```bash
uv run --script scripts/commit_from_yaml.py \
  /tmp/commit.yaml --repo /path/to/repository
```

脚本默认从当前 Codex thread 自动解析模型并生成 `Assisted-by: Codex:<model>`。自动探测不可用时只能显式选择以下一种方式，不得猜测模型：

```bash
./scripts/commit_from_yaml.py /tmp/commit.yaml \
  --repo /path/to/repository --model gpt-5.6-sol

./scripts/commit_from_yaml.py /tmp/commit.yaml \
  --repo /path/to/repository --skip-assisted-by
```

`--model` 跳过自动探测但仍生成 trailer；`--skip-assisted-by` 同时跳过探测和 trailer。两者互斥，后者只用于确实无法获得模型信息的场景。

4. YAML 的 `paths` 非空时，脚本使用 `git commit --only` 限定提交范围；新文件仍需事先只 stage 当前任务负责的路径。`paths` 为空时提交当前 index，也可用于已经解决冲突的 merge commit。
5. 脚本会在提交前后校验正文、breaking 标记和 trailer；任何字段中的字面量 `\\n` 都会失败。提交后仍需回读范围与工作区：

```bash
git show --name-status --oneline --no-renames HEAD
git show -s --format=%B HEAD | git interpret-trailers --parse
git status -sb
```

提交脚本失败时停止后续操作；默认不得自行 amend，按“分支、推送与历史”的授权规则处理。

## 分支、推送与历史

- 日常切换分支使用 `git switch`，恢复工作区或暂存区使用 `git restore`。
- 新分支优先使用符合仓库约定的 Conventional Branch 名称。
- 涉及真实 index 或引用的 Git 写操作保持串行；遇到 `.git/index.lock` 时先检查活跃 Git 进程。
- 推送前再次确认分支、远端、上游关系和工作区状态。
- 更新已有 PR/MR 分支时，默认 merge target/base 到 source/head，并追加修正 commit。
- 默认不 amend、rebase、squash 或 force push。只有用户明确要求，或仓库明确要求线性历史时才改写历史；执行前先确认本地与远端目标。

## Issue、PR/MR 与 review reply

1. 完整读取 [change-requests.md](references/change-requests.md)；PR/MR 标题同时读取 [commit-messages.md](references/commit-messages.md)。
2. 根据平台同时使用 `github-cli` 或 `gitlab-cli` 完成模板检查、资源读取和实际写入。
3. 创建或更新前核对平台当前内容与最终本地状态；独立 Issue 按 reference 中的例外处理。
4. 多行正文先写入临时 Markdown 文件，再通过平台命令的 file 参数提交，不在 shell 中拼接。
5. 写入后回读标题、正文、状态和必要的元数据，确认平台结果与预期一致。

## 最终可合并门禁

当用户要求“确保 PR/MR 可以合并”“准备好合入”或同等结果时，目标不是仅消除代码冲突或等待 CI，而是满足目标仓库当前的全部合入策略。

1. 通过对应平台 skill 读取目标 repository/project 的合并方式、线性历史或 fast-forward 要求、source/head 必须包含最新 target/base 的要求、必需 checks/pipeline、审批、讨论和分支保护规则。
2. `git fetch` 后检查 base/target 与 head/source 的提交关系。无冲突、CI 成功或平台返回笼统的 `can_be_merged`，都不能替代“目标分支同步要求已满足”的检查。
3. 若目标分支尚未包含在源分支历史中，根据仓库策略和分支用途选择同步方式：
   - 平台允许 merge commit 时，沿用本 skill 的默认策略，把 target/base merge 到 source/head 并追加提交。
   - 共享或长期分支默认避免 rebase；不要仅因平台按钮提示而改写其他协作者正在使用的历史。
   - 仓库强制线性历史且只能 rebase 时，先确认源分支共享情况、需要改写的提交和推送方式，再按授权边界执行。
4. 更新源分支后，旧 pipeline/check 与旧合并状态全部视为过期；等待新提交对应的检查完成，并重新读取平台的冲突、同步、审批、讨论、权限与最终合并状态。
5. 只有平台策略和上述门禁全部满足时才报告“可以合并”。如果仍需 rebase、更新分支、审批、权限或人工操作，应明确报告剩余条件，不能把“理论上可无冲突合并”表述成“已可合并”。

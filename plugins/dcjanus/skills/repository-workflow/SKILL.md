---
name: repository-workflow
description: 仓库文档、分支、commit、push，以及 Issue/PR/MR 文案与 review reply 的协作交付。纯只读的平台查询使用对应平台 skill。
---

# Repository Workflow

按本次交付涉及的内容读取对应参考；同一任务可涉及多项，已读且未变化的内容不重复加载。参考中的个人默认服从用户当前要求和项目约定。平台资源读取与写入使用 [GitHub](../github-cli/SKILL.md) 或 [GitLab](../gitlab-cli/SKILL.md)。

| 任务 | 参考 |
| --- | --- |
| 编写或整理仓库文档 | [文档边界](references/documentation.md) |
| 创建 commit、编写 commit message、处理平台合并消息 | [提交约定](references/commit-messages.md) |
| 编写或修改 PR/MR 标题、正文 | [协作文案](references/change-requests.md)；标题同时读取[提交约定](references/commit-messages.md) |
| Issue 文案或 inline review reply | [协作文案](references/change-requests.md) |
| 确保 PR/MR 达到可合并状态 | [合入门禁](references/merge-readiness.md)及平台对应规则 |
| 分支、push 与历史管理 | 本文件 |

## 授权与范围

- 修改代码不自动授权 commit、push 或平台写入；发布、发送回复、resolve 和合并按用户当前授权及适用项目约定执行，已有授权无需重复确认。草拟不等于发送。
- PR/MR 默认创建为正式状态；用户要求 draft 时创建 draft。
- 先用 `git status -sb` 核对分支、上游与改动，区分本次任务和用户已有内容；不为任务 stash、restore、reset 或清理无关改动。同文件混有无法安全分离的改动时停止提交并说明。

## 创建 commit

- 按提交约定生成仓库外的临时 YAML，默认仅写 `subject` 与精确的 `paths`；无需预先 stage。正文、trailer、breaking change 与 pathspec 规则只在提交约定中维护。
- 使用 `scripts/commit_from_yaml.py`，显式指定目标仓库：

```bash
./scripts/commit_from_yaml.py /tmp/commit.yaml --repo /path/to/repository \
  && rm -- /tmp/commit.yaml
```

- 仅在成功且不再复用时，用同次 shell 的 `&& rm -- <明确文件路径>` 清理自己创建的临时文件；失败保留，不用变量、通配符或目录作为清理目标，不删除用户文件。
- `Assisted-by` 自动探测当前 Agent/模型；无法识别时使用已确认的信息填写 YAML 的 `assisted_by`，不得猜测。没有可靠信息时询问用户；确实无法获得时才用 `assisted_by: false`。
- 脚本已校验 message 和 trailer；成功后核对 `git show --name-status --oneline HEAD` 与 `git status -sb`，确认范围和剩余改动。失败时停止后续发布，默认不自行 amend。

## 分支、推送与历史

- 日常切换分支使用 `git switch`，恢复工作区或暂存区使用 `git restore`。
- 新分支优先使用符合仓库约定的 Conventional Branch 名称。
- 涉及真实 index 或引用的 Git 写操作保持串行；遇到 `.git/index.lock` 时先检查活跃 Git 进程。
- 推送前再次确认分支、远端、上游关系和工作区状态。
- 更新已有 PR/MR 分支前，先 fetch 并检查远端 head/source 与本地提交关系；维护者或其他协作者已追加的提交应纳入后续工作的基准，保留其修改，不用过期的本地分支覆盖远端。存在分叉时核对双方改动并按历史规则整合。
- 更新已有 PR/MR 分支时，默认 merge target/base 到 source/head，并追加修正 commit。
- 默认不 amend、rebase、squash 或 force push。只有用户明确要求，或仓库明确要求线性历史时才改写历史；执行前先确认本地与远端目标。

## 平台交付

- 按平台 skill 检查模板、目标分支和当前资源内容，结合[协作文案](references/change-requests.md)起草；PR/MR 以相对 base/target 的最终净变化为依据，独立 Issue 不要求本地存在代码改动。
- 多行正文通过文件参数提交。写入前通读完整文案，核对适用的用户要求、项目约定与协作文案偏好。
- 写入后确认标题、正文、状态与必要元数据；复用脚本已经完成的回读验证，仅补查未覆盖信息。验证失败但已有资源 URL 时先处理该资源，不重复创建。

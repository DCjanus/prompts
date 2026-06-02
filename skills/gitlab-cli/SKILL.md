---
name: gitlab-cli
description: 使用 GitLab CLI（glab）与 GitLab 资源交互；适用于 project、issue、MR、comment、wiki 等查看、更新或创建场景，含自建实例。
---

## 使用约定

说明：以下脚本调用均以当前 `SKILL.md` 所在文件夹为 workdir。

脚本调用方式（必须直接当作可执行命令运行，不要用 `uv run python` 或 `python`）：

```bash
cd skills/gitlab-cli && ./scripts/gitlab_cli.py --help
```

错误示例：

```bash
uv run python skills/gitlab-cli/scripts/gitlab_cli.py --help
python skills/gitlab-cli/scripts/gitlab_cli.py --help
```

- 目标 GitLab 仓库不是当前目录时，用 `--cwd <repo>` 指定实际执行目录。
- 自建实例需要覆盖默认 host 时，用 `--hostname <host>`。
- 不在目标仓库里、或当前目录不是 GitLab 仓库时，用 `--project <id|group/project>` 显式指定项目。

## 正文传参约束

- 创建或更新 MR / Issue 时，正文必须通过 `--description-file <path>` 传入。
- 不要使用 shell 直接传多行正文；脚本不支持 `--description`。
- `--title` 这类短文本参数可以直接传，长正文一律先写到文件里再引用。

示例：

```bash
# 正确
./scripts/gitlab_cli.py mr update --cwd /path/to/repo 123 --description-file /tmp/mr-body.md

# 错误
./scripts/gitlab_cli.py mr update --cwd /path/to/repo 123 --description "multi-line body"
```

## MR 标题与描述

- MR 标题默认遵循语义化提交规范，例如 `feat(scope): short summary`；即使标题要求中文，语义化前缀仍需英文。
- 创建或更新 MR 标题/正文时，只描述目标分支当前状态到当前分支最终状态的净变化。不要按 commit 历史、开发过程、临时实验或旧正文残留来写。
- 先确认 target/source，再用 final net diff 作为正文依据：`git fetch` 后查看 `git diff --stat <target>...HEAD` 与 `git diff --name-status <target>...HEAD`；必要时再用 `glab mr diff` 或关键文件 diff 辅助核对。
- MR 正文不要包含：中间提交顺序、调试过程、失败尝试、临时方案、merge/rebase/冲突解决过程、曾经实现过但最终 diff 已不存在的行为。
- MR / Issue 正文不要包含本机绝对路径、home 目录、agent 工作区路径、临时正文文件路径或其它会暴露个人/机器环境的信息；如需引用仓库内文件，使用相对路径或 Markdown 链接。
- MR 正文优先写清 why / what / validation。
- Validation 默认可以省略；只有能增加 reviewer 信心的信息才写，例如真实端到端使用过目标场景、线上/页面/API/CLI 行为被实际确认，或修 BUG 时先构造稳定失败的回归 case 再修复到通过。
- 不要把 GitLab pipeline、格式化、lint、类型检查、普通单元测试、构建通过等常规卫生检查写进 MR 正文；这些属于合入门槛，信息增量低。也不要记录探索性失败、调试命令或临时注入失败，除非它是最终交付的已知风险。
- Breaking change 按 final net diff / 对外行为判断，不按中间 commit 机械继承；只有最终净变化确实破坏既有用法时，标题才用 `type(scope)!: short summary`，正文才加 `BREAKING CHANGE:` 说明影响和迁移方式。

## 什么时候直接用 glab

- 查看与列表：`glab issue view`、`glab issue list`、`glab mr view`、`glab mr diff`
- CI 阻塞等待：优先用 `glab ci status --live` 等 pipeline 结束；需要跟随单个 job 日志时用 `glab ci trace <job-id|job-name>`
- 评论：`glab issue note`
- 审查意见整理：先读 MR discussions / notes / diff comments，再统一整理
- 先确认能力边界：`glab <group> --help`、`glab <group> <subcommand> --help`
- wiki：先看 `glab wiki --help`；若当前版本没有子命令，再考虑 `glab api`

## CI 等待与日志跟随

- 等待当前分支最新 pipeline 完成时，不要手写定时轮询；直接运行：

```bash
glab ci status --live --compact
```

- 等待指定分支或其它仓库的 pipeline 完成时，用：

```bash
glab ci status --branch main --live --compact
glab ci status --branch main --live --compact -R group/project
```

- 需要看某个 job 的实时日志并阻塞到日志结束时，用：

```bash
glab ci trace 123456
glab ci trace test --pipeline-id 123456 --branch main
```

- `glab ci status --live` 适合替代 agent 自己的轮询等待；等待结束后若需要把结果写入 MR / Issue / 回复，先再用 `glab ci status --output json`、`glab ci get --with-job-details` 或 `glab ci list --output json` 做一次最终状态读取，避免只根据动态终端输出下结论。
- 需要按 pipeline ID 锁定具体 pipeline 时，优先用 `glab ci view --pipelineid <id>` 做交互查看；如果任务需要非交互、机器可解析的最终状态，改用 `glab ci get` 或 `glab api` 读取该 pipeline / jobs。

## 脚本支持的场景

- GitLab CI lint：校验本地 `.gitlab-ci.yml`，支持 `--dry-run`、`--include-jobs`、`--ref`、`--json`。
- MR create：非交互创建 MR，可配合 `--cwd`、`--hostname`、`--project` 使用。
- MR update：非交互更新 MR 标题、正文、labels、reviewers、assignees、milestone、merge 相关选项。
- Issue create：非交互创建 Issue，可设置正文、labels、assignees、milestone、confidential、due date。
- Issue update：非交互更新 Issue 标题、正文、labels、assignees、milestone、confidential、due date。

除此之外，优先直接用 `glab`。

脚本入口：运行 [gitlab_cli.py](scripts/gitlab_cli.py)

## 常用子命令

- CI 校验：

```bash
./scripts/gitlab_cli.py ci lint --cwd /path/to/repo
./scripts/gitlab_cli.py ci lint --cwd /path/to/repo --project group/project --ref main --dry-run --include-jobs
```

- 创建 MR：

```bash
./scripts/gitlab_cli.py mr create \
  --cwd /path/to/repo \
  --title "feat(scope): short summary" \
  --target-branch main \
  --description-file /tmp/mr-body.md \
  --squash true \
  --remove-source-branch true
```

- 更新 MR：

```bash
./scripts/gitlab_cli.py mr update \
  --cwd /path/to/repo \
  123 \
  --description-file /tmp/mr-body.md
```

- 创建 Issue：

```bash
./scripts/gitlab_cli.py issue create \
  --cwd /path/to/repo \
  --title "short summary" \
  --description-file /tmp/issue-body.md
```

- 更新 Issue：

```bash
./scripts/gitlab_cli.py issue update \
  --cwd /path/to/repo \
  456 \
  --title "updated title" \
  --description-file /tmp/issue-body.md
```

## 创建或更新前

- 更新 Issue 或 MR 标题/正文前，先读取当前内容，再修改。
- 正文只允许通过 `--description-file` 传入；脚本不再支持 `--description`，避免 shell 转义和多行文本处理问题。
- 创建 MR 前，先检查模板、目标分支、当前分支与工作区状态是否符合仓库要求；除非仓库或用户明确要求保留多 commit 或保留源分支，否则创建 MR 时显式传 `--squash true` 与 `--remove-source-branch true`。
- 创建或更新 MR 标题/正文前，按 final net diff 重新生成整篇 MR 标题/正文，覆盖旧正文中的过时内容，并重新判断是否需要 `!` 与 `BREAKING CHANGE:`。
- 创建 Issue 前，先检查模板、标签、复现信息与现状是否一致。

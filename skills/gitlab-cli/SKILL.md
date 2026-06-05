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

## 创建前检查
在创建 Issue 或 MR 前，先检查对应的 GitLab 模板、表单和当前资源状态。
1. 优先检查 issue / MR 模板，以及 `.gitlab/issue_templates/`、`.gitlab/merge_request_templates/`、`.gitlab-ci.yml`、项目说明文档等 GitLab 专用配置。
2. Issue/MR 标题与正文编写统一遵循 [SKILL.md](../change-request-writing/SKILL.md)。
3. 在正式创建前检查当前代码、分支与提交状态是否和准备提交到平台上的内容一致，避免创建出与现状不符的 Issue 或 MR。

## 创建 Issue（非交互）
以下规范建立在“创建前检查”已完成的前提上。
1. 标题与正文先按 [SKILL.md](../change-request-writing/SKILL.md) 准备。
2. Issue 正文默认先写到本地 Markdown 文件；草稿优先放 `/tmp/*.md`，标题通常较短，可直接用 `--title` 传入。
3. 创建与修改时优先使用 `--description-file`，例如：`./scripts/gitlab_cli.py issue create --cwd /path/to/repo --title "..." --description-file /tmp/issue-body.md`，或 `./scripts/gitlab_cli.py issue update --cwd /path/to/repo 123 --title "..." --description-file /tmp/issue-body.md`。
4. 创建成功后，输出完整 Issue URL。

## 创建 MR
以下规范建立在“创建前检查”已完成的前提上。
1. 先完成“创建前检查”。
2. 只有在确认仓库要求与本地代码/提交状态都满足后，才创建 MR；若发现不满足，应先修正，再创建。
3. `git status` 必须干净，且当前分支已推送到远端。
4. 标题与正文先按 [SKILL.md](../change-request-writing/SKILL.md) 准备。
5. MR 正文默认先写到本地 Markdown 文件；草稿优先放 `/tmp/*.md`，不要在 shell 里拼多行字符串，也不要依赖交互式编辑。标题通常较短，可直接用 `--title` 传入。
6. 创建 MR 时优先使用 `--description-file`，例如：
```
./scripts/gitlab_cli.py mr create \
  --cwd /path/to/repo \
  --title "feat(scope): short summary" \
  --description-file /tmp/mr-body.md \
  --target-branch main \
  --squash true \
  --remove-source-branch true
```
7. 修改 MR 时也复用本地文件，避免手工编辑，例如：`./scripts/gitlab_cli.py mr update --cwd /path/to/repo 123 --title "..." --description-file /tmp/mr-body.md`。
8. 创建成功后，输出完整 MR URL。

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
  - `--dry-run --ref refs/merge-requests/<iid>/head` 会改用 MR source branch 调用 CI Lint。调用方知道源分支时可显式传 `--source-branch <branch>`；否则脚本会根据 ref 里的 MR IID 查询 MR 元数据。部分 GitLab 14.x 实例会因为 MR internal ref 缺少 `source_branch` 在 CI Lint dry-run 返回 500，所以脚本避免直接把 MR internal ref 发给 CI Lint。
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
./scripts/gitlab_cli.py ci lint --cwd /path/to/repo --project 122477 --ref refs/merge-requests/9/head --dry-run
./scripts/gitlab_cli.py ci lint --cwd /path/to/repo --project 122477 --ref refs/merge-requests/9/head --source-branch chore/sync-knots-api-master --dry-run
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
- 创建或更新 Issue/MR 标题正文时，文案按 [SKILL.md](../change-request-writing/SKILL.md) 重新生成。
- 创建 Issue 前，先检查模板、标签、复现信息与现状是否一致。

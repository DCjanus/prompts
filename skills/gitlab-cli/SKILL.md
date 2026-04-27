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

## 什么时候直接用 glab

- 查看与列表：`glab issue view`、`glab issue list`、`glab mr view`、`glab mr diff`
- 评论：`glab issue note`
- 审查意见整理：先读 MR discussions / notes / diff comments，再统一整理
- 先确认能力边界：`glab <group> --help`、`glab <group> <subcommand> --help`
- wiki：先看 `glab wiki --help`；若当前版本没有子命令，再考虑 `glab api`

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
- 创建 Issue 前，先检查模板、标签、复现信息与现状是否一致。

---
name: gitlab-pr-issue
description: 使用 GitLab CLI（glab）查看/评论/修改 issue 与 merge request，并包含团队约定的 MR/issue 创建规范（标题/正文格式、非交互命令）。
---

# GitLab CLI Skill（Issue/MR）

## 基本准备
- 确认身份与认证：
  - `glab auth status` 读取当前实例及 “Logged in to <host> as <user>” 行。
  - 直接取用户名：`GITLAB_HOST=<host> glab api /user | jq -r '.username'`（依赖本机 `jq`，若已设全局 `GITLAB_HOST` 可直接 `glab api /user`）。
  - 自建实例优先通过环境变量 `GITLAB_HOST` 指定；如需单次覆盖，可在命令前加 `GITLAB_HOST=<host>` 或用 `-R group/project`。
- 输出格式默认够用，若需机器可读用 `--output json`。

## Issue 快速查看
- 只看正文：`glab issue view <id|url>`.
- 带讨论：`glab issue view <id|url> --comments`（必要时加 `--system-logs`）。
- 列表：`glab issue list --state opened --per-page 50 [-R group/project]`；过滤标签用 `--label foo,bar`。
- 添加评论：`glab issue note <id> -m "comment"`。

## MR 快速查看
- 基本信息：`glab mr view <id|branch|url> [--comments|--system-logs]`。
- 查看 diff：`glab mr diff <id|branch> --color=never`；需要原始 patch 用 `--raw`。
- 相关 issue：`glab mr issues <id>`。

## 创建 MR（非交互）
1) 确保本地分支已推送且 `git status` 干净。  
2) 语义化英文标题，必要时添加 scope（例 `feat(scope): short summary`）。  
3) 用 heredoc 传多行描述，避免交互式编辑；描述聚焦合并前后行为与影响的变化，避免记录开发过程中的中间尝试或撤销动作：
```
glab mr create \
  --title "feat(scope): short summary" \
  --description "$(cat <<'EOF'
- Added X
- Updated Y
- Notes: Z
EOF
)" \
  --target-branch main \
  --source-branch $(git branch --show-current) \
  --label bugfix \
  --draft \
  --yes
```
- 推荐参数（可按需开启）：`--remove-source-branch`（合并后删源分支）、`--squash-before-merge`（合并前压缩为单一 commit）；若团队偏好可省略。  
- 其他常用参数：`--reviewer user1,user2`、`--allow-collaboration`。  
- 修改已建 MR：`glab mr update <id> --title "..."
  --description "$(cat <<'EOF'\n...\nEOF\n)" --label ... --yes`。

## Issue 创建（非交互）
- 命令模式与 MR 类似，使用 `--title` 与 heredoc 描述：  
```
glab issue create \
  --title "feat: short summary" \
  --description "$(cat <<'EOF'\n- context\n- expected\nEOF\n)" \
  --label backlog,team-x \
  --assignee user1 \
  --yes
```
- 若需私密：加 `--confidential`；截止日期 `--due-date YYYY-MM-DD`。

## 常见选项速记
- `-R group/project`：指定自建实例项目，等价于完整 URL。
- `--web`：改用浏览器查看当前对象。
- `--per-page` 与 `--page`：分页查看列表或评论时使用。

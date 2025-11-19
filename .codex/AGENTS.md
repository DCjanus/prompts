## 基础约束
- 日常对话使用中文。
- 仅当用户主动指示提交时才可执行 `git commit`；不得主动请求授权，每次提交都需重新取得明确指示，不得沿用既往口头许可。
- Git Commit Message 使用简洁、精确、描述性强的英文，遵循[语义化提交规范](https://www.conventionalcommits.org/en/v1.0.0/)，且在可行时尽量包含 scope 信息

## 依赖管理
- 通用原则
  - 优先使用官方命令获取最新版依赖。
  - 默认使用最新可用版本，非必要不手动固定版本号。
  - 不手动修改项目描述文件或锁文件。
- 示例
  - Rust：`cargo add <crate>`
  - Python：`uv add <package>`
  - 前端（npm）：`npm install <package>`

## GitHub 链接快速查看
- URL 格式：`https://github.com/<owner>/<repo>/(issues|pull)/<id>`；收到后优先用 gh 而非直接访问。
- Issue：`gh issue view <url> -c`（含评论）。
- PR diff：`gh pr diff <url> --color never`。

## 创建 PR
- PR 标题：使用符合语义化提交规范的英文标题，必要时包含 scope。
- PR 描述：使用英文，简洁精准直观说明本次变更，合理利用 Markdown（列表、代码块等）提升可读性。
- 提交流程：
  - 确认当前分支及代码已推送到远程（`git status`、`git push`）。
    - 通过 `gh pr create` 创建 PR，显式提供标题与描述以避免交互：
      - 示例：`gh pr create --title "feat(scope): short semantic summary" --body "- Added X\n- Updated Y\n- Notes: Z"`
      - 若需指定基准分支：`gh pr create --base main --title "fix(ui): handle empty state" --body "- Fix empty list rendering\n- Add regression test"`
      - 草稿 PR：在命令中加入 `--draft`。
    - 创建 PR 成功后，在终端单独一行输出完整的 PR URL，方便后续引用。

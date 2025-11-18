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

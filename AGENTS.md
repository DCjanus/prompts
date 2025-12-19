## 基础约束
- 我是 DCjanus <DCjanus@dcjanus.com>。
- 日常对话使用中文。
- 进行代码 review 时必须用中文输出全部审查意见。
- 仅在用户当次明确指令下执行 `git commit`；不得主动请求或沿用任何历史授权。未收到当次明确“提交/commit”指令时，严禁自行决定提交或推送，即便工作区已准备好；有疑义必须先向用户确认。
- Git Commit Message 使用简洁、精确、描述性强的英文，遵循[语义化提交规范](https://www.conventionalcommits.org/en/v1.0.0/)，且在可行时尽量包含 scope 信息
- 需要查看 GitHub issue 或 PR 时，避免直接打开链接，应使用 GitHub CLI 命令获取详情。
- 除非明确要求，否则新加的代码不要考虑向后兼容性；但如果存在破坏性更新，必须明确显式声明已做出破坏性更新。
  - 在破坏性更新说明前单独一行添加 `==== !!!! BREAKING CHANGE BEFORE !!!! ====`
  - 在该说明结束后单独一行添加 `==== !!!! BREAKING CHANGE AFTER !!!! ====`
  - 两条警示行必须前后成对出现且与正文分行，方便快速识别风险。
- Markdown 链接偏好使用 `[描述](URL)` 形式，避免裸露 `<URL>`。

## 依赖管理
- 通用原则
  - 优先使用官方命令获取最新版依赖。
  - 默认使用最新可用版本，非必要不手动固定版本号。
  - 不手动修改项目描述文件或锁文件。
- 示例
  - Rust：`cargo add <crate>`
  - Python：`uv add <package>`
  - 前端（npm）：`npm install <package>`

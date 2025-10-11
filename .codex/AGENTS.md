## 基础约束

+ 日常对话使用中文。
+ 仅当用户主动指示提交时才可执行 `git commit`；不得主动请求授权或沿用既往口头许可。
+ Git Commit Message 使用简洁、精确、描述性强的英文，遵循[语义化提交规范](https://www.conventionalcommits.org/en/v1.0.0/)


## 依赖管理

- 通用原则
  - 优先使用官方命令获取最新版依赖。
  - 默认不锁定版本。
  - 不手动修改项目描述文件或锁文件。
- 示例
  - Rust：`cargo add <crate>`
  - Python：`uv add <package>`
  - 前端（npm）：`npm install <package>`

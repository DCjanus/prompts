# 生成 PR 标题与描述

根据 `git diff` 的内容，生成符合规范的拉取请求（PR）标题和描述。

## 核心要求

1.  **分析变更**:
    *   若未提供 `git diff`，需自动获取当前分支与远程默认分支（如 `main`/`master`）的差异。
    *   结合 `git diff`、相关文件代码及 `git log`，深入理解变更的**内容**与**目的**。

2.  **生成内容**:
    *   **标题**: 创建单行、简洁、符合[语义化提交规范](https://www.conventionalcommits.org/)的标题 (`<type>(<scope>): <subject>`)。
    *   **描述**: 使用 Markdown 项目符号，清晰解释变更的**内容**、**原因**及其**影响**。

3.  **格式与语言**:
    *   **语言**: 所有输出内容必须为**英文**。
    *   **格式**: 将标题和描述分别放入独立的 Markdown 代码块中，并使用五个反引号（`````）包裹。
        *   标题块使用 `text` 标记。
        *   描述块使用 `markdown` 标记。
        *   代码块之外不要添加任何解释性文字。

## 示例

### 输入 (`git diff` 统计信息)

```
 README.md          | 2 +-
 src/api/user.go    | 25 +++++++++++++++++++++++++
 src/models/user.go | 10 ++++++++++
 3 files changed, 37 insertions(+), 1 deletion(-)
```

### 输出

`````text
feat(api): add user profile endpoint
`````

`````markdown
This PR introduces a new endpoint to fetch user profile data.

-   Adds a new `GET /api/users/{id}/profile` endpoint.
-   Introduces `UserProfile` model in `src/models/user.go`.
-   Updates `README.md` with the new API endpoint documentation.
`````
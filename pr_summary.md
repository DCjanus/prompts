# 生成拉取请求（PR）标题与描述

作为一名 AI 开发者专家，你的任务是根据当前分支与默认分支之间的代码变更差异（`git diff`），创建一个符合规范的拉取请求（PR）标题和描述。

## 指示

1.  **分析差异**：仔细审查提供的 `git diff` 输出所展示的代码变更。
2.  **创建语义化提交标题**：标题必须遵循[语义化提交规范](https://www.conventionalcommits.org/)。
    *   格式：`<type>(<scope>): <subject>`
    *   示例：`feat(api): add user profile endpoint`
3.  **撰写清晰的描述**：描述应简明扼要地解释变更的"内容"和"原因"。
    *   使用项目符号（bullet points）以增强可读性。
    *   重点说明变更带来的影响。
4.  **语言**：所有输出内容必须为**英文**。
5.  **格式**：将标题和描述分别放入独立的 Markdown 代码块中，使用五个反引号（`````）包裹，以便于复制。不要在代码块之外添加任何其他解释性文字。

## 上下文

你将收到一份 `git diff` 的输出，其中可能只包含变化的统计信息（如 `git diff --stat`），也可能包含完整的代码变更详情。请根据收到的信息，全面理解修改的范围和性质。

## 示例

### 输入 (示例 Git Diff)

```
 README.md          | 2 +-
 src/api/user.go    | 25 +++++++++++++++++++++++++
 src/models/user.go | 10 ++++++++++
 3 files changed, 37 insertions(+), 1 deletion(-)
```

### 输出

`````
feat(api): add user profile endpoint
`````

`````markdown
This PR introduces a new endpoint to fetch user profile data.

-   Adds a new `GET /api/users/{id}/profile` endpoint.
-   Introduces `UserProfile` model in `src/models/user.go`.
-   Updates `README.md` with the new API endpoint documentation.
````` 
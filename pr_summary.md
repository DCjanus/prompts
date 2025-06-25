# 生成拉取请求（PR）标题与描述

作为一名 AI 开发者专家，你的任务是根据当前分支与默认分支之间的代码变更差异（`git diff`），创建一个符合规范的拉取请求（PR）标题和描述。

## 指示

1.  **获取代码差异**:
    *   首先，检查用户是否已提供 `git diff` 内容。
    *   如果**没有**提供，请按以下步骤操作：
        1.  通过 `git symbolic-ref refs/remotes/origin/HEAD` 等方式，自动识别出远程仓库的默认分支（如 `main` 或 `master`）。
        2.  执行 `git diff` 命令，将当前分支与获取到的默认分支进行比较。
2.  **理解变更上下文**：
    *   仔细审查 `git diff` 的输出，了解变更的表面内容。
    *   为了更准确地理解变更背后的"原因"和"目的"，请结合以下信息进行综合分析：
        *   **读取相关文件**：阅读 `diff` 中涉及的核心文件的上下文代码。
        *   **查阅提交历史**：运行 `git log` 查看当前分支的提交信息，寻找开发者的意图。
3.  **创建语义化提交标题**：基于对代码和上下文的全面理解，创建符合[语义化提交规范](https://www.conventionalcommits.org/)的标题。
    *   格式：`<type>(<scope>): <subject>`
    *   示例：`feat(api): add user profile endpoint`
4.  **撰写清晰的描述**：基于全面的理解，简明扼要地解释变更的"内容"和"原因"。
    *   使用项目符号（bullet points）以增强可读性。
    *   重点说明变更带来的影响。
5.  **语言**：所有输出内容必须为**英文**。
6.  **格式**：将标题和描述分别放入独立的 Markdown 代码块中，使用五个反引号（`````）包裹，以便于复制。不要在代码块之外添加任何其他解释性文字。

## 上下文

你可能会收到一份 `git diff` 的输出，也可能需要自己获取。这份输出可能只包含变化的统计信息（如 `git diff --stat`），也可能包含完整的代码变更详情。请根据收到的信息，全面理解修改的范围和性质。

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
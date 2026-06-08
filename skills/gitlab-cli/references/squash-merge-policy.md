# GitLab Squash 与 Merge Commit 策略

本参考用于配置 GitLab 项目，让长期维护分支的提交历史更适合按 MR 审计。

## 期望效果

每个 MR 合并后，目标分支应留下两个提交：

1. 一个 squash commit：承载这次 MR 的实际代码变化，commit message 来自 MR 标题与正文。
2. 一个 merge commit：记录 MR 的合并边界，保留“这批变化是通过哪个 MR 合入”的结构。

这样阅读长期维护分支时，可以先看 squash commit 理解单个 MR 做了什么；需要追溯合并关系时，再看对应 merge commit 与 MR 链接。

## 推荐项目配置

项目 MR 设置建议为：

```text
merge_method: merge
squash_option: always
squash_commit_template:
%{title}

%{description}

See merge request %{reference}

%{co_authored_by}
```

配置效果：

- `merge_method=merge`：每个 MR 合并时保留一个 merge commit。
- `squash_option=always`：每个 MR 的源分支内容先压成一个 squash commit。
- `%{title}` 与 `%{description}`：让 squash commit message 直接复用 MR 标题和正文。
- `See merge request %{reference}`：在 commit message 中保留 MR 链接。
- `%{co_authored_by}`：追加 GitLab 生成的 `Co-authored-by` trailer。

如果项目希望每个 MR 只产生一个提交，且不需要 merge commit，可以改用 `merge_method=ff`。这是另一种策略，不是本文件描述的默认偏好。

## API 配置

```bash
template=$(mktemp)
cat > "$template" <<'EOF'
%{title}

%{description}

See merge request %{reference}

%{co_authored_by}
EOF
value=$(cat "$template")
rm -f "$template"

glab api --method PUT projects/:fullpath \
  --repo <group/project> \
  -f merge_method=merge \
  -f squash_option=always \
  -f squash_commit_template="$value"
```

检查最终生效配置：

```bash
glab api projects/:fullpath --repo <group/project> \
  | jq '{merge_method, squash_option, squash_commit_template, merge_commit_template}'
```

预期结果：

```text
merge_method: merge
squash_option: always
merge_commit_template: null
```

## Co-author 行为

`%{co_authored_by}` 基于 MR 中各个 commit 的 author 生成，不会读取源 commit message 里已经存在的 `Co-authored-by` trailer。

在 GitLab 14.10 上验证到的行为：

- 如果一个 MR 里有多个不同 author 的 commit，`%{co_authored_by}` 会展开为这些 author 对应的 `Co-authored-by` trailer。
- 如果源 commit message 自己带有 `Co-authored-by` trailer，但 MR 里所有 commit 的 author 相同，`%{co_authored_by}` 可能为空。
- 如果必须保留一个手工指定的 co-author，可以把 `Co-authored-by: Name <email>` 放在 MR description 末尾，让 `%{description}` 把它带进最终 squash commit message。

通过 API 合并一个 `squash_option=always` 的项目时，仍然建议显式传 `squash=true`；否则部分 GitLab 版本可能拒绝合并请求。

## 已验证行为

在 GitLab 14.10 上验证到：

- 目标分支会得到两个提交：一个 squash commit 和一个 merge commit。
- MR API 会分别返回 `squash_commit_sha` 与 `merge_commit_sha`。
- squash commit message 按 `squash_commit_template` 生成。
- 如果没有配置 `merge_commit_template`，merge commit message 使用 GitLab 默认格式。

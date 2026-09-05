# GitHub Squash Merge 策略

本参考用于配置 GitHub repository，让 PR 合并后的提交历史更适合按 PR 审计。

## 期望效果

1. repository 只允许 squash merge，禁用 merge commit 和 rebase merge。
2. squash commit message 来自 PR 标题与正文。
3. GitHub 可以继续自动追加 PR number、分隔线和 `Co-authored-by` trailer。
4. PR 合并后自动删除 source branch。

这个脚本只配置 repository-level merge policy，不配置 branch protection 或 ruleset。

## 配置脚本

```bash
./scripts/configure_squash_merge_policy.py --repo <owner/repo>
```

脚本会在写入配置后回读 GitHub repository 设置；如果回读结果不符合预期，会打印不匹配字段并以非零状态退出。

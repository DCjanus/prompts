# GitLab Squash 与 Merge Commit 策略

本参考用于配置 GitLab 项目，让长期维护分支的提交历史更适合按 MR 审计。

## 期望效果

1. 目标分支的 first-parent 历史保持线性，便于按 MR 顺序审计长期维护分支。
2. 每个 MR 合并后，目标分支留下两个提交：
   - 一个 squash commit，承载这次 MR 的实际代码变化。
   - 一个 merge commit，记录 MR 的合并边界。
3. squash commit message 来自 MR 标题与正文，并尽量保留 GitLab 可生成的 `Co-authored-by` trailer。
4. MR 链接与合并边界由 merge commit 承载，squash commit message 不重复记录 MR reference。

这样阅读长期维护分支时，可以先看 squash commit 理解单个 MR 做了什么、有哪些协作者；需要追溯合并关系时，再看对应 merge commit 与 MR 链接。

## 配置脚本

`merge_method=rebase_merge` 对应 GitLab UI 里的 Merge commit with semi-linear history。

```bash
./scripts/configure_squash_merge_policy.py --project <group/project>
```

脚本会在写入配置后回读 GitLab project 设置；如果回读结果不符合预期，会打印不匹配字段并以非零状态退出。

# MR 最终可合并门禁

当用户要求“确保 MR 可以合并”“准备好合入”或同等结果时，不能只检查冲突和 CI，也不能仅凭 MR API 的 `merge_status=can_be_merged` 下结论。该字段可能只表示内容可以无冲突地合并，项目的线性历史、fast-forward 或 source branch 必须包含最新 target branch 等策略仍可能让 GitLab UI 要求 rebase。

1. 读取目标项目设置，至少确认 `merge_method`、`squash_option`、pipeline/discussion 合入限制和默认源分支删除策略：

   ```bash
   glab api 'projects/:id' --jq '{merge_method, squash_option, only_allow_merge_if_pipeline_succeeds, only_allow_merge_if_all_discussions_are_resolved, remove_source_branch_after_merge}'
   ```

   `merge_method` 常见值包括 `merge`、`rebase_merge` 和 `ff`。不要根据名称推测平台一定会自动处理落后提交；应继续核对实际分支关系和 MR 状态。
2. `git fetch` 最新 source/target 后检查双方独有提交，并确认 target tip 是否已经包含在 source 历史中：

   ```bash
   git rev-list --left-right --count origin/<target>...origin/<source>
   git merge-base --is-ancestor origin/<target> origin/<source>
   ```

   当第二条命令返回非 0，source 仍落后或与 target 分叉。如果项目要求 fast-forward、线性历史或源分支必须最新，则 MR 尚未达到可合并状态，即使没有内容冲突。
3. 回读 MR、审批、讨论和最新 MR pipeline；需要 GitLab 重新计算合并状态时传入 `with_merge_status_recheck=true`：

   ```bash
   glab api 'projects/:id/merge_requests/<iid>?include_diverged_commits_count=true&with_merge_status_recheck=true'
   glab api 'projects/:id/merge_requests/<iid>/approvals'
   glab api 'projects/:id/merge_requests/<iid>/discussions?per_page=100'
   glab api 'projects/:id/merge_requests/<iid>/pipelines?per_page=1'
   ```

4. 只有同时满足以下条件时才能报告“可以合并”：MR 为 opened 且非 draft、无冲突、目标分支同步要求已满足、必需 pipeline/check 成功、审批数量满足、阻塞讨论已解决，并且当前用户或预期合并者具备合并权限。
5. 如果 source 落后，先按 `repository-workflow` 和项目策略选择同步方式。共享或长期分支不要因为 UI 显示 “Rebase” 就直接改写历史；优先判断是否允许把 target merge 到 source。确实必须 rebase 时，先核对远端分支共享情况和改写范围，再按授权边界执行。
6. 同步 source 会产生新 commit/pipeline；必须等待新 pipeline 到终态并再次执行上述机器可读回读，不能沿用同步前的 CI 或 merge status。


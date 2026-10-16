# GitHub 个人仓库维护偏好

适用于 DCjanus 自己维护的 GitHub 仓库；上游或团队仓库遵循其自身约定。

## 合并策略

优先采用 [dcjanus-merge-policy](../../dcjanus-merge-policy/SKILL.md) 中的 GitHub 策略，并通过该 skill 配置和回读校验，避免在此重复维护字段。仅讨论偏好或修改 skill 不代表授权修改远端仓库设置。

## Dependabot

- 使用 GitHub Dependabot 提示依赖更新，在 `.github/dependabot.yml` 中配置项目实际使用的 package ecosystem 和目录；使用 GitHub Actions 时也覆盖 `github-actions`。
- 常规版本更新优先每周一次（`schedule.interval: weekly`），PR 自动 assign 给 `DCjanus`（`assignees: [DCjanus]`）。
- 按 ecosystem 将 minor、patch 等日常更新聚合为少量 PR，包括 lockfile 中的零碎版本更新；默认用 `groups`、`patterns: ["*"]` 和 `update-types: [minor, patch]`。major 更新单独提出，便于评估兼容性，不因未纳入日常分组而忽略它们。
- 每个 ecosystem 的 `open-pull-requests-limit` 可参考设为 `5`。按项目实际需要设置例外，不照搬其它仓库针对特定依赖的 `ignore`。
- 聚合更新不等于只更新 lockfile；不要默认设置 `versioning-strategy: lockfile-only`，以免遗漏需要修改 manifest 的更新。每周节奏用于常规版本更新，不用于延后安全更新。

Rust 与 GitHub Actions 项目的参考配置；其它项目按实际 ecosystem 和目录调整：

```yaml
version: 2

updates:
  - package-ecosystem: cargo
    directory: /
    schedule:
      interval: weekly
    assignees:
      - DCjanus
    open-pull-requests-limit: 5
    groups:
      routine-cargo-updates:
        patterns:
          - "*"
        update-types:
          - minor
          - patch

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    assignees:
      - DCjanus
    open-pull-requests-limit: 5
    groups:
      routine-github-actions-updates:
        patterns:
          - "*"
        update-types:
          - minor
          - patch
```

字段语义与支持范围见 [Dependabot 配置参考](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)。

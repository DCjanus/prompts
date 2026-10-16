# GitHub 个人仓库维护偏好

适用于 DCjanus 自己维护的 GitHub 仓库，包括原创项目和长期自用 fork；这是个人偏好，上游或团队仓库遵循其自身约定。复刻前先辨认仓库用途，再选择维护方式。

## 原创项目与长期自用 fork

- 原创项目：通常通过短期分支与 PR 交付，检查通过后 squash 到默认分支；默认分支承担持续验证及项目需要的发布。沿用项目实际的默认分支名。
- 长期自用 fork：优先采用 [单主分支与补丁重放](fork-maintenance.md)，集中维护自有改造及上游基线；发布范围按自用需求决定。
- 用来向上游贡献的临时 fork 遵循上游贡献流程，不能直接套用长期自用 fork 的主分支与历史改写约定。

## 合并策略

优先采用 [dcjanus-merge-policy](../../dcjanus-merge-policy/SKILL.md) 中的 GitHub 策略，并通过该 skill 配置和回读校验，避免在此重复维护字段。仅讨论偏好或修改 skill 不代表授权修改远端仓库设置。

这是仓库提供 PR 时的合并设置，不要求直接维护主分支的个人 fork 改走 PR。启用 Allow auto-merge 后，仍由具体 PR 决定是否请求自动合并。

## 文档与开发入口

- README 保留项目定位、使用与安装入口和少量导航；架构、维护、支持现状、路线图及测试规范各自放在聚焦的文档中。长期有效的决策落入对应文档，避免按日期堆积开发过程记录。
- 自有维护说明优先中文，手写 commit 使用英文 Conventional Commits；自有项目 PR 的标题和正文通常用中文。Fork 保留上游原有说明的语言、许可证及归属边界，不将上游原有规则自动认定为个人偏好。
- 通用项目规则放在 `AGENTS.md`，仓库维护 skill 负责路由和操作方法，引用规则而不重复维护。可变实现细节以 workflow、工具配置和 manifest 为准。
- 开发任务、Git hooks 和 CI 复用仓库声明的检查入口与配置，减少同一检查项的多份定义；已有工具沿用项目约定。
- 导入或改编第三方源码时记录来源、revision、许可证及本地改造；同步源码和归属说明。需要独立维护的生成链可拆到专门仓库，由消费端通过明确依赖接入。
- 优先直接、可维护的实现和明确的职责边界；需要升级或重构时整体适配新接口，避免为旧实现长期保留无收益的兼容层。

CI、构建缓存与发布的可复刻约定见 [GitHub Actions 偏好](github-actions.md)。

## Dependabot

- 使用 GitHub Dependabot 提示依赖更新，在 `.github/dependabot.yml` 中配置项目实际使用的 package ecosystem 和目录；使用 GitHub Actions 时也覆盖 `github-actions`。
- 常规版本更新优先每周一次（`schedule.interval: weekly`），PR 自动 assign 给 `DCjanus`（`assignees: [DCjanus]`）。
- 按 ecosystem 将 minor、patch 等日常更新聚合为少量 PR，包括 lockfile 中的零碎版本更新；默认用 `groups`、`patterns: ["*"]` 和 `update-types: [minor, patch]`。major 更新单独提出，便于评估兼容性，不因未纳入日常分组而忽略它们。
- 分组还要核对实际兼容性：`0.x` 的 minor 或上游明确带 breaking change 的更新不能只因版本类型叫 minor 就作为日常兼容更新。必要时将相关依赖从通用组排除，单独提出或只聚合兼容的 patch。
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

# GitHub Actions、CI 与发布偏好

配置前先遵循 [私有仓库与 Actions 成本偏好](repository-maintenance.md#私有仓库与-actions-成本)，确认仓库可见性与启用意图；以下自动化约定适用于已决定启用 Actions 的仓库。

## Action 版本与原生 lockfile

这是用户明确的版本偏好：用语义化版本的兼容范围表达升级意图，用 GitHub 原生 `.github/workflows/actions.lock` 固定实际执行的提交和受支持的传递依赖。

- `1.x` 及以上优先使用兼容的大版本引用，例如 `@v1`；`0.x` 优先限制在同一个 minor，例如 `@v0.1`。`0.0.x` 或没有稳定兼容承诺的 action 选择精确版本，结合上游实际的版本策略判断。
- `uses` 中写的是上游实际存在的 tag 或 branch，不是包管理器的 SemVer range，不写 `@^1` 或 `@~0.1`。上游没有所需兼容范围标签时使用可用的精确版本，不扩大到整个 `@v0`。
- Rust toolchain 等 action 的 ref 可能表达工具链频道或版本，而非 action 自身版本；先确认引用语义，沿用项目工具链要求，由 lockfile 固定 action 实现。
- 首次接入时明确纳入哪些 workflow；个人 fork 优先只锁定自己实际维护的 workflow，不顺带改写禁用的上游流程。
- 使用 GitHub 官方 `gh-actions-lock` 扩展生成与校验，不手工修改 lockfile。生成时使用 `--no-narrow` 保留兼容范围引用；默认生成会把新引用收紧为精确版本，不能只检查 lockfile 而漏看 workflow 的变化。

从目标仓库根目录执行；具体参数以当前扩展的 `--help` 为准：

```sh
gh extension install github/gh-actions-lock
gh actions-lock --help
gh actions-lock .github/workflows/ci.yml --no-narrow
gh actions-lock .github/workflows/ci.yml --verify
```

项目全部 workflow 都在维护范围时可省略路径。生成器还可能迁移同仓库 action 的 `uses` 引用，应审查完整 diff；需要保留现有本地引用时，先确认扩展支持的 `--no-migrate-local-actions` 行为和 workflow 接入条件。

常规 `gh actions-lock` 会保留已有锁定，不因 `@v1` 或 `@v0.1` 移动而自动更新。审阅兼容范围内的上游变化后，用同一作用域的 `--relock --no-narrow` 更新锁定。新增或调整 `uses` 时同步生成，并将在线 `--verify` 纳入项目检查入口。

Dependabot 为已接入的 workflow 提出 action 版本更新时会一并更新对应锁定；它不负责首次接入。每周依赖维护还要核对移动引用的锁定是否需要刷新，不假定普通生成或一次 Dependabot 配置能自动追上所有 tag 移动。

该功能仍在公开预览，目标 GitHub 实例、仓库及 runner 的支持条件需实际确认。参考 [GitHub lockfile 文档](https://docs.github.com/en/actions/how-tos/secure-your-work/lock-workflow-dependencies)、[官方扩展](https://github.com/github/gh-actions-lock)及 [`--no-narrow` 说明](https://github.com/github/gh-actions-lock/blob/main/cmd/gh-actions-lock/root.go)。

## CI 组织与构建缓存

- 将格式、静态检查、测试、构建与发布的依赖关系写清楚；有实际跨平台契约时使用 matrix。重生成资产通过重跑生成器后检查零 diff 验证，避免只测生成脚本能否退出。
- 常规 PR 或同一分支的新提交可取消过时验证；耗时手动实验与正式发布分别组织并发队列，避免实验阻塞或误触发发布。
- workflow 默认只读权限，发布等需要写入的 job 单独声明权限；发布仅在约定的默认分支或明确发布入口触发，并依赖对应验证通过。
- Rust 的 CI 编译缓存优先使用 sccache，减少重复构建开销；这项偏好仅用于 CI，本地构建沿用本地工具与项目约定。通过 CI 环境中的 `RUSTC_WRAPPER=sccache` 接入，并在该环境设置 `CARGO_INCREMENTAL=0`；不修改本机全局 Cargo 配置或增量编译设置。Cargo registry / Git 下载缓存与编译结果分别维护，平台及工具链约束由项目配置定义。
- 接入后用 `sccache --show-stats` 核实 CI 的实际命中，不能把设置了 wrapper 当作缓存生效。接入方式与可缓存范围见 [sccache 使用说明](https://github.com/mozilla/sccache#usage)和 [Rust 缓存限制](https://github.com/mozilla/sccache/blob/main/docs/Rust.md)。
- 构建收益用冷、热缓存对比、Cargo timings 和必要的 linker timing 判断；同时记录 sccache 的命中、不可缓存原因及读写错误。结构化明细放在 artifact，摘要放 job summary，便于复查，避免把原始数据长期刷到日志。
- 大型自用 fork 可优先只让默认分支写正式缓存，实验分支只读，减少实验产物挤占正式缓存。
- 需要复用的仓库 action 可集中在 `.github/actions/`；第三方 action 的运行时或维护状态不适合时，再评估是否用最小本地实现替代。

## 发布与安装

- 面向日常自用的工具可在默认分支验证成功后持续分发；采用移动 `latest` 渠道还是不可变版本，依据产品的更新与回退契约决定。
- `latest` 渠道维护指向当前已验证提交的 tag 和平台资产；需要准确追溯与回退时，使用不可变发行版，自用 fork 可在上游版本后增加独立 fork 序号。配套库按消费方式提供依赖，不默认增加二进制发布流程。
- 平台矩阵、压缩格式、资产名、manifest 和安装器的解析规则共同构成分发契约；变更时同步调整，删除或更名的平台不遗留误导性的旧渠道资产。
- CLI 优先提供适用平台的预编译包，源码安装使用项目锁文件；发行包做必要的运行时依赖及资源完整性检查。更换日常安装前先隔离验收，回退策略按项目定义。
- 源码验证、CI、Release、已安装版本与可见运行行为分别报告，不能相互代替。

具体 runner、action/tool 版本、平台名单及缓存 key 以目标仓库配置为准。

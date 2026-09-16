# Skill 编写偏好

## Description

Skill frontmatter 中的 `description` 只服务于发现与触发：用具体、可区分的任务、对象、症状或用户意图说明何时应该使用该 skill，并保留识别这些场景所需的关键词；不要概述内部实现、执行流程、工具步骤或正文细节。只有在能避免相邻 skill 实际误触发时，才补充排除边界。

## CLI 渐进探索

自行维护的 CLI 型 skill 应让命令行界面本身支持渐进探索：按稳定的领域或资源与动作组织子命令，并让每层 `--help` 都能发现下一层能力。`SKILL.md` 只保留入口、路由与关键约束，引导 Agent 从顶层到目标子命令逐层查看帮助，不平铺全部命令、参数和示例；简单 CLI 不为了分层而增加层级。

## Breaking Change

判断 skill 修改是否属于 breaking change 时，以用户或 Agent 实际使用的对外契约为准，不因内部脚本的命令、参数或 API 变化机械地添加 breaking 标记。脚本仅由同一 skill 驱动且指令已同步更新，用户仍能完成同样的任务时，通常不属于 breaking change。只有当变更使用户可见能力、输出或持久化格式、显式调用方式失效，或该脚本已被明确承诺给用户、自动化或其它 skill 直接调用时，才按 breaking change 处理并说明迁移方法。

- 通常不是 breaking：仅供 skill 内部调用的 CLI 将 `cluster list` 重组为 `cluster query list`，同时更新 `SKILL.md`；用户仍然只需要提出“列出集群”，Agent 也能完成同样的任务。
- 属于 breaking：某个命令或 `--json` 输出结构已明确提供给用户自动化或其它 skill 直接调用，变更却删除命令、重命名字段或改变语义，导致这些调用者失效。

# 贡献指南

## 开发检查

完成任何修改前，运行仓库测试：

```bash
./scripts/run_tests.py
```

每次修改还应检查所有 PEP 723 脚本依赖是否为最新稳定版本：

```bash
./scripts/script_deps.py --only-attention --fail-on-attention
```

如果检查发现过期依赖，即使它与本次功能修改没有直接关系，也应使用仓库工具升级，并将必要的声明变更包含在当前 PR 中：

```bash
./scripts/script_deps.py --upgrade
```

升级后检查最终差异，确认只修改了报告指出的依赖，再重新运行依赖检查。不要通过跳过或缩小检查范围来绕过已有的依赖告警。

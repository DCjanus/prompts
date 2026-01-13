---
name: dcjanus-preferences
description: 记录 DCjanus 在不同语言中偏好的第三方库与使用场景，供 AI 在选型、引入依赖或替换库时优先参考。适用于 Python/Rust/Go 的库选择、技术方案对比、或需要遵循 DCjanus 个人偏好进行开发的场景。
---

# DCjanus Preferences

## Overview

作为 DCjanus 的个人库偏好入口，按语言拆分具体库清单与使用场景。

## Usage

- 识别当前任务的语言（Python/Rust/Go），再读取对应参考文件。
- 需要引入或替换第三方库时，优先使用偏好清单中的库。
- 语言未覆盖或需求冲突时，先向用户确认，再补充到对应语言文件。
- 新增语言时，创建 `references/<language>.md` 并在本文件补充链接。

## Language References

- Python: `references/python.md`
- Rust: `references/rust.md`
- Go: `references/go.md`

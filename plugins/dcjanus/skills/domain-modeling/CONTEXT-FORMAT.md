# CONTEXT.md 格式

## 结构

```md
# {上下文名称}

{用一两句话说明这个上下文是什么，以及它为什么存在。}

## Language

**Order**:
{用一两句话定义该术语}
_Avoid_: Purchase, transaction

**Invoice**:
货物交付后发送给客户的付款请求。
_Avoid_: Bill, payment request

**Customer**:
下单的个人或组织。
_Avoid_: Client, buyer, account
```

## 规则

- **明确选择。** 同一概念存在多个词时，选定最合适的规范术语，并把其它词列入 `_Avoid_`。
- **定义保持简短。** 最多一两句话，只定义它是什么，不描述它做什么。
- **只收录项目领域特有的术语。** 超时、错误类型、工具模式等通用编程概念不应进入词汇表。添加前先判断它是否是该上下文特有的概念。
- **自然形成概念簇时使用子标题分组。** 如果所有术语都属于同一领域，保持扁平列表即可。

## 单上下文与多上下文仓库

**单上下文（大多数仓库）：** 在根目录维护一个 `CONTEXT.md`。

**多上下文：** 在根目录使用 `CONTEXT-MAP.md` 列出各上下文、所在位置及彼此关系：

```md
# Context Map

## Contexts

- [Ordering](./src/ordering/CONTEXT.md) — 接收并跟踪客户订单
- [Billing](./src/billing/CONTEXT.md) — 生成发票并处理付款
- [Fulfillment](./src/fulfillment/CONTEXT.md) — 管理仓库拣货与发货

## Relationships

- **Ordering → Fulfillment**：Ordering 发出 `OrderPlaced` 事件；Fulfillment 消费该事件并开始拣货
- **Fulfillment → Billing**：Fulfillment 发出 `ShipmentDispatched` 事件；Billing 消费该事件并生成发票
- **Ordering ↔ Billing**：共享 `CustomerId` 和 `Money` 类型
```

按以下规则判断结构：

- 存在 `CONTEXT-MAP.md` 时，读取它以定位各上下文。
- 只有根目录 `CONTEXT.md` 时，视为单上下文。
- 两者都不存在时，在确认第一个术语后按需创建根目录 `CONTEXT.md`。

存在多个上下文时，根据当前主题判断所属上下文；无法确定时询问用户。

# Jira wiki markup

Issue Description、Comment 和 Worklog Comment 均按 Jira wiki markup 原样发送；CLI
不做正文格式转换。使用下面这组高频 Jira wiki markup：

```text
h3. 调查结论

*重要结论*、_需要强调_、{{inline_code}}

* 第一项
** 嵌套项

# 第一步
## 子步骤

||字段||值||
|状态|完成|

bq. 单段引用

{quote}
多段引用
{quote}

[RCA-SRE-22950|https://dems.example/task-centre/tasks/RCA-SRE-22950]
[^report.txt]
[~username]

{noformat}
保留原始格式，不解析 *强调* 等语法
{noformat}

{code:python}
print("hello")
{code}
```

链接使用 `[显示文本|URL]`。空行开始新段落，`\\` 强制换行，`----` 插入水平线；
使用反斜杠转义后续特殊字符。必要时可使用 `{panel:title=标题}...{panel}` 和
`!image.png|thumbnail!`。

Jira 管理员可以按字段配置 renderer，插件也可能增减宏。需要完整或实例特定语法时，
读取当前 Jira 的
`/secure/WikiRendererHelpAction.jspa?section=all`。

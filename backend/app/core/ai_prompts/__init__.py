"""
AI 工作台的提示词与场景逻辑包。

| 模块 | 职责 |
|---|---|
| `base.py` | 公共基座: 外部文本标签包裹(防注入) + 头尾截断 + system prompt 组装 |
| `case_gen.py` | 用例生成: prompt + DSL 解析 + 14 条校验规则 |
| `bug.py` | Bug 分析: prompt + 结论解析 + evidence 校验 |
| `log.py` | 日志分析: prompt + 结论解析 + evidence 校验 |
| `sql.py` | SQL 分析: prompt + 结论解析 |
| `clustering.py` | 日志聚类(**纯 Python, 不调模型**) |

跨端常量的**权威定义**在 `app/enums/AIWorkbenchEnum.py`; UI 步骤动作白名单的
权威定义在 `app/core/ui_executor.py`。
"""

"""
SQL 分析 —— 提示词与结论解析(US4)

**只读保证**: 执行计划只采集不执行 —— 只发普通 `EXPLAIN`, **绝不执行目标 SQL 本身**
(对 `UPDATE` / `DELETE` 也只做计划采集)。`EXPLAIN ANALYZE` 在
`app/utils/sql_guard.py` 里**硬拦**(research.md §3.11)。

**可验证**: 改写后的 SQL 必须能直接在「在线工具 → SQL 客户端」执行 ——
建议不可验证等于没建议。
"""
import re
from typing import Any, Dict, List, Optional

from app.core.ai_prompts import base

# 问题点的级别
LEVELS = ["high", "medium", "low"]
DEFAULT_LEVEL = "medium"

# 改写 SQL 的最小可信度 —— 拿不准就别给改写建议
MIN_REWRITE_CONFIDENCE = 0.5

MAX_SQL_CHARS = 100000

SYSTEM_PROMPT = """你是接口测试平台 Pity 的「SQL 分析」助手。
你的任务是根据给定的**执行计划**、**表结构**与**索引信息**, 判断这条 SQL 的性能问题并给出改写建议。

你只输出 JSON, 不要输出任何解释文字, 不要输出 markdown 代码块以外的内容。

## 输出结构

{
  "problems": [
    {"level": "high|medium|low", "point": "问题点", "detail": "详细说明"}
  ],
  "index_suggestions": [
    {"table": "表名", "ddl": "ALTER TABLE ... ADD INDEX ...;", "reason": "为什么这样加"}
  ],
  "rewritten_sql": "改写后的 SQL",
  "confidence": 0.8
}

## 硬性要求

1. `problems` 里的每一条都要**能在执行计划里找到依据** ——
   比如 `type=ALL` 且 `rows` 很大, 就是全表扫描。不要凭空猜测。
2. `index_suggestions[].ddl` 必须是**可直接执行的 DDL**, 例如:
   `ALTER TABLE orders ADD INDEX idx_user_id (user_id);`
   索引列的顺序要按 WHERE 条件里的过滤列来排。
3. `rewritten_sql` 必须是**语义等价**的 SQL, 且**不含 `EXPLAIN` 前缀** ——
   它会被直接拿去执行。只在确实能改善时才给; 拿不准就给空字符串。
4. `confidence` 必须在 0 到 1 之间, 表示你对整体结论的把握。
5. 只用采集到的信息说话 —— 表结构与索引里没有的列不要提。

## 示例

执行计划里有: `type: ALL, table: orders, rows: 128400`
表结构: `orders(id, user_id, amount, status)`
索引: `orders` 上只有主键 `PRIMARY`

输出:
{"problems": [
   {"level": "high", "point": "orders 表全表扫描", "detail": "type=ALL 且预估扫描 12.8 万行, 实际只命中 1 行"}],
 "index_suggestions": [
   {"table": "orders", "ddl": "ALTER TABLE orders ADD INDEX idx_user_id (user_id);",
    "reason": "过滤列 user_id 上没有可用索引"}],
 "rewritten_sql": "select id, amount, status from orders where user_id = 1001",
 "confidence": 0.85}
"""


def build_messages(sql: str, plan_text: str, columns_text: str, indexes_text: str) -> list:
    """
    组装 messages —— SQL 与采集结果用 `<sql>` 标签包裹(外部输入, 可能含注入)。

    :param sql:          目标 SQL
    :param plan_text:    执行计划(EXPLAIN 的输出)
    :param columns_text: 涉及表的列结构
    :param indexes_text: 涉及表的索引
    """
    body = f"[目标SQL]\n{sql}\n\n[执行计划]\n{plan_text}\n\n[表结构]\n{columns_text}\n\n[索引]\n{indexes_text}\n"
    user = f"<sql>\n{body}\n</sql>\n\n请按系统消息里的规范输出 JSON:"
    return base.build_messages(SYSTEM_PROMPT, user)


def _clip(value: Any, limit: int = 2000) -> str:
    return str(value or "")[:limit]


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if number < 0 else (1.0 if number > 1 else number)


def parse_result(text: str) -> dict:
    """
    解析模型输出。

    - 结构校验: 缺字段补默认值, 类型不对的丢弃
    - `rewritten_sql` 做**基本合法性检查** —— 含 `EXPLAIN` 前缀的不要(会被执行),
      不是合法语句的丢弃
    """
    from app.core.ai_service import AIJsonError, extract_json

    payload = extract_json(text)
    if not isinstance(payload, dict):
        raise AIJsonError("模型返回的 JSON 不是对象")

    result = {
        "problems": [],
        "index_suggestions": [],
        "rewritten_sql": "",
        "confidence": _confidence(payload.get("confidence")),
    }

    raw_problems = payload.get("problems")
    if isinstance(raw_problems, list):
        for item in raw_problems:
            if not isinstance(item, dict):
                continue
            point = str(item.get("point") or "").strip()
            if not point:
                continue
            level = str(item.get("level") or DEFAULT_LEVEL).strip().lower()
            if level not in LEVELS:
                level = DEFAULT_LEVEL
            result["problems"].append({
                "level": level,
                "point": point,
                "detail": _clip(item.get("detail")),
            })

    raw_indexes = payload.get("index_suggestions")
    if isinstance(raw_indexes, list):
        for item in raw_indexes:
            if not isinstance(item, dict):
                continue
            table = str(item.get("table") or "").strip()
            ddl = str(item.get("ddl") or "").strip()
            if not table or not ddl:
                continue
            if not ddl.upper().startswith("ALTER TABLE"):
                # 索引建议必须是可执行的 DDL
                continue
            result["index_suggestions"].append({
                "table": table,
                "ddl": _clip(ddl, 4000),
                "reason": _clip(item.get("reason")),
            })

    rewritten = str(payload.get("rewritten_sql") or "").strip()
    if rewritten:
        if rewritten.upper().startswith("EXPLAIN"):
            # 改写 SQL 会被直接执行 —— 带 EXPLAIN 前缀的不给
            rewritten = ""
        elif not _looks_like_sql(rewritten):
            rewritten = ""
        else:
            rewritten = rewritten[:MAX_SQL_CHARS]
    result["rewritten_sql"] = rewritten

    return result


def _looks_like_sql(text: str) -> bool:
    """
    基本合法性检查 —— 至少要像个 SQL 语句。

    不做完整的 SQL 解析器(那是另一个战场), 只挡住明显不是 SQL 的东西:
    散文、JSON、Markdown 包裹。
    """
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("```"):
        return False
    lowered = stripped.lower()
    keywords = ("select", "insert", "update", "delete", "with", "replace", "show", "explain")
    return lowered.startswith(keywords) or lowered.startswith("(")

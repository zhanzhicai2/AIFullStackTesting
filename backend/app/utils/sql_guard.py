"""
SQL 安全护栏 —— 分析场景的只读保证

## 硬约束: `EXPLAIN ANALYZE` 必须在解析层拦下

MySQL 8.0.18+ 的 `EXPLAIN ANALYZE` **会真实执行查询**。
对 `UPDATE` / `DELETE` 来说, 那等于在生产库上执行写操作。

提示词里写"不要用 EXPLAIN ANALYZE"是**软约束** —— 模型不保证遵守;
在解析层硬拦才是硬约束(research.md §3.11)。

本模块是**纯解析**的, 不连数据库 —— 拦在"发给数据库之前"。
"""
import re
from typing import List, Tuple


class SqlGuardError(Exception):
    """SQL 不满足安全约束 —— 由路由层转成 code 110"""


def strip_sql_comments(sql: str) -> str:
    """
    去掉注释与字符串字面量。

    否则注释里写一句 `EXPLAIN ANALYZE` 就会被误判成危险语句,
    而字符串里的 `EXPLAIN` 又会让检查失效。
    """
    if not sql:
        return ""
    result = []
    index, total = 0, len(sql)
    while index < total:
        char = sql[index]
        if char == "-" and index + 1 < total and sql[index + 1] == "-":
            while index < total and sql[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < total and sql[index + 1] == "*":
            end = sql.find("*/", index + 2)
            index = total if end == -1 else end + 2
            continue
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            while index < total:
                if sql[index] == "\\":
                    index += 2
                    continue
                if sql[index] == quote:
                    index += 1
                    break
                index += 1
            result.append(" ")
            continue
        result.append(char)
        index += 1
    return "".join(result)


def contains_explain_analyze(sql: str) -> bool:
    """
    判断 SQL 里是否含 `EXPLAIN ANALYZE`(含各种变体)。

    覆盖:
    - `EXPLAIN ANALYZE SELECT ...`
    - `EXPLAIN ANALYZE FORMAT=JSON SELECT ...`
    - `EXPLAIN FORMAT=JSON, ANALYZE SELECT ...`

    不误判:
    - `EXPLAIN SELECT ...`
    - `EXPLAIN FORMAT=JSON SELECT ...`
    - 注释或字符串里出现的 "EXPLAIN ANALYZE"
    """
    text = strip_sql_comments(sql).upper()
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)
    skip = {"FORMAT", "JSON", "TREE", "TRADITIONAL"}
    for index, token in enumerate(tokens):
        if token != "EXPLAIN":
            continue
        cursor = index + 1
        while cursor < len(tokens):
            nxt = tokens[cursor]
            if nxt == "ANALYZE":
                return True
            if nxt in skip or nxt == ",":
                cursor += 1
                continue
            break
    return False


def ensure_explain_safe(sql: str) -> None:
    """
    采集执行计划前的最后一道闸 —— 含 `EXPLAIN ANALYZE` 直接拒绝。

    :raise SqlGuardError: 命中危险语句
    """
    if contains_explain_analyze(sql):
        raise SqlGuardError("仅支持普通 EXPLAIN 采集执行计划, 不允许 EXPLAIN ANALYZE")


def build_explain(sql: str) -> str:
    """生成采集执行计划用的语句 —— 只加普通 EXPLAIN"""
    text = (sql or "").strip().rstrip(";")
    return f"EXPLAIN {text}"


# FROM / JOIN / INTO / UPDATE 后面的表名
TABLE_REF_PATTERN = re.compile(
    r"\b(?:from|join|into|update)\s+"
    r"[`\"]?([A-Za-z_][A-Za-z0-9_$]*)[`\"]?"
    r"(?:\s*\.\s*[`\"]?([A-Za-z_][A-Za-z0-9_$]*)[`\"]?)?",
    re.IGNORECASE,
)

# 这些关键字出现在 from 后面时不是表名
NOT_A_TABLE = {"select", "dual", "lateral", "unnest"}


def extract_table_refs(sql: str) -> List[str]:
    """
    提取 SQL 涉及的表名(带 schema 前缀)。

    :param sql: 原始 SQL
    :return:    表名列表(去重, 保序)
    """
    text = strip_sql_comments(sql)
    result: List[str] = []
    for matched in TABLE_REF_PATTERN.finditer(text):
        first = matched.group(1)
        second = matched.group(2)
        if not first or first.lower() in NOT_A_TABLE:
            continue
        name = f"{first}.{second}" if second else first
        if name not in result:
            result.append(name)
    return result


def split_table_ref(table_ref: str) -> Tuple[str, str]:
    """把 `schema.table` 拆成 (schema, table) —— 没有 schema 时 schema 为空"""
    if "." in table_ref:
        schema, table = table_ref.split(".", 1)
        return schema, table
    return "", table_ref

"""
数据工厂导出通道

导出成临时文件, 由 router 用 PityResponse.file 返回给浏览器下载
(PityResponse.file 自带 BackgroundTask, 下载完自动删临时文件)
"""
import json
import os
import tempfile
from datetime import datetime
from typing import Any, List, Tuple


def _sql_value(value: Any) -> str:
    """把 python 值转成 SQL 字面量"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d %H:%M:%S")
    # 单引号转义, MySQL / PostgreSQL 通用
    return "'" + str(value).replace("'", "''") + "'"


def _collect_columns(rows: List[dict]) -> List[str]:
    columns: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in columns:
                columns.append(key)
    return columns


def build_json(rows: List[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2)


def build_sql(rows: List[dict], table_name: str) -> str:
    if not rows:
        return ""
    columns = _collect_columns(rows)
    column_part = ", ".join(f"`{c}`" for c in columns)
    lines = []
    for row in rows:
        values = ", ".join(_sql_value(row.get(c)) for c in columns)
        lines.append(f"INSERT INTO `{table_name}` ({column_part}) VALUES ({values});")
    return "\n".join(lines)


def write_temp(content: str, suffix: str) -> Tuple[str, str]:
    """
    写临时文件, 返回 (文件路径, 下载文件名)
    """
    filename = f"datafactory_{datetime.now().strftime('%Y%m%d%H%M%S')}{suffix}"
    fd, path = tempfile.mkstemp(prefix="pity_datafactory_", suffix=suffix)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return path, filename

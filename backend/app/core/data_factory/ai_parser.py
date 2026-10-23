"""
自然语言 -> 字段生成规则 的翻译

AI 在这里只做一件事: 把用户的口语描述翻译成结构化的字段规则。
真正的数据生成仍然由确定性的内核完成, 所以同样的规则永远得到同样的数据。

模型输出的 JSON 会经过逐字段校验, 非法字段被丢弃并作为 warning 返回,
不会因为一个字段写错就整批失败。
"""
import json
import re
from typing import Any, Dict, List, Tuple

from app.core.data_factory.generator import (DATA_FACTORY_KINDS, FAKER_PROVIDERS,
                                             FIELD_NAME_PATTERN, DataFactoryError)

SYSTEM_PROMPT = """你是接口测试平台 Pity 的「数据工厂」助手, 负责把用户的自然语言需求翻译成测试数据的字段生成规则。

你只输出 JSON, 不要输出任何解释文字, 不要用 markdown 代码块以外的内容。

JSON 结构:
{
  "count": 生成的条数(整数),
  "columns": [
    {
      "name": "字段名, 只能是字母/数字/下划线, 不能以数字开头",
      "type": "string | int | float | bool | date | datetime",
      "rule": { "kind": "...", ... },
      "unique": false,
      "nullable": false,
      "default": null,
      "comment": "字段含义说明"
    }
  ]
}

unique 只在字段本身是随机值、且确实要求不重复时才设 true。
若字段用 ${} 引用了另一个字段(比如 email 引用 mobile), 不要给它设 unique ——
让被引用的那个字段 unique 即可, 否则被引用字段一旦重复, 这个字段永远换不出新值。

rule.kind 只能取下面这些值, 并按对应参数填写:
- "fixed": 固定值, 参数 {"value": "常量"}
- "random": 随机区间, 参数 {"min": 1, "max": 100}, type 为 float 时加 {"decimals": 2}
- "enum": 枚举轮转, 参数 {"values": ["A", "B"]}
- "sequence": 序列递增, 参数 {"start": 1, "step": 1}
- "uuid": UUID, 参数 {"prefix": ""} (可省略)
- "template": 字符模板, 参数 {"template": "138########"}, # 代表数字, ? 代表字母, * 代表数字或字母
- "regex": 正则生成, 参数 {"pattern": "^1[3-9]\\\\d{9}$"}
- "reference": 引用同一批数据里的另一个字段, 参数 {"from": "被引用字段名"}
- "faker": 随机真实数据, 参数 {"provider": "name"}, 常用 provider: name, phone_number, email, ssn, address, company, uuid4
- "func": 平台内置函数, 参数 {"expr": "${random_int(1,100)}"}, 可用函数: now(), uuid(), random_int(a,b), sec_before(n), hour_before(n), day_before(n)
- "date": 随机日期, 参数 {"start": "-30d", "end": "now", "format": "%Y-%m-%d %H:%M:%S"}

如果某个字段需要引用另一个字段的值(比如手机号派生邮箱), 用 template 或 reference,
在 template 里写 ${字段名} 引用同批次已生成的字段。

举例:
用户说「生成 100 个测试用户, 手机号 138 开头, 邮箱是 qq 域名, 昵称随机中文名」
输出:
{"count": 100, "columns": [
  {"name": "user_id", "type": "int", "rule": {"kind": "sequence", "start": 1, "step": 1}, "unique": true, "comment": "用户ID"},
  {"name": "mobile", "type": "string", "rule": {"kind": "template", "template": "138########"}, "unique": true, "comment": "手机号"},
  {"name": "email", "type": "string", "rule": {"kind": "template", "template": "${mobile}@qq.com"}, "comment": "邮箱"},
  {"name": "nickname", "type": "string", "rule": {"kind": "faker", "provider": "name"}, "comment": "昵称"}
]}
"""

USER_TEMPLATE = "用户需求: {prompt}\n\n请按上面的规则输出 JSON:"


def build_messages(prompt: str) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(prompt=prompt)},
    ]


def _extract_json(text: str) -> Any:
    """从模型输出里抠出 JSON, 容忍 markdown 代码块包裹和前后废话"""
    if not text:
        raise DataFactoryError("模型没有返回内容")
    content = text.strip()
    # 去掉 ```json ... ``` 包裹
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        content = re.sub(r"\s*```\s*$", "", content)
    try:
        return json.loads(content)
    except Exception:
        pass
    # 退而求其次: 提取第一个完整的 {...} 块
    start = content.find("{")
    if start == -1:
        raise DataFactoryError("模型返回的内容里没有 JSON")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(content)):
        char = content[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(content[start:index + 1])
                except Exception:
                    break
    raise DataFactoryError("模型返回的 JSON 解析失败, 请重试")


def _validate_column(column: Any) -> Tuple[dict, str]:
    """
    校验单个字段, 返回 (规范化后的字段, 错误信息)
    """
    if not isinstance(column, dict):
        return {}, "字段格式非法(不是对象)"
    name = str(column.get("name") or "").strip()
    if not name:
        return {}, "字段名不能为空"
    if not FIELD_NAME_PATTERN.match(name):
        return {}, f"字段名 {name} 非法, 只能包含字母/数字/下划线且不能以数字开头"
    rule = column.get("rule") or {}
    if not isinstance(rule, dict):
        return {}, f"字段 {name} 的 rule 格式非法"
    kind = rule.get("kind") or "fixed"
    if kind not in DATA_FACTORY_KINDS:
        return {}, f"字段 {name} 的生成方式 {kind} 不支持"
    if kind == "faker":
        provider = str(rule.get("provider") or "")
        if provider not in FAKER_PROVIDERS:
            return {}, f"字段 {name} 的 faker provider {provider} 不支持"
    normalized = {
        "name": name,
        "type": column.get("type") or "string",
        "rule": rule,
        "unique": bool(column.get("unique")),
        "nullable": bool(column.get("nullable")),
        "default": column.get("default"),
        "comment": column.get("comment") or "",
    }
    return normalized, ""


def parse_rules(text: str) -> Tuple[Dict[str, Any], List[str]]:
    """
    解析模型输出

    :param text: 模型返回的文本
    :return: (规则集, 警告列表)
    """
    payload = _extract_json(text)
    if not isinstance(payload, dict):
        raise DataFactoryError("模型返回的 JSON 不是对象")
    raw_columns = payload.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise DataFactoryError("模型没有给出任何字段")

    columns = []
    warnings = []
    seen = set()
    for raw in raw_columns:
        column, error = _validate_column(raw)
        if error:
            warnings.append(error)
            continue
        if column["name"] in seen:
            warnings.append(f"字段 {column['name']} 重复, 已忽略")
            continue
        seen.add(column["name"])
        columns.append(column)

    if not columns:
        raise DataFactoryError("模型给出的字段全部不合法")

    count = payload.get("count")
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = None
    if count is None or count <= 0:
        count = len(columns)
    count = min(count, 10000)
    return {"count": count, "columns": columns}, warnings

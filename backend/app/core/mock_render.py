"""
Mock 响应渲染器 —— 白名单回显变量, 字典替换, 零表达式求值

**安全边界(本特性最关键的一条)**: 本模块**只做"查字典替换"** —— 扫描 `$request.*` 模式,
在请求快照里取值替换, 不引入任何表达式求值、不调用任何函数。
**禁止**复用 `app/core/render.py`(裸 `Environment()`, 非沙箱, 可执行任意表达式 —— RCE 面)。

**确定性声明(constitution 原则 I)**: 变量值全部由请求内容决定 —— 同一请求 + 同一响应体,
渲染结果逐字段一致, 无随机源、无真实时间。

取不到值(请求未携带该参数)→ 替换为空字符串, 不报错不抛异常, 响应结构保持稳定
(spec Edge Cases「回显变量取不到值」)。
"""
import json
import re
from typing import Dict

# 合法变量 —— 封闭白名单(data-model.md §4):
#   $request.path                   被测接口原始路径(不含 query)
#   $request.query.<name>           查询参数(同名多值取第一个; 键名可含点, 如 filter.name)
#   $request.body.<key.path>        JSON 请求体字段(点分路径, 数组用数字索引, 段间非空)
#   $request.header(s).<name>       请求头(忽略大小写)
# 本正则即「管理端保存时校验」的权威定义 —— schema/mock.py 引用它派生锚定版, 单一出处。
VARIABLE_PATTERN = re.compile(
    r"\$request\.(path|query\.[A-Za-z0-9_.-]+|body\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
    r"|header(s)?\.[A-Za-z0-9_-]+)"
)


class MockRequestSnapshot:
    """请求快照 —— 渲染的取值来源(由服务路由 / 调试表单构造)"""

    def __init__(self, path: str = "", query: Dict = None, body: Dict = None, headers: Dict = None):
        self.path = path
        self.query = query or {}
        self.body = body or {}
        # header 键统一小写, 取值忽略大小写
        self.headers = {str(k).lower(): v for k, v in (headers or {}).items()}


def _get_by_dot_path(obj, dot_path: str):
    """按点分路径逐层取值, 数组用数字索引; 取不到返回 None。"""
    current = obj
    for key in dot_path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return None
    return current


def _to_text(value) -> str:
    """
    取值 → 文本。bool → true/false(保持 JSON 字面量), 数字 → str, dict/list → JSON,
    其他 → str。渲染器本质是文本替换, 不做结构化 JSON 类型保持 —— 这是设计边界。
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _lookup(snapshot: MockRequestSnapshot, variable: str) -> str:
    """变量 → 值; 取不到一律返回空串(不抛异常)。"""
    if variable == "$request.path":
        return snapshot.path
    rest = variable[len("$request."):]
    if rest.startswith("query."):
        key = rest[len("query."):]
        value = snapshot.query.get(key)
        if isinstance(value, list):
            return _to_text(value[0]) if value else ""
        return _to_text(value) if value is not None else ""
    if rest.startswith("body."):
        value = _get_by_dot_path(snapshot.body, rest[len("body."):])
        return _to_text(value) if value is not None else ""
    if rest.startswith("header.") or rest.startswith("headers."):
        key = rest.split(".", 1)[1].lower()
        return snapshot.headers.get(key, "")
    return ""


def render(response_body: str, snapshot: MockRequestSnapshot) -> str:
    """渲染响应体: 把白名单变量替换为请求快照中的值。无变量时原样返回。"""
    if not response_body:
        return response_body or ""
    return VARIABLE_PATTERN.sub(lambda m: _lookup(snapshot, m.group(0)), response_body)

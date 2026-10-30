"""
Mock 配置自测脚本(**不依赖数据库**)

不依赖 pytest(后端目前没有测试框架), 直接跑:
    cd backend
    .venv/bin/python scripts/mock_selftest.py

覆盖(constitution 原则 V 门禁 + GATE-SEC 安全面):
- 匹配引擎全表正反例: 精确 / 参数化 / 通配 / ANY / 优先级排序 / 停用排除 /
  路径类型推导 / normalize 清洗 / **双跑一致(确定性)**
- 变量渲染器正反例: $request.path / query(单值多值) / body(点分+数字索引) /
  header(s)(忽略大小写) / 取不到值空串 / 未知变量拒绝
- 延迟与状态码边界(schema 校验)
- **源码 AST 静态扫描**: mock 相关模块无出网调用(aiohttp/httpx/requests)、
  无 eval/exec —— GATE-SEC 的机器可验证保证

**需要数据库的部分**(DAO 真实读写 + 对外服务命中)在 `scripts/mock_e2e.py`。
"""
import ast
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json  # noqa: E402

from app.core import mock_engine, mock_render  # noqa: E402
from app.core.mock_engine import derive_path_type, match_rule, normalize_path  # noqa: E402
from app.core.mock_render import MockRequestSnapshot, render  # noqa: E402
from app.enums.MockEnum import (MAX_DELAY, MAX_STATUS_CODE, METHODS,  # noqa: E402
                                MIN_STATUS_CODE, PATH_TYPE_EXACT, PATH_TYPE_PARAM,
                                PATH_TYPE_WILDCARD)
from app.schema.mock import MockRuleForm, REQUEST_VARIABLE_PATTERN  # noqa: E402

FAILED = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


def rule(**kw):
    """构造匹配引擎可用的规则对象(默认启用、ANY、精确路径)"""
    base = dict(name="r", method="ANY", path="/api/x", path_type=PATH_TYPE_EXACT,
                priority=0, status=1, id=1)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# 路径类型推导与清洗
# ---------------------------------------------------------------------------


def test_path_type():
    print("== 路径类型推导 ==")
    check("含 * → 通配", derive_path_type("/api/*") == PATH_TYPE_WILDCARD)
    check("含 * 且含 : → 通配优先", derive_path_type("/api/:id/*") == PATH_TYPE_WILDCARD)
    check("含 : → 参数化", derive_path_type("/api/user/:id") == PATH_TYPE_PARAM)
    check("纯路径 → 精确", derive_path_type("/api/user/1") == PATH_TYPE_EXACT)
    check("根路径 → 精确", derive_path_type("/") == PATH_TYPE_EXACT)


def test_normalize_path():
    print("== 路径清洗 ==")
    check("去 query", normalize_path("/api/user/1?x=1") == "/api/user/1")
    check("合并多余斜杠", normalize_path("api/user/1") == "/api/user/1")
    check("去末尾斜杠", normalize_path("/api/user/1/") == "/api/user/1")
    check("根路径保持", normalize_path("/") == "/")
    check("根路径多斜杠", normalize_path("//") == "/")


# ---------------------------------------------------------------------------
# 匹配引擎
# ---------------------------------------------------------------------------


def test_match_exact():
    print("== 精确匹配 ==")
    r = rule(path="/api/user/1", path_type=PATH_TYPE_EXACT, method="GET")
    check("精确路径命中", match_rule("GET", "/api/user/1", [r]) == r)
    check("精确路径命中(带 query)", match_rule("GET", "/api/user/1?name=tom", [r]) == r)
    check("末尾斜杠兼容", match_rule("GET", "/api/user/1/", [r]) == r)
    check("方法不符不命中", match_rule("POST", "/api/user/1", [r]) is None)
    check("路径不同不命中", match_rule("GET", "/api/user/2", [r]) is None)


def test_match_param():
    print("== 参数化匹配 ==")
    r = rule(path="/api/user/:id", path_type=PATH_TYPE_PARAM, method="GET")
    check("参数占位命中", match_rule("GET", "/api/user/123", [r]) == r)
    check("参数占位命中另一段", match_rule("GET", "/api/user/abc", [r]) == r)
    check("段数不符不命中", match_rule("GET", "/api/user", [r]) is None)
    check("多一段不命中", match_rule("GET", "/api/user/1/extra", [r]) is None)
    check("参数不吞斜杠", match_rule("GET", "/api/user/1/2", [r]) is None)
    check("前缀不同不命中", match_rule("GET", "/api/admin/123", [r]) is None)


def test_match_wildcard():
    print("== 通配匹配 ==")
    r = rule(path="/api/*", path_type=PATH_TYPE_WILDCARD, method="GET")
    check("通配命中多段", match_rule("GET", "/api/user/1/2", [r]) == r)
    check("通配命中单段", match_rule("GET", "/api/user", [r]) == r)
    check("通配不匹配前缀外", match_rule("GET", "/other/user", [r]) is None)
    check("通配不吞根", match_rule("GET", "/api2", [r]) is None)


def test_match_any_method():
    print("== ANY 方法通配 ==")
    r = rule(method="ANY", path="/api/x", path_type=PATH_TYPE_EXACT)
    for m in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
        check(f"ANY 命中 {m}", match_rule(m, "/api/x", [r]) == r)
    specific = rule(method="POST", path="/api/x", path_type=PATH_TYPE_EXACT, id=2)
    check("具体方法优先于 ANY(同优先级同 id 序)", match_rule("POST", "/api/x", [r, specific]) == specific)


def test_match_priority():
    print("== 优先级排序(确定性) ==")
    wild = rule(path="/api/*", path_type=PATH_TYPE_WILDCARD, priority=0, id=10)
    exact = rule(path="/api/user/1", path_type=PATH_TYPE_EXACT, priority=100, id=20)
    check("精确优先于通配(即使 priority 更大)",
          match_rule("GET", "/api/user/1", [wild, exact]) == exact)
    param_a = rule(path="/api/user/:id", path_type=PATH_TYPE_PARAM, priority=5, id=30)
    param_b = rule(path="/api/user/:id", path_type=PATH_TYPE_PARAM, priority=1, id=31)
    check("同类型内 priority 小者优先",
          match_rule("GET", "/api/user/1", [param_a, param_b]) == param_b)
    param_c = rule(path="/api/user/:id", path_type=PATH_TYPE_PARAM, priority=1, id=32)
    check("同 priority 内 id 小者优先(创建早)",
          match_rule("GET", "/api/user/1", [param_b, param_c]) == param_b)


def test_match_disabled():
    print("== 停用规则排除 ==")
    off = rule(status=0, path="/api/x", path_type=PATH_TYPE_EXACT)
    on = rule(status=1, path="/api/x", path_type=PATH_TYPE_EXACT, id=2)
    check("停用规则不参与匹配", match_rule("GET", "/api/x", [off, on]) == on)
    check("全部停用 → 未命中", match_rule("GET", "/api/x", [off]) is None)


def test_match_determinism():
    print("== 双跑一致(确定性, constitution 原则 I) ==")
    rules = [
        rule(path="/api/*", path_type=PATH_TYPE_WILDCARD, priority=0, id=1),
        rule(path="/api/user/:id", path_type=PATH_TYPE_PARAM, priority=0, id=2),
        rule(path="/api/user/1", path_type=PATH_TYPE_EXACT, priority=9, id=3),
        rule(path="/api/user/1", path_type=PATH_TYPE_EXACT, method="POST", id=4),
        rule(status=0, path="/api/off", path_type=PATH_TYPE_EXACT, id=5),
    ]
    cases = ["GET /api/user/1", "POST /api/user/1", "GET /api/user/999", "GET /api/off", "GET /other"]
    for case in cases:
        m, _, p = case.partition(" ")
        first = match_rule(m, p, rules)
        second = match_rule(m, p, rules)
        first_id = first.id if first else None
        second_id = second.id if second else None
        check(f"双跑一致: {case}", first_id == second_id, f"{first_id} != {second_id}")


def test_match_empty_rules():
    print("== 空规则集 ==")
    check("空规则集未命中", match_rule("GET", "/api/x", []) is None)


# ---------------------------------------------------------------------------
# 变量渲染器
# ---------------------------------------------------------------------------


def test_render_basic():
    print("== 变量渲染: $request.path / query ==")
    snap = MockRequestSnapshot(path="/api/user/1",
                               query={"name": "tom", "tag": ["a", "b"]},
                               body={"user": {"name": "jerry", "items": [{"id": 7}]}},
                               headers={"X-Token": "abc"})
    check("path 渲染", render("{\"p\": \"$request.path\"}", snap) == "{\"p\": \"/api/user/1\"}")
    check("query 单值渲染", render("{\"q\": \"$request.query.name\"}", snap) == "{\"q\": \"tom\"}")
    check("query 多值取第一个", render("{\"q\": \"$request.query.tag\"}", snap) == "{\"q\": \"a\"}")
    check("body 点分渲染", render("{\"n\": \"$request.body.user.name\"}", snap) == "{\"n\": \"jerry\"}")
    check("body 数字索引渲染", render("{\"i\": \"$request.body.user.items.0.id\"}", snap) == "{\"i\": \"7\"}")
    check("header 渲染(忽略大小写)", render("{\"t\": \"$request.header.X-Token\"}", snap) == "{\"t\": \"abc\"}")
    check("headers 别名渲染", render("{\"t\": \"$request.headers.x-token\"}", snap) == "{\"t\": \"abc\"}")


def test_render_missing():
    print("== 变量取不到值 → 空串 ==")
    snap = MockRequestSnapshot(path="/api/x", query={"a": "1"}, body={}, headers={})
    check("未携带 query 参数", render("[$request.query.missing]", snap) == "[]")
    check("body 非 JSON 空", render("[$request.body.none]", snap) == "[]")
    check("未携带 header", render("[$request.header.none]", snap) == "[]")
    check("body 路径断裂", render("[$request.body.a.b.c]", snap) == "[]")
    check("无变量原样返回", render("{\"a\": 1}", snap) == "{\"a\": 1}")
    check("空 body 返回空", render("", snap) == "")


def test_render_no_exec():
    print("== 渲染零表达式 ==")
    # 变量只做字典替换 —— 任何函数/类名形态的 body 路径都取不到值, 且不执行
    snap = MockRequestSnapshot(path="/api/x", body={}, headers={})
    evil = "$request.body.__class__ $request.body.os.system"
    check("类名/函数形态不执行", render(evil, snap) == " ")


def test_variable_whitelist():
    print("== 变量白名单(未知变量拒绝) ==")
    legal = ["$request.path", "$request.query.name", "$request.query.a-b_c.1",
             "$request.body.user.name", "$request.body.items.0.id",
             "$request.header.X-Token", "$request.headers.x-token",
             "$request.body.__class__"]  # 魔术名形态是合法格式, 取不到值 → 空串(不执行)
    illegal = ["$randomInt", "$timestamp", "$request.foo", "$request.query.", "$request.body.",
               "$request.query.name)", "$request.body.a..b", "$request.QUERY.name",
               "$request.header"]
    # ${...} 不是本系统变量语法(render 不处理), 原样输出, 不属于拒绝面
    not_variable = ["${request.query.name}"]
    for v in legal:
        check(f"合法: {v}", bool(REQUEST_VARIABLE_PATTERN.match(v)))
    for v in illegal:
        check(f"非法: {v}", not bool(REQUEST_VARIABLE_PATTERN.match(v)))
    # 非变量语法($ 数字开头 / ${...})不在白名单校验面 —— 原样输出
    for v in not_variable:
        check(f"非变量语法放行: {v}", not bool(REQUEST_VARIABLE_PATTERN.match(v)))


def test_schema_body_validation():
    print("== 表单保存校验(schema) ==")
    def make(body=None):
        return MockRuleForm(project_id=1, name="规则", method="GET", path="/api/x",
                            response_body=body)
    make()  # 无 body 合法
    check("合法变量 body 放行", make("{\"a\": \"$request.query.name\"}") is not None)
    for bad in ("{\"a\": \"$randomInt\"}", "{\"a\": \"$timestamp\"}", "{\"a\": \"$request.body.a..b\"}"):
        try:
            make(bad)
            check(f"未知变量拦截: {bad}", False)
        except Exception:
            check(f"未知变量拦截: {bad}", True)
    # ${...} 非系统变量语法 → 放行(原样输出, render 不处理)
    check("非变量语法放行", make("{\"a\": \"${request.query.name}\"}") is not None)
    # 响应头必须是 JSON 对象
    try:
        MockRuleForm(project_id=1, name="规则", method="GET", path="/api/x",
                     response_headers="[1,2]")
        check("响应头非对象被拒", False)
    except Exception:
        check("响应头非对象被拒", True)
    # 路径必须以 / 开头
    try:
        MockRuleForm(project_id=1, name="规则", method="GET", path="api/x")
        check("路径不以 / 开头被拒", False)
    except Exception:
        check("路径不以 / 开头被拒", True)
    # * 只能在末尾
    try:
        MockRuleForm(project_id=1, name="规则", method="GET", path="/api/*/x")
        check("* 不在末尾被拒", False)
    except Exception:
        check("* 不在末尾被拒", True)


def test_delay_bounds():
    print("== 延迟与状态码边界 ==")
    for ok in (0, MAX_DELAY):
        form = MockRuleForm(project_id=1, name="r", method="GET", path="/api/x", delay=ok)
        check(f"delay={ok} 合法", form.delay == ok)
    for bad in (-1, MAX_DELAY + 1):
        try:
            MockRuleForm(project_id=1, name="r", method="GET", path="/api/x", delay=bad)
            check(f"delay={bad} 被拒", False)
        except Exception:
            check(f"delay={bad} 被拒", True)
    for ok in (MIN_STATUS_CODE, MAX_STATUS_CODE, 200):
        form = MockRuleForm(project_id=1, name="r", method="GET", path="/api/x", status_code=ok)
        check(f"status_code={ok} 合法", form.status_code == ok)
    for bad in (99, 600):
        try:
            MockRuleForm(project_id=1, name="r", method="GET", path="/api/x", status_code=bad)
            check(f"status_code={bad} 被拒", False)
        except Exception:
            check(f"status_code={bad} 被拒", True)


# ---------------------------------------------------------------------------
# 源码静态扫描(GATE-SEC 机器保证)
# ---------------------------------------------------------------------------


def test_static_source_scan():
    print("== 源码 AST 静态扫描(零出网 / 零执行) ==")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    targets = [
        "app/routers/mock/service.py",
        "app/routers/mock/admin.py",
        "app/core/mock_engine.py",
        "app/core/mock_render.py",
        "app/crud/mock/MockRuleDao.py",
    ]
    forbidden_imports = ("aiohttp", "httpx", "requests", "urllib.request", "http.client", "socket")
    forbidden_calls = ("eval", "exec")
    found = []
    for rel in targets:
        path = os.path.join(root, rel)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name.startswith(forbidden_imports):
                        found.append(f"{rel}: import {n.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith(forbidden_imports):
                    found.append(f"{rel}: from {node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_calls:
                    found.append(f"{rel}: {node.func.id}()")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in forbidden_calls:
                    found.append(f"{rel}: {node.func.attr}()")
    check("mock 模块无出网 import / 调用、无 eval/exec", not found, str(found))


def test_methods_enum():
    print("== 方法白名单 ==")
    expected = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "ANY"]
    check("METHODS 与契约一致", METHODS == expected, str(METHODS))
    check("MAX_DELAY = 5000", MAX_DELAY == 5000)


def test_cross_endpoint_constants():
    """跨端常量核对(constitution 原则 III): 前端镜像 consts/mock.ts 与后端权威定义一致"""
    print("== 跨端常量核对(前端镜像) ==")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
    frontend_file = os.path.join(root, "..", "frontend", "src", "consts", "mock.ts")
    check("前端镜像文件存在", os.path.isfile(frontend_file), frontend_file)
    if not os.path.isfile(frontend_file):
        return
    with open(frontend_file, encoding="utf-8") as f:
        text = f.read()
    for m in METHODS:
        check(f"前端包含方法 {m}", f"'{m}'" in text, m)
    check("前端 MAX_DELAY 一致", f"MOCK_MAX_DELAY = {MAX_DELAY}" in text)
    check("前端指认后端权威", "backend/app/enums/MockEnum.py" in text)


def main():
    test_path_type()
    test_normalize_path()
    test_match_exact()
    test_match_param()
    test_match_wildcard()
    test_match_any_method()
    test_match_priority()
    test_match_disabled()
    test_match_determinism()
    test_match_empty_rules()
    test_render_basic()
    test_render_missing()
    test_render_no_exec()
    test_variable_whitelist()
    test_schema_body_validation()
    test_delay_bounds()
    test_static_source_scan()
    test_methods_enum()
    test_cross_endpoint_constants()
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == '__main__':
    main()

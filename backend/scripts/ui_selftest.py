"""
UI 自动化自测脚本

不依赖 pytest(后端目前没有测试框架), 直接 python scripts/ui_selftest.py 即可跑。

覆盖:
- 步骤 DSL 校验(动作白名单正例 / 必填字段 / 定位策略枚举 / 未知字段丢弃)
- **动作白名单负例** —— evaluate / exec / run / script 必须在加载步骤时就被拒绝
- **SSRF 拦截** —— 协议 / 域名白名单 / DNS 解析后的私网地址 / 通配符 / 步骤内 URL
- **确定性等待** —— 无隐式 sleep、退避固定、多元素显式失败
- UI 断言汇总成接口用例同构结构

**不依赖数据库** —— 元素引用解析器做成可注入的, 这里用假的解析器。
"""
import asyncio
import ast
import inspect
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import ui_executor  # noqa: E402
from app.core.ui_executor import (ACTIONS, ASSERT_TYPE_MAPPING, STRATEGIES, UIExecutor,  # noqa: E402
                                 strip_internal, validate_steps)
from app.core.ui_locator import UILocatorError, resolve_unique  # noqa: E402
from app.utils.ui_security import UINavigationBlocked, check_url, domain_allowed, is_blocked_ip, resolve_step_url  # noqa: E402

FAILED = []
EXECUTOR_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "app", "core", "ui_executor.py")


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


def blocked(label, fn, expect_in_msg=None):
    """断言 fn 会抛 UINavigationBlocked, 且报错信息里含指定关键词"""
    try:
        fn()
        check(label, False, "但没有抛异常")
        return
    except UINavigationBlocked as e:
        if expect_in_msg and expect_in_msg not in e.message:
            check(label, False, f"报错信息里没有「{expect_in_msg}」: {e.message}")
            return
        check(label, True)
        return
    except Exception as e:
        check(label, False, f"抛的是非预期异常 {type(e).__name__}: {e}")
        return


class FakeElement(object):
    def __init__(self, id=1, strategy="css", locator="#btn", name_attr=None):
        self.id = id
        self.strategy = strategy
        self.locator = locator
        self.name_attr = name_attr


async def fake_resolver_ok(project_id, reference):
    """元素存在且启用"""
    return FakeElement(strategy="role", locator="button", name_attr="登录"), ""


async def fake_resolver_missing(project_id, reference):
    """元素不存在"""
    return None, f"引用的元素「{reference}」不存在"


async def fake_resolver_disabled(project_id, reference):
    """元素已停用"""
    return None, f"引用的元素「{reference}」已停用"


class FakeLocator(object):
    """假装自己是个 Playwright Locator"""

    def __init__(self, count):
        self._count = count

    async def count(self):
        return self._count

    @property
    def first(self):
        return self


# ============================================================================
# T023 步骤 DSL 校验
# ============================================================================


async def test_dsl_positive():
    print("== 步骤 DSL 校验(正例) ==")
    steps = [
        {"action": "goto", "url": "/login"},
        {"action": "click", "by": "css", "value": "#btn"},
        {"action": "fill", "by": "label", "value": "用户名", "text": "admin"},
        {"action": "press", "by": "css", "value": "#pwd", "text": "Enter"},
        {"action": "select", "element": "登录页.语言", "value": "zh"},
        {"action": "expect_text", "element": "登录页.提示", "value": "欢迎"},
        {"action": "expect_count", "element": "登录页.行", "value": "3"},
        {"action": "wait_for", "element": "登录页.弹窗", "state": "visible"},
        {"action": "wait_timeout", "timeout": 500},
        {"action": "set_viewport", "value": "1280x720"},
        {"action": "screenshot"},
        {"action": "back"},
        {"action": "reload"},
    ]
    valid, warnings = await validate_steps(1, steps, resolver=fake_resolver_ok)
    check("合法步骤全部通过", len(valid) == len(steps), f"实际 {len(valid)}/{len(steps)} {warnings}")
    check("合法步骤无告警", warnings == [], str(warnings))

    # 8 种定位策略都认
    for strategy in STRATEGIES:
        one = [{"action": "click", "by": strategy, "value": "x"}]
        v, w = await validate_steps(1, one, resolver=fake_resolver_ok)
        check(f"定位策略 {strategy} 被接受", len(v) == 1, str(w))


async def test_dsl_required_fields():
    print("== 步骤 DSL 校验(必填字段) ==")
    cases = [
        ("goto 缺 url", [{"action": "goto"}]),
        ("fill 缺 text", [{"action": "fill", "by": "css", "value": "#u"}]),
        ("press 缺 text", [{"action": "press", "by": "css", "value": "#u"}]),
        ("wait_for 缺 state", [{"action": "wait_for", "by": "css", "value": "#t"}]),
        ("wait_timeout 缺 timeout", [{"action": "wait_timeout"}]),
        ("select 缺 value", [{"action": "select", "element": "页面.元素"}]),
        ("expect_text 缺 value", [{"action": "expect_text", "element": "页面.元素"}]),
        ("set_viewport 缺 value", [{"action": "set_viewport"}]),
        ("upload 缺 files", [{"action": "upload", "by": "css", "value": "#f"}]),
    ]
    for label, bad in cases:
        valid, warnings = await validate_steps(1, bad, resolver=fake_resolver_ok)
        check(f"{label} 被丢弃", len(valid) == 0, f"实际保留 {len(valid)}")
        check(f"{label} 有告警", len(warnings) == 1, str(warnings))


async def test_dsl_strategy_enum():
    print("== 步骤 DSL 校验(定位策略枚举) ==")
    valid, warnings = await validate_steps(1, [{"action": "click", "by": "magic", "value": "x"}],
                                            resolver=fake_resolver_ok)
    check("非法定位策略被丢弃", len(valid) == 0)
    check("非法定位策略有告警", len(warnings) == 1 and "定位策略" in warnings[0], str(warnings))
    # 内联定位必须 by + value 都给
    valid, warnings = await validate_steps(1, [{"action": "click", "by": "css"}], resolver=fake_resolver_ok)
    check("内联定位缺 value 被丢弃", len(valid) == 0)
    check("内联定位缺 value 有告警", len(warnings) == 1 and "内联定位" in warnings[0], str(warnings))


async def test_dsl_unknown_field():
    print("== 步骤 DSL 校验(未知字段) ==")
    valid, warnings = await validate_steps(1, [{"action": "click", "by": "css", "value": "#b",
                                                 "javascript": "alert(1)", "foo": 1}],
                                            resolver=fake_resolver_ok)
    check("未知字段被丢弃", len(valid) == 1 and "javascript" not in valid[0] and "foo" not in valid[0],
          str(valid))
    check("未知字段有告警", len(warnings) == 1 and "未知字段" in warnings[0], str(warnings))


async def test_dsl_element_reference():
    print("== 步骤 DSL 校验(元素引用) ==")
    valid, warnings = await validate_steps(1, [{"action": "click", "element": "登录页.登录按钮"}],
                                            resolver=fake_resolver_ok)
    check("元素引用有效时保留步骤", len(valid) == 1, str(warnings))
    check("元素引用解析出定位策略", valid and valid[0].get("_strategy") == "role", str(valid))
    check("元素引用解析出定位值", valid and valid[0].get("_locator") == "button", str(valid))
    check("元素引用解析出可访问名称", valid and valid[0].get("_name_attr") == "登录", str(valid))
    # 存进库的必须是纯 DSL —— 内部字段不能落库
    clean = strip_internal(valid)
    check("内部字段被剥掉", clean and not any(k.startswith("_") for k in clean[0]), str(clean))
    check("业务字段保留", clean and clean[0].get("element") == "登录页.登录按钮", str(clean))
    check("动作保留", clean and clean[0].get("action") == "click", str(clean))

    valid, warnings = await validate_steps(1, [{"action": "click", "element": "登录页.没有"}],
                                            resolver=fake_resolver_missing)
    check("元素不存在时丢弃步骤", len(valid) == 0)
    check("元素不存在时有告警", len(warnings) == 1 and "不存在" in warnings[0], str(warnings))

    valid, warnings = await validate_steps(1, [{"action": "click", "element": "登录页.停用的"}],
                                            resolver=fake_resolver_disabled)
    check("元素已停用时丢弃步骤", len(valid) == 0)
    check("元素已停用时有告警", len(warnings) == 1 and "已停用" in warnings[0], str(warnings))


async def test_dsl_value_semantics():
    print("== 步骤 DSL 校验(value 的双重语义) ==")
    # expect_text 的 value 是期望值, 不能拿来当内联定位
    valid, warnings = await validate_steps(1, [{"action": "expect_text", "by": "css", "value": "x"}],
                                            resolver=fake_resolver_ok)
    check("expect_text 走内联定位被拒", len(valid) == 0)
    check("expect_text 走内联定位有告警", len(warnings) == 1 and "element" in warnings[0], str(warnings))
    # select 的 value 是选项值
    valid, _ = await validate_steps(1, [{"action": "select", "by": "css", "value": "zh"}],
                                    resolver=fake_resolver_ok)
    check("select 走内联定位被拒", len(valid) == 0)
    # click 的 value 就是定位值
    valid, _ = await validate_steps(1, [{"action": "click", "by": "css", "value": "#b"}],
                                    resolver=fake_resolver_ok)
    check("click 走内联定位被接受", len(valid) == 1)


async def test_dsl_all_invalid():
    print("== 步骤 DSL 校验(全部无效) ==")
    valid, warnings = await validate_steps(1, [{"action": "evaluate", "value": "x"},
                                               {"action": "click", "element": "登录页.没有"}],
                                            resolver=fake_resolver_missing)
    check("全部步骤无效时返回空", len(valid) == 0)
    check("全部步骤无效时每步都有告警", len(warnings) == 2, str(warnings))


# ============================================================================
# T024 动作白名单负例 —— 本 feature 新引入的安全面之一
# ============================================================================


async def test_action_whitelist_negative():
    print("== 动作白名单负例(执行代码的动作一律拒绝) ==")
    forbidden = ["evaluate", "exec", "run", "script", "eval", "evaluate_handle",
                 "add_script_tag", "add_init_script", "expose_function", "javascript"]
    for action in forbidden:
        valid, warnings = await validate_steps(1, [{"action": action, "value": "alert(1)"}],
                                                resolver=fake_resolver_ok)
        check(f"动作「{action}」被丢弃", len(valid) == 0, f"实际保留 {len(valid)}")
        check(f"动作「{action}」有告警", len(warnings) == 1 and "白名单" in warnings[0], str(warnings))
        # **在加载步骤时**就被拒绝 —— 白名单里根本没有这个动作
        check(f"动作「{action}」不在 ACTIONS 里", action not in ACTIONS)

    # 执行器侧也没有对应的分派方法 —— 双保险
    for action in ["evaluate", "exec", "run", "script"]:
        check(f"执行器没有 _do_{action} 分派", not hasattr(UIExecutor, f"_do_{action}"))

    # 源码里没有 eval / exec 调用 —— 平台不执行任何用户内容
    # 用 AST 判而不是字符串匹配: 字符串里出现 "eval" 这种字样不代表会执行它
    source = open(EXECUTOR_PATH, encoding="utf-8").read()
    called = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
    check("执行器源码没有调用 eval", "eval" not in called, str(called))
    check("执行器源码没有调用 exec", "exec" not in called, str(called))


# ============================================================================
# T025 SSRF 拦截 —— 本 feature 新引入的另一个安全面
# ============================================================================


def test_ssrf_scenario_d():
    """
    quickstart §3.4 场景 D 的**全表** —— SSRF 边界逐项走。

    D1 域名不在白名单 / D2 白名单里加了解析到 127.0.0.1 的域名 /
    D3 白名单里加了 169.254.169.254 / D4 重定向跳内网 /
    D5 清空白名单 / D6 非 http 协议 / D7 页面子资源
    """
    print("== SSRF 场景 D 全表(quickstart §3.4) ==")
    allow = ["example.com", "127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254",
             "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1", "0.0.0.0", "100.64.0.1",
             "172.16.0.1", "93.184.216.34"]

    # D1 域名不在白名单
    blocked("D1 域名不在白名单被拒",
            lambda: check_url("https://example.org/", allow), "不在本项目允许列表内")

    # D2 解析到 127.0.0.1
    blocked("D2 解析到 127.0.0.1 被拒",
            lambda: check_url("http://127.0.0.1/", allow), "内网地址")

    # D3 云元数据地址
    blocked("D3 解析到 169.254.169.254 被拒",
            lambda: check_url("http://169.254.169.254/latest/meta-data/", allow), "内网地址")

    # D4 重定向跳内网 —— 重定向的每一跳都走浏览器层的同一个判定函数
    executor = UIExecutor(SimpleNamespace(case_id=1, screenshot=True), 1, allow)
    check("D4 重定向跳内网那一跳被拦", not executor._host_allowed("169.254.169.254"))
    check("D4 重定向跳环回那一跳被拦", not executor._host_allowed("127.0.0.1"))
    check("D4 重定向跳私网那一跳被拦", not executor._host_allowed("192.168.1.1"))

    # D5 清空白名单 —— 不可执行, 不是默认放行
    blocked("D5 白名单为空即拒绝",
            lambda: check_url("https://example.com/", []), "尚未配置允许访问的域名")

    # D6 非 http/https 协议
    for url in ["file:///etc/passwd", "ftp://example.com/x", "data:text/html,x",
                "javascript:alert(1)"]:
        blocked(f"D6 协议 {url.split(':')[0]} 被拒",
                lambda u=url: check_url(u, allow), "仅支持 http / https 协议")

    # D7 页面子资源 —— 与 D4 走同一个浏览器层判定
    check("D7 子资源指向内网被拦", not executor._host_allowed("169.254.169.254"))
    check("D7 子资源指向环回被拦", not executor._host_allowed("127.0.0.1"))
    check("D7 白名单内的公网子资源放行", executor._host_allowed("93.184.216.34"))
    check("D7 白名单外的公网子资源被拦", not executor._host_allowed("example.org"))


def test_ssrf_protocol():
    print("== SSRF(协议白名单) ==")
    allow = ["example.com", "127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254",
             "::1", "fd00::1", "93.184.216.34"]
    for url in ["file:///etc/passwd", "ftp://example.com/x", "data:text/html,<h1>x</h1>",
                "javascript:alert(1)", "gopher://example.com"]:
        blocked(f"协议拦截 {url}", lambda u=url: check_url(u, allow), "仅支持 http / https 协议")


def test_ssrf_domain_whitelist():
    print("== SSRF(域名白名单) ==")
    blocked("域名不在白名单", lambda: check_url("https://example.org/", ["example.com"]),
            "不在本项目允许列表内")
    blocked("白名单为空 = 不可执行", lambda: check_url("https://example.com/", []),
            "尚未配置允许访问的域名")
    blocked("空域名", lambda: check_url("https:///x", ["example.com"]))
    blocked("没有主机名", lambda: check_url("", ["example.com"]))
    # 通配符
    check("*.example.com 匹配子域", domain_allowed("a.example.com", ["*.example.com"]))
    check("*.example.com 匹配多级子域", domain_allowed("a.b.example.com", ["*.example.com"]))
    check("*.example.com 不匹配 apex", not domain_allowed("example.com", ["*.example.com"]))
    check("精确匹配", domain_allowed("example.com", ["example.com"]))
    check("精确匹配不吃子域", not domain_allowed("a.example.com", ["example.com"]))
    check("大小写不敏感", domain_allowed("EXAMPLE.com", ["example.com"]))


def test_ssrf_private_ip():
    print("== SSRF(DNS 解析后的私网地址) ==")
    # 域名白名单里显式加上这些 IP, 让检查走到第 3 步(DNS 解析后逐 IP 拦截)
    private = ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
               "0.0.0.0", "100.64.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1"]
    for ip in private:
        # IPv6 字面量在 URL 里必须带方括号, 否则不是合法的 URL
        host = f"[{ip}]" if ":" in ip else ip
        blocked(f"内网地址 {ip} 被拒",
                lambda h=host: check_url(f"http://{h}/", private + ["example.com"]),
                "内网地址")
    # 公网 IP 必须放行(用 IP 字面量, 不依赖外部 DNS)
    check("公网 IP 放行", check_url("http://93.184.216.34/", ["93.184.216.34"]) == "http://93.184.216.34/")


def test_ssrf_ip_predicate():
    print("== SSRF(网段判定) ==")
    for ip in ["127.0.0.1", "127.1.2.3", "10.0.0.1", "172.16.5.5", "172.31.255.255",
               "192.168.0.1", "169.254.169.254", "0.0.0.0", "100.64.0.1",
               "::1", "fd00::1", "fe80::1", "::ffff:10.0.0.1", "not-an-ip"]:
        check(f"{ip} 判为内网", is_blocked_ip(ip))
    for ip in ["8.8.8.8", "93.184.216.34", "172.15.0.1", "172.32.0.1", "11.0.0.1", "2606:2800:220:1::1"]:
        check(f"{ip} 判为公网", not is_blocked_ip(ip))


def test_ssrf_step_url():
    print("== SSRF(步骤内的 URL) ==")
    allow = ["example.com", "93.184.216.34"]
    check("相对路径拼到 base_url",
          resolve_step_url("https://93.184.216.34/app", "/login", allow) == "https://93.184.216.34/login")
    blocked("相对路径拼出来的地址仍要过校验",
            lambda: resolve_step_url("https://other.com", "/x", allow),
            "不在本项目允许列表内")
    blocked("绝对 URL 直接过校验",
            lambda: resolve_step_url("https://example.com", "https://example.org/x", allow),
            "不在本项目允许列表内")
    blocked("步骤内的 file: 协议",
            lambda: resolve_step_url("https://example.com", "file:///etc/passwd", allow),
            "仅支持 http / https 协议")


def test_ssrf_subresource_guard():
    """页面子资源与重定向的每一跳都走同一个判定函数"""
    print("== SSRF(子资源 / 重定向逐跳) ==")
    executor = UIExecutor(SimpleNamespace(case_id=1, screenshot=True), 1,
                          ["example.com", "169.254.169.254", "93.184.216.34"])
    check("白名单内的私网主机被拦(子资源/重定向)", not executor._host_allowed("169.254.169.254"))
    check("白名单外的公网主机被拦", not executor._host_allowed("example.org"))
    check("白名单内的公网主机放行", executor._host_allowed("93.184.216.34"))


# ============================================================================
# T026 确定性等待
# ============================================================================


async def test_deterministic_wait():
    print("== 确定性等待 ==")
    source = open(EXECUTOR_PATH, encoding="utf-8").read()
    check("引擎没有 asyncio.sleep", "asyncio.sleep" not in source)
    check("引擎没有 time.sleep", "time.sleep" not in source)
    # wait_for_timeout 只允许出现在「用户显式配置的固定等待」与「固定退避」两处
    wait_count = source.count("wait_for_timeout(")
    check("wait_for_timeout 只出现 2 次(显式固定等待 + 固定退避)", wait_count == 2, f"实际 {wait_count}")
    # 退避次数与间隔必须是写死的常量, 不在运行时决定
    check("重试次数是模块级常量", isinstance(ui_executor.RETRY_TIMES, int))
    check("退避间隔是模块级常量", isinstance(ui_executor.RETRY_DELAY, float))
    check("重试次数固定", ui_executor.RETRY_TIMES == 2, str(ui_executor.RETRY_TIMES))
    check("退避间隔固定", ui_executor.RETRY_DELAY == 1.0, str(ui_executor.RETRY_DELAY))
    # 平台不得引入随机源
    check("引擎没有 import random", "import random" not in source)
    check("引擎没有 random.", "random." not in source)
    check("引擎没有 import numpy", "numpy" not in source)


async def test_multi_element_failure():
    print("== 多元素匹配必须显式失败 ==")
    try:
        await resolve_unique(FakeLocator(3))
        check("定位到 3 个元素时报错", False, "但没有抛异常")
    except UILocatorError as e:
        check("定位到 3 个元素时报错", True)
        check("多元素失败原因分类正确", e.reason == "element_ambiguous", e.reason)
        check("多元素报错信息说明了数量", "3" in e.message, e.message)
    try:
        await resolve_unique(FakeLocator(0))
        check("定位到 0 个元素时报错", False, "但没有抛异常")
    except UILocatorError as e:
        check("定位到 0 个元素时报错", True)
        check("找不到元素的失败原因分类正确", e.reason == "element_not_found", e.reason)
    ok = await resolve_unique(FakeLocator(1))
    check("恰好 1 个元素时正常返回", ok is not None)


# ============================================================================
# T027 断言汇总
# ============================================================================


def test_assert_summary():
    print("== UI 断言汇总 ==")
    check("断言类型映射齐全", set(ASSERT_TYPE_MAPPING) == {
        "expect_text", "expect_visible", "expect_hidden", "expect_url",
        "expect_count", "expect_value", "expect_enabled"}, str(ASSERT_TYPE_MAPPING))
    check("expect_count 映射到 length_eq", ASSERT_TYPE_MAPPING["expect_count"] == "length_eq")
    status, msg = UIExecutor._compare("equal", "a", "a")
    check("equal 相等时通过", status is True, msg)
    status, _ = UIExecutor._compare("equal", "a", "b")
    check("equal 不等时失败", status is False)
    status, _ = UIExecutor._compare("length_eq", 3, 3)
    check("length_eq 相等时通过", status is True)
    status, _ = UIExecutor._compare("length_eq", 3, 4)
    check("length_eq 不等时失败", status is False)

    executor = UIExecutor(SimpleNamespace(case_id=1, screenshot=True), 1, [])
    executor._add_assertion({"action": "expect_text"}, "equal", "欢迎", "欢迎")
    executor._add_assertion({"action": "expect_text"}, "equal", "欢迎", "登录成功")
    result = executor._result()
    import json
    asserts = json.loads(result["asserts"])
    check("asserts 是接口用例同构结构", all(
        isinstance(v, dict) and "status" in v and "msg" in v for v in asserts.values()), str(asserts))
    check("断言条目数正确", len(asserts) == 2, str(asserts))
    check("断言失败时用例判失败", result["status"] == 1, str(result["status"]))
    check("富断言明细带 assert_type", result["assertions"][0]["assert_type"] == "equal")
    check("富断言明细带 expected/actually",
          result["assertions"][0]["expected"] == "欢迎" and result["assertions"][0]["actually"] == "欢迎")
    executor2 = UIExecutor(SimpleNamespace(case_id=1, screenshot=True), 1, [])
    executor2._add_assertion({"action": "expect_text"}, "equal", "欢迎", "欢迎")
    check("断言全通过时用例判成功", executor2._result()["status"] == 0)


def test_executor_contract():
    print("== 执行器与契约的一致性 ==")
    contract = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "..", "specs", "002-ui-automation", "contracts", "steps.md")
    if not os.path.exists(contract):
        print("   (跳过: 找不到契约文件)")
        return
    text = open(contract, encoding="utf-8").read()
    for action in ["goto", "back", "reload", "click", "dblclick", "fill", "clear", "press",
                   "select", "check", "uncheck", "hover", "upload", "drag", "wait_for",
                   "wait_timeout", "expect_text", "expect_visible", "expect_hidden", "expect_url",
                   "expect_count", "expect_value", "expect_enabled", "screenshot", "scroll",
                   "set_viewport"]:
        check(f"契约里有动作 {action}", f"`{action}`" in text)
        check(f"ACTIONS 里有动作 {action}", action in ACTIONS)
    for strategy in ["css", "xpath", "id", "text", "role", "placeholder", "label", "testid"]:
        check(f"STRATEGIES 里有策略 {strategy}", strategy in STRATEGIES)
    check("STRATEGIES 恰好 8 种", len(STRATEGIES) == 8, str(len(STRATEGIES)))
    check("ACTIONS 恰好 26 种", len(ACTIONS) == 26, str(len(ACTIONS)))


def test_codegen_parser():
    """T033 —— codegen 脚本的静态解析"""
    print("== codegen 脚本静态解析 ==")
    from app.core.ui_recorder import element_name_of, normalize_page, parse_codegen

    # ---- sync 目标 ----
    sync = '''from playwright.sync_api import Playwright, sync_playwright

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    page.goto("https://example.com/login")
    page.get_by_label("用户名").fill("admin")
    page.get_by_role("button", name="登录").click()
    page.get_by_placeholder("验证码").fill("1234")
    page.get_by_test_id("submit").click()
    page.get_by_text("提交").click()
    page.locator("#captcha").click()
    page.locator("div.form").click()
    page.locator("xpath=//div[@id='x']").click()
    page.get_by_text("错误提示").wait_for()
    page.wait_for_timeout(500)
    page.set_viewport_size({"width": 1280, "height": 720})
    browser.close()
'''
    actions, warnings = parse_codegen(sync)
    check("sync 脚本解析出动作", len(actions) == 12, f"实际 {len(actions)}: {[a.action for a in actions]}")
    check("sync 脚本无告警", warnings == [], str(warnings))
    kinds = [a.action for a in actions]
    check("goto 被识别", actions[0].kind == "goto" and actions[0].params.get("url") == "https://example.com/login",
          str(actions[0].params))
    check("fill 被识别", "fill" in kinds, str(kinds))
    check("click 被识别", "click" in kinds, str(kinds))
    check("wait_for 被识别", "wait_for" in kinds, str(kinds))
    check("wait_timeout 被识别", "wait_timeout" in kinds, str(kinds))
    check("set_viewport 被识别", "set_viewport" in kinds, str(kinds))
    strategies = {a.strategy for a in actions if a.strategy}
    for strategy in ["label", "role", "placeholder", "testid", "text", "css", "xpath", "id"]:
        check(f"sync 识别出策略 {strategy}", strategy in strategies, str(strategies))
    role = [a for a in actions if a.strategy == "role"]
    check("role 的 accessible name 被解析", role and role[0].name_attr == "登录",
          str([(a.name_attr) for a in role]))
    id_ = [a for a in actions if a.strategy == "id"]
    check("#id 选择器归到 id 策略", id_ and id_[0].locator == "captcha",
          str([(a.locator) for a in id_]))
    xpath = [a for a in actions if a.strategy == "xpath"]
    check("xpath= 前缀被解析", xpath and xpath[0].locator == "//div[@id='x']",
          str([(a.locator) for a in xpath]))

    # ---- async 目标 ----
    async_script = '''async def run(playwright: AsyncPlaywright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()
    await page.goto("https://example.com/login")
    await page.get_by_label("用户名").fill("admin")
    await expect(page.get_by_text("登录成功")).to_be_visible()
    await expect(page.get_by_text("标题")).to_have_text("Pity")
    await browser.close()
'''
    actions, warnings = parse_codegen(async_script)
    check("async 脚本解析出动作", len(actions) == 4, f"实际 {len(actions)}")
    check("async 脚本无告警", warnings == [], str(warnings))
    kinds = [a.action for a in actions]
    check("async 的 expect 断言被识别", "expect_visible" in kinds and "expect_text" in kinds, str(kinds))
    expect_text = [a for a in actions if a.action == "expect_text"]
    check("expect(...).to_have_text 的期望值被解析",
          expect_text and expect_text[0].params.get("value") == "Pity", str(expect_text))

    # ---- 无法解析的行被跳过且不中断整段 ----
    mixed = '''page.goto("https://example.com/login")
page.get_by_label("用户名").fill("admin")
this is not python at all !!!
page.get_by_role("button", name="登录").click()
'''
    actions, warnings = parse_codegen(mixed)
    check("坏行不中断整段解析", len(actions) == 3, f"实际 {len(actions)}")
    check("坏行有告警", len(warnings) >= 1, str(warnings))

    # ---- 含自由代码的行被跳过(第二个安全面) ----
    free_code = '''page.goto("https://example.com/login")
page.evaluate("() => { document.cookie }")
page.add_script_tag(content="alert(1)")
page.get_by_label("用户名").fill("admin")
'''
    actions, warnings = parse_codegen(free_code)
    check("自由代码的行被跳过", len(actions) == 2, f"实际 {len(actions)}: {[a.action for a in actions]}")
    check("自由代码有告警", len(warnings) == 2, str(warnings))
    check("告警说明了是执行代码的动作",
          all("执行代码" in w for w in warnings), str(warnings))
    # 解析器源码里不能有 eval / exec
    recorder_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "app", "core", "ui_recorder.py")
    recorder_src = open(recorder_path, encoding="utf-8").read()
    called = set()
    for node in ast.walk(ast.parse(recorder_src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
    check("解析器没有调用 eval", "eval" not in called, str(called))
    check("解析器没有调用 exec", "exec" not in called, str(called))
    check("解析器没有 import importlib", "importlib" not in recorder_src)

    # ---- 页面归一与元素命名 ----
    name, url = normalize_page("https://example.com/login")
    check("页面按 origin+path 归一", url == "https://example.com/login" and name == "login",
          f"{name} {url}")
    name, url = normalize_page("https://example.com/")
    check("根路径用主机名做页面名", name == "example.com", f"{name} {url}")
    check("role 元素名取可访问名称", element_name_of("role", "button", "登录") == "登录")
    check("label 元素名取定位值", element_name_of("label", "用户名", None) == "用户名")
    check("css 元素名去掉特殊字符", element_name_of("css", "#login-btn", None) == "login-btn",
          element_name_of("css", "#login-btn", None))


def test_cross_feature_contract():
    """
    T049 —— 跨 feature 契约核对。

    1. 001 的 DSL 规则 11–14 引用的动作白名单, 权威出处必须是 002 的契约
    2. 后端 `ACTIONS` / `STRATEGIES` 与前端镜像**无漂移**
    """
    print("== 跨 feature 契约核对(T049) ==")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dsl_path = os.path.join(root, "specs", "001-ai-workbench", "contracts", "dsl.md")
    steps_path = os.path.join(root, "specs", "002-ui-automation", "contracts", "steps.md")
    frontend_path = os.path.join(root, "frontend", "src", "consts", "uiTest.ts")
    for p in (dsl_path, steps_path, frontend_path):
        if not os.path.exists(p):
            print(f"    (跳过: 找不到 {p})")
            return
    dsl = open(dsl_path, encoding="utf-8").read()
    steps = open(steps_path, encoding="utf-8").read()
    frontend = open(frontend_path, encoding="utf-8").read()

    # 1. 001 的规则 11–14 必须把动作白名单的权威出处指向 002
    for rule in ["规则 11", "规则 12", "规则 13", "规则 14"]:
        check(f"001 的契约里有 {rule}", rule in dsl)
    check("001 的规则 11 指向 002 的契约为准",
          "002" in dsl and "为准" in dsl)
    check("002 的契约是动作集合的权威出处",
          "封闭集合" in steps and "ACTIONS" in steps)

    # 2. 后端与前端常量无漂移
    block = frontend.split('export const UI_ACTIONS')[1].split('export const UI_ACTION_MAP')[0]
    frontend_actions = set(re.findall(r"name: '([a-z_]+)'", block))
    check("前端镜像的动作数与后端一致", len(frontend_actions) == len(ACTIONS),
          f"前端 {len(frontend_actions)} 后端 {len(ACTIONS)}")
    missing = set(ACTIONS) - frontend_actions
    extra = frontend_actions - set(ACTIONS)
    check("前端没有多出后端没有的动作", not extra, str(extra))
    check("前端没有漏掉后端有的动作", not missing, str(missing))
    frontend_strategies = set(re.findall(r"^  ([a-z]+): \{ label:", frontend, re.M))
    check("前端镜像的定位策略与后端一致", frontend_strategies == set(STRATEGIES),
          f"前端 {frontend_strategies} 后端 {set(STRATEGIES)}")
    # 前端文件头必须指认后端的权威出处(constitution 原则 III)
    check("前端文件头指认了后端权威出处", "backend/app/core/ui_executor.py" in frontend)


def test_security_boundaries():
    """
    两个新安全面的边界断言 —— 防止以后改代码时无声退化。

    ① SSRF: Service Worker 的请求与 WebSocket 握手**都绕过 page.route**(实测),
       必须靠 service_workers="block" 与 route_web_socket 补上
    ② 录制脚本/模板: 用户可控的文本不能进未沙箱的 Jinja2
    """
    print("== 安全边界回归 ==")
    source = open(EXECUTOR_PATH, encoding="utf-8").read()

    # ① SSRF 边界
    check('上下文禁用了 Service Worker', 'service_workers="block"' in source)
    check('注册了 WebSocket 握手拦截', 'route_web_socket' in source)
    check('WebSocket 拦截用的是同一套域名白名单判定', '_host_allowed' in source)

    # ② upload 动作不能把用户填的路径直接交给浏览器
    upload_start = source.find('async def _do_upload')
    upload_end = source.find('async def ', upload_start + 10)
    upload_block = source[upload_start:upload_end] if upload_start > 0 else ''
    check('upload 动作存在', bool(upload_block))
    check('upload 动作只接受已登记到 OSS 的文件',
          'PityOssDao.query_record' in upload_block, upload_block[:120])
    check('upload 动作不把用户路径直接给 set_input_files',
          'set_input_files(files' not in upload_block and 'set_input_files(paths' in upload_block,
          upload_block[:200])

    # ③ 沙箱渲染 —— 载荷必须原样返回而不是被执行
    from app.core.render import Render
    payload = "${cycler.__init__.__globals__.os.popen('id').read()}"
    unsafe = str(Render.render({}, payload))
    check('未沙箱渲染确实能取到系统信息(说明载荷有效)', 'uid=' in unsafe, unsafe[:60])
    safe = str(Render.render_safe({}, payload))
    check('沙箱渲染挡住了载荷', 'uid=' not in safe and 'popen' in safe, safe[:80])
    check('沙箱渲染正常变量仍可用', Render.render_safe({'name': 'admin'}, '${name}') == 'admin')
    check('沙箱渲染全局函数仍可用', Render.render_safe({}, '${random_int(1,1)}') == '1')
    # UI 执行器必须走沙箱
    from app.core.ui_executor import UIExecutor
    executor = UIExecutor(SimpleNamespace(case_id=1, screenshot=True), 1, [])
    check('UI 执行器走沙箱渲染', 'popen' in str(executor.render(payload)))


def main():
    asyncio.run(test_dsl_positive())
    asyncio.run(test_dsl_required_fields())
    asyncio.run(test_dsl_strategy_enum())
    asyncio.run(test_dsl_unknown_field())
    asyncio.run(test_dsl_element_reference())
    asyncio.run(test_dsl_value_semantics())
    asyncio.run(test_dsl_all_invalid())
    asyncio.run(test_action_whitelist_negative())
    test_ssrf_scenario_d()
    test_ssrf_protocol()
    test_ssrf_domain_whitelist()
    test_ssrf_private_ip()
    test_ssrf_ip_predicate()
    test_ssrf_step_url()
    test_ssrf_subresource_guard()
    asyncio.run(test_deterministic_wait())
    asyncio.run(test_multi_element_failure())
    test_assert_summary()
    test_executor_contract()
    test_codegen_parser()
    test_cross_feature_contract()
    test_security_boundaries()
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == '__main__':
    main()

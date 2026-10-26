"""
录制脚本解析 —— 把本地 `npx playwright codegen --target python` 的输出翻译成步骤 DSL

**安全边界(本 feature 新引入的第二个安全面)**:
导入的脚本是**外部输入**。平台只做**静态文本解析** —— 用 `ast` 解析语法树,
**绝不 eval / exec / 在浏览器里跑脚本内容**。脚本里的 `page.evaluate(...)` 这类
「执行一段代码」的行会被跳过并在告警里说明。

解析用 `ast` 而不是正则: 正则处理不了多行调用与关键字参数, `ast` 能;
而 `ast.parse` 只产出语法树, 不执行任何代码。

无法解析的行**跳过并说明原因**, 不中断整段导入 —— 整段失败会让用户白录一遍。
"""
import ast
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

# Playwright 的定位方法 → (策略, 定位值取自第几个位置参数)
LOCATOR_METHODS = {
    "get_by_text": "text",
    "get_by_role": "role",
    "get_by_label": "label",
    "get_by_placeholder": "placeholder",
    "get_by_test_id": "testid",
    "locator": "locator",
}

# Playwright 的动作方法 → 我们的动作名
ACTION_METHODS = {
    "click": "click",
    "dblclick": "dblclick",
    "fill": "fill",
    "clear": "clear",
    "press": "press",
    "select_option": "select",
    "check": "check",
    "uncheck": "uncheck",
    "hover": "hover",
    "set_input_files": "upload",
    "scroll_into_view_if_needed": "scroll",
    "screenshot": "screenshot",
    "wait_for": "wait_for",
}

# 明确「读取」而不是「动作」的方法 —— 不产生步骤, 跳过并说明
READ_METHODS = {
    "inner_text", "text_content", "input_value", "get_attribute", "count",
    "is_visible", "is_hidden", "is_enabled", "is_disabled", "is_checked", "is_unchecked",
    "bounding_box", "evaluate", "evaluate_handle", "get_attribute",
}

# pytest 风格的断言 → 我们的动作名
ASSERT_METHODS = {
    "to_be_visible": "expect_visible",
    "to_be_hidden": "expect_hidden",
    "to_have_text": "expect_text",
    "to_have_value": "expect_value",
    "to_have_count": "expect_count",
    "to_be_enabled": "expect_enabled",
    "to_have_url": "expect_url",
}

# 明确禁止执行代码的动作 —— 遇到就跳过并说明
FORBIDDEN_METHODS = {
    "evaluate", "evaluate_handle", "add_script_tag", "add_init_script",
    "expose_function", "expose_binding", "run",
}

# locator("text=xxx") 这种前缀写法 → 策略
LOCATOR_PREFIX = {
    "text": "text",
    "role": "role",
    "label": "label",
    "placeholder": "placeholder",
    "testid": "testid",
    "id": "id",
    "css": "css",
    "xpath": "xpath",
}

ID_PATTERN = re.compile(r"^#[A-Za-z_][A-Za-z0-9_\-]*$")


def _literal(node):
    """只取字面量 —— `ast.literal_eval` 不执行任何代码"""
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _arg_values(args) -> List:
    return [_literal(a) for a in args]


def _kwarg(keywords) -> dict:
    result = dict()
    for kw in keywords:
        if kw.arg is None:
            # **kwargs 展开 —— 无法静态确定, 忽略
            continue
        result[kw.arg] = _literal(kw.value)
    return result


def _unwrap(node):
    """剥掉 await / 括号"""
    while isinstance(node, (ast.Await, ast.Starred)):
        node = node.value
    return node


class ParsedAction(object):
    """解析出的一条动作"""

    def __init__(self, kind: str, **kwargs):
        self.kind = kind          # goto / action / assert
        self.line = 0
        self.strategy = None
        self.locator = None
        self.name_attr = None
        self.action = None
        self.params = dict()
        self.raw = None
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f"<ParsedAction {self.kind} {self.action or self.params.get('url')} line={self.line}>"


def _parse_locator_call(call: ast.Call) -> Optional[Tuple[str, object, Optional[str]]]:
    """
    解析一个定位调用 → (策略, 定位值, name_attr)
    """
    if not isinstance(call.func, ast.Attribute):
        return None
    method = call.func.attr
    if method in FORBIDDEN_METHODS:
        return None
    args = _arg_values(call.args)
    kwargs = _kwarg(call.keywords)
    if method == "locator":
        if not args or not isinstance(args[0], str):
            return None
        selector = args[0]
        # locator("xpath=//div") / locator("text=xxx") 这类前缀写法
        if "=" in selector:
            prefix, _, rest = selector.partition("=")
            prefix = prefix.strip().lower()
            if prefix in LOCATOR_PREFIX:
                strategy = LOCATOR_PREFIX[prefix]
                if strategy == "role":
                    return strategy, rest, kwargs.get("name")
                return strategy, rest, None
        if ID_PATTERN.match(selector):
            # #foo 这种 id 选择器归到 id 策略
            return "id", selector[1:], None
        return "css", selector, None
    if method in LOCATOR_METHODS:
        strategy = LOCATOR_METHODS[method]
        if not args:
            return None
        value = args[0]
        if strategy == "role":
            # get_by_role("button", name="登录")
            return "role", value, kwargs.get("name")
        return strategy, value, None
    return None


def _build_step(action: str, strategy: Optional[str], locator, name_attr: Optional[str],
                params: dict) -> dict:
    """组装的步骤 —— 有元素引用时优先用 element, 否则用内联定位"""
    step = {"action": action}
    if strategy and locator is not None:
        step["by"] = strategy
        step["value"] = locator
        if name_attr:
            step["name"] = name_attr
    for key, value in params.items():
        if value is not None:
            step[key] = value
    return step


def parse_codegen(script: str) -> Tuple[List[ParsedAction], List[str]]:
    """
    静态解析 codegen 脚本。

    :param script: 脚本文本
    :return: (解析出的动作列表, 跳过原因列表)
    """
    actions: List[ParsedAction] = []
    warnings: List[str] = []
    if not script or not script.strip():
        return actions, warnings
    tree, failed_lines = _parse_tree(script)
    if tree is None:
        warnings.append("脚本语法无法解析, 已整体跳过")
        return actions, warnings
    # 兜底逐行解析时坏掉的行 —— 必须说明, 不能静默丢弃(FR-017)
    for line in failed_lines:
        warnings.append(f"第 {line} 行无法解析，已跳过")
    consumed = set()
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    # 外层调用在前(BFS 顺序), 保证链式调用不会被拆开处理
    for call in calls:
        if id(call) in consumed:
            continue
        _handle_call(call, actions, warnings, consumed)
    return actions, warnings


def _parse_tree(script: str) -> Tuple[Optional[ast.AST], List[int]]:
    """
    整段解析 —— 失败则退化成逐行解析, 尽量 salvage 出可用的行。

    :return: (语法树, 解析失败的行号)
    """
    try:
        return ast.parse(script), []
    except SyntaxError:
        pass
    lines = script.splitlines()
    tree = ast.Module(body=[], type_ignores=[])
    failed: List[int] = []
    ok = False
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            sub = ast.parse(stripped)
        except SyntaxError:
            failed.append(index)
            continue
        tree.body.extend(sub.body)
        ok = True
    return (tree if ok else None), failed


def _handle_call(call: ast.Call, actions: List[ParsedAction], warnings: List[str], consumed: set):
    func = call.func
    if not isinstance(func, ast.Attribute):
        return
    method = func.attr
    line = getattr(call, "lineno", 0)

    # ---- 断言: expect(locator).to_xxx(...) ----
    if method in ASSERT_METHODS and isinstance(func.value, ast.Call):
        inner = func.value
        consumed.add(id(inner))
        if not isinstance(inner.func, ast.Name) or inner.func.id != "expect":
            return
        if not inner.args:
            warnings.append(f"第 {line} 行无法解析: expect 缺少目标")
            return
        locator_call = _unwrap(inner.args[0])
        if not isinstance(locator_call, ast.Call):
            warnings.append(f"第 {line} 行无法解析: expect 的目标不是定位调用")
            return
        consumed.add(id(locator_call))
        parsed = _parse_locator_call(locator_call)
        if parsed is None:
            warnings.append(f"第 {line} 行无法解析: 断言目标不是受支持的定位方式")
            return
        strategy, locator, name_attr = parsed
        args = _arg_values(call.args)
        kwargs = _kwarg(call.keywords)
        action = ASSERT_METHODS[method]
        params = dict()
        if action in ("expect_text", "expect_value", "expect_count", "expect_url"):
            params["value"] = args[0] if args else kwargs.get("expected")
            if params.get("value") is None:
                warnings.append(f"第 {line} 行无法解析: 断言缺少期望值")
                return
        item = ParsedAction("assert", line=line, action=action, strategy=strategy,
                            locator=locator, name_attr=name_attr, params=params)
        actions.append(item)
        return

    # ---- page.xxx(...) ----
    if isinstance(func.value, ast.Name) and func.value.id == "page":
        consumed.add(id(call))
        args = _arg_values(call.args)
        kwargs = _kwarg(call.keywords)
        if method in FORBIDDEN_METHODS:
            warnings.append(f"第 {line} 行无法解析，已跳过: {method}(...) 属于执行代码的动作，平台不执行录制脚本")
            return
        if method == "goto":
            if not args or not isinstance(args[0], str):
                warnings.append(f"第 {line} 行无法解析: goto 缺少地址")
                return
            actions.append(ParsedAction("goto", line=line, params={"url": args[0]}))
            return
        if method == "wait_for_timeout":
            if not args or not isinstance(args[0], (int, float)):
                warnings.append(f"第 {line} 行无法解析: wait_for_timeout 缺少毫秒数")
                return
            actions.append(ParsedAction("action", line=line, action="wait_timeout",
                                        params={"timeout": int(args[0])}))
            return
        if method == "set_viewport_size":
            size = args[0] if args else kwargs.get("viewport")
            if isinstance(size, dict) and size.get("width") and size.get("height"):
                actions.append(ParsedAction("action", line=line, action="set_viewport",
                                            params={"value": f"{size['width']}x{size['height']}"}))
            else:
                warnings.append(f"第 {line} 行无法解析: set_viewport_size 的参数不是 {{width, height}}")
            return
        if method == "go_back":
            actions.append(ParsedAction("action", line=line, action="back"))
            return
        if method == "reload":
            actions.append(ParsedAction("action", line=line, action="reload"))
            return
        if method == "screenshot":
            # page.screenshot(path="x.png") —— 路径是本地的, 平台用不上, 只记动作
            actions.append(ParsedAction("action", line=line, action="screenshot"))
            return
        if method in READ_METHODS:
            warnings.append(f"第 {line} 行已跳过: {method}(...) 是读取操作，不产生步骤")
            return
        warnings.append(f"第 {line} 行无法解析，已跳过: page.{method}(...) 不是受支持的调用")
        return

    # ---- page.locator(...).action(...) ----
    if isinstance(func.value, ast.Call):
        inner = func.value
        if not isinstance(inner.func, ast.Attribute):
            return
        locator_method = inner.func.attr
        if locator_method in FORBIDDEN_METHODS:
            consumed.add(id(inner))
            warnings.append(f"第 {line} 行无法解析，已跳过: {locator_method}(...) 属于执行代码的动作，平台不执行录制脚本")
            return
        if locator_method not in LOCATOR_METHODS:
            return
        consumed.add(id(inner))
        parsed = _parse_locator_call(inner)
        if parsed is None:
            warnings.append(f"第 {line} 行无法解析: 定位参数不是字面量")
            return
        strategy, locator, name_attr = parsed
        if method in READ_METHODS:
            warnings.append(f"第 {line} 行已跳过: {method}(...) 是读取操作，不产生步骤")
            return
        if method not in ACTION_METHODS:
            warnings.append(f"第 {line} 行无法解析，已跳过: {method}(...) 不是受支持的动作")
            return
        action = ACTION_METHODS[method]
        args = _arg_values(call.args)
        kwargs = _kwarg(call.keywords)
        params = dict()
        if action == "fill":
            params["text"] = args[0] if args else kwargs.get("value")
        elif action == "press":
            params["text"] = args[0] if args else kwargs.get("key")
        elif action == "select":
            params["value"] = args[0] if args else kwargs.get("value")
        elif action == "upload":
            files = args[0] if args else kwargs.get("files")
            if isinstance(files, str):
                files = [files]
            if not isinstance(files, list):
                warnings.append(f"第 {line} 行无法解析: set_input_files 的参数不是文件名列表")
                return
            params["files"] = files
        elif action == "wait_for":
            state = kwargs.get("state")
            params["state"] = state if state else "visible"
        if action == "fill" and params.get("text") is None:
            warnings.append(f"第 {line} 行无法解析: fill 缺少文本")
            return
        if action == "press" and params.get("text") is None:
            warnings.append(f"第 {line} 行无法解析: press 缺少按键")
            return
        actions.append(ParsedAction("action", line=line, action=action, strategy=strategy,
                                    locator=locator, name_attr=name_attr, params=params))
        return


# ============================================================================
# 自动建页面与元素
# ============================================================================


def normalize_page(url: str) -> Tuple[str, str]:
    """
    按 origin + path 归一页面。

    :return: (页面名, 归一后的地址)
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else url
    path = parsed.path or "/"
    segments = [s for s in path.split("/") if s]
    if segments:
        name = segments[-1]
    else:
        name = parsed.netloc or origin
    # 页面名最长 64
    return name[:64], origin + path


def element_name_of(strategy: str, locator, name_attr: Optional[str]) -> str:
    """按定位方式生成可读的元素名"""
    if strategy == "role" and name_attr:
        return str(name_attr)[:64]
    if strategy in ("text", "label", "placeholder", "testid", "id"):
        return str(locator)[:64]
    # css / xpath 之类 —— 取最后一段, 去掉特殊字符
    raw = str(locator)
    tail = re.split(r"[\\s>]+", raw)[-1] if raw else raw
    cleaned = re.sub(r"[^\w\-一-龥]", "", tail)
    return (cleaned or raw)[:64]


async def build_pages_and_elements(project_id: int, actions: List[ParsedAction], user_id: int
                                   ) -> Tuple[List[dict], List[dict], List[dict], dict]:
    """
    自动建页面与元素, 并产出引用元素的步骤。

    - 页面按 URL 的 origin + path 归一后建立或复用
    - 元素按 `(project_id, page_id, strategy, locator, name_attr)` 去重, 已存在则复用只追加步骤
    - 元素名冲突时追加序号后缀, 避免「页面名.元素名」出现歧义

    :return: (页面列表, 元素列表, 步骤列表, 统计)
    """
    from app.crud.ui.UIElementDao import UIElementDao
    from app.crud.ui.UIPageDao import UIPageDao

    pages = list()
    elements = list()
    steps: List[dict] = []
    stats = dict(pages_created=0, elements_created=0, elements_reused=0)
    page_names = dict()      # page_id -> 页面名
    name_used = dict()       # page_id -> 已用过的元素名集合

    current_page_id = None

    async def ensure_page(url: str) -> int:
        """按 origin + path 归一后建立或复用页面"""
        nonlocal pages, stats
        page_name, normalized = normalize_page(url)
        exist = await UIPageDao.query_page_by_name(project_id, page_name, None)
        if exist is not None:
            page_names[exist.id] = exist.name
            return exist.id
        page = await UIPageDao.insert_page(name=page_name, project_id=project_id,
                                            user_id=user_id, url=normalized)
        page_names[page.id] = page.name
        pages.append(page)
        stats["pages_created"] += 1
        return page.id

    for item in actions:
        if item.kind == "goto":
            url = item.params.get("url")
            current_page_id = await ensure_page(url)
            steps.append({"action": "goto", "url": url})
            continue
        if current_page_id is None:
            # 没有 page.goto 就无法确定页面归属 —— 跳过, 不硬造页面
            steps.append({"action": item.action, "_skipped": "脚本没有 page.goto, 无法确定页面归属"})
            continue
        step = {"action": item.action}
        for key, value in item.params.items():
            step[key] = value
        if item.strategy and item.locator is not None:
            name = element_name_of(item.strategy, item.locator, item.name_attr)
            # 同页面内名字冲突 -> 加序号, 保证「页面名.元素名」唯一
            used = name_used.setdefault(current_page_id, set())
            final_name = name
            suffix = 2
            while final_name in used:
                final_name = f"{name}_{suffix}"
                suffix += 1
            used.add(final_name)
            element, duplicated = await UIElementDao.insert_element(
                name=final_name, strategy=item.strategy, locator=item.locator,
                project_id=project_id, page_id=current_page_id, user_id=user_id,
                name_attr=item.name_attr)
            if duplicated:
                stats["elements_reused"] += 1
            else:
                stats["elements_created"] += 1
                elements.append(element)
            step["element"] = f"{page_names.get(current_page_id, current_page_id)}.{element.name}"
        steps.append(step)
    return pages, elements, steps, stats

"""
用例生成 —— 提示词与 DSL 解析(US1)

**本文件是用例 DSL 规范的 backend 侧出处**, 前端镜像在
`frontend/src/consts/aiWorkbench.ts` —— **改一处必须同时改另一处**
(契约见 `specs/001-ai-workbench/contracts/dsl.md` §8)。

## 常量的权威归属

| 常量 | 权威位置 | 本文件 |
|---|---|---|
| 断言类型白名单(14 种) | `app/enums/AIWorkbenchEnum.py` | 引用 |
| 优先级 / 类别 / 测试类型 | `app/enums/AIWorkbenchEnum.py` | 引用 |
| **UI 步骤动作白名单** | `app/core/ui_executor.py` 的 `ACTIONS` | **委托 `validate_steps` 校验** |

> UI 动作白名单的真正权威是 UI 自动化子系统的契约
> (`specs/002-ui-automation/contracts/steps.md`), 本 feature 的规则 11~13
> **直接复用 `ui_executor.validate_steps`** —— 不另写一套步骤校验器,
> 两处漂移会让「生成时通过、执行时丢弃」的步骤悄悄消失。

## 核心原则

**AI 只翻译, 落地由确定性内核做。** 违反规则的**字段被丢弃并记 warning**,
不整批失败; 只有一条用例的**所有**内容都非法时, 整条草稿才被丢弃
(契约见 `contracts/dsl.md` §5)。

## 确定性声明

本模块产出的 DSL 由模型生成, **不可重放**。确定性的锚点是草稿的
**当前 content 版本** —— 重复采纳同一版本结果逐字段相等。
"""
import re
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.ai_prompts import base
from app.core.ui_executor import ACTIONS, STRATEGIES, strip_internal, validate_steps
from app.enums.AIWorkbenchEnum import (ASSERT_TYPE_KEYS, ASSERT_TYPES, BODY_TYPES,
                                        CASE_CATEGORIES, CONSTRUCTOR_TYPES, DEFAULT_BODY_TYPE,
                                        DEFAULT_CATEGORY, DEFAULT_PRIORITY, DEFAULT_REQUEST_METHOD,
                                        OUT_PARAMETER_SOURCES, PRIORITIES, REQUEST_METHODS,
                                        TEST_TYPES)

# DSL 的顶层结构 —— 只有 cases 一个键
DSL_ROOT_KEYS = ("cases",)

# 单批生成用例数上限(research.md 的 Performance Goals)
MAX_CASES = 200

# 变量名规则 —— 断言 `actually` 的 `${变量}` 与出参名都要满足
VARIABLE_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"

# 出参名长度上限(pity_out_parameters.name = String(24))
MAX_OUT_PARAMETER_NAME = 24

# 用例名长度上限(pity_testcase.name = String(32))
MAX_CASE_NAME = 32

# 断言名长度上限(pity_testcase_asserts.name = String(32))
MAX_ASSERT_NAME = 32

# 步骤描述长度上限(pity_constructor.name = String(64))
MAX_CONSTRUCTOR_NAME = 64

# 标签长度上限(pity_testcase.tag = String(64))
MAX_TAG = 64

# UI 步骤需要定位的动作 —— 规则 12 的判定依据
# 与 ui_executor 的 ACTIONS[*]["target"] 一致, 这里只做「必须有 element 或内联定位」的判断
TARGET_ACTIONS = tuple(name for name, spec in ACTIONS.items() if spec.get("target"))

# `${变量}` 的匹配 —— `${data.id}` 取根名 `data`
VARIABLE_PATTERN = re.compile(r"\$\{\s*([^{}]+?)\s*\}")


def supported_test_types() -> tuple:
    """支持的测试类型 —— 与 AIWorkbenchEnum 的权威定义一致"""
    return tuple(TEST_TYPES)


def supported_assert_types() -> tuple:
    """断言类型白名单(14 种)"""
    return tuple(ASSERT_TYPE_KEYS)


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------


def _assert_type_doc() -> str:
    return "\n".join(f"  - {key}: {label}" for key, label in ASSERT_TYPES.items())


def _method_doc() -> str:
    return " / ".join(REQUEST_METHODS)


def _category_doc() -> str:
    return " / ".join(CASE_CATEGORIES)


def _body_type_doc() -> str:
    return "0=none / 1=json / 2=form / 3=x-form / 4=binary / 5=GraphQL"


def _source_doc() -> str:
    return "0=Body(TEXT) / 1=Body(JSON) / 2=Header / 3=Cookie / 4=HTTP状态码"


def _constructor_type_doc() -> str:
    return "0=测试用例 / 1=SQL / 2=Redis / 3=Python脚本 / 4=HTTP"


def _ui_section() -> str:
    """Web UI 用例的规范段 —— 放在 system prompt 里"""
    goto = "goto / back / reload"
    click = "click / dblclick / fill / clear / press / select / check / uncheck / hover / upload / drag"
    expect = "expect_text / expect_visible / expect_hidden / expect_url / expect_count / expect_value / expect_enabled"
    return f"""
## Web UI 用例(test_type = web)

Web UI 用例**没有** `request`, 改成 `ui` 块:

"ui": {{
  "base_url": "起始地址, 必填",
  "viewport": "1280x720, 默认 1280x720",
  "timeout": 30,
  "steps": [
    {{"action": "goto", "url": "/login"}},
    {{"action": "fill", "element": "登录页.用户名", "text": "admin"}},
    {{"action": "click", "element": "登录页.登录按钮"}},
    {{"action": "expect_text", "element": "登录页.错误提示", "value": "用户名或密码错误"}}
  ]
}}

`element` 的格式是「页面名.元素名」, 引用的是**元素库里已启用**的元素 ——
引用不存在的元素, 那一步会被丢弃, 草稿也无法被采纳。
可用的动作只有下面这些, 不要自创:
- 导航: {goto}
- 交互: {click}
- 等待: wait_for / wait_timeout
- 断言: {expect}
- 辅助: screenshot / scroll / set_viewport
"""


def build_system_prompt(test_type: str = "api") -> str:
    """
    组装 system prompt —— 完整的 DSL 规范 + 正反示例 + 「只输出 JSON」的约束。

    规范里的每一项都对应 `contracts/dsl.md` §5 的一条校验规则,
    规则违反的字段会被平台**丢弃**, 所以 prompt 要把要求说死。
    """
    ui_part = _ui_section() if test_type == "web" else ""
    web_part = """
Web UI 用例(当任务要求生成 Web UI 用例时): 把 `request` 换成 `ui` 块,
`ui` 块的格式见下方说明。
""" if test_type == "web" else ""

    return f"""你是接口测试平台 Pity 的「用例生成」助手。
你的任务是把用户给出的需求文本翻译成**结构化的测试用例 JSON**。

你只输出 JSON, 不要输出任何解释文字, 不要输出 markdown 代码块以外的内容。
输出的 JSON 必须是下面这个结构, 一个用例一个元素:

{{
  "cases": [
    {{
      "name": "用例名, 必填, 不超过 {MAX_CASE_NAME} 个字符",
      "priority": "{' / '.join(PRIORITIES)}, 默认 {DEFAULT_PRIORITY}",
      "category": "{_category_doc()}, 默认 {DEFAULT_CATEGORY}",
      "tags": ["标签1", "标签2"],
      "request": {{
        "method": "{_method_doc()}, 默认 {DEFAULT_REQUEST_METHOD}",
        "url": "请求地址, 必填, 不能为空",
        "body_type": {_body_type_doc()}, 默认 {DEFAULT_BODY_TYPE}",
        "headers": {{"Content-Type": "application/json"}},
        "body": {{"key": "value"}}
      }},
      "out_parameters": [
        {{"name": "变量名", "source": 1, "expression": "$.data.token", "match_index": "random"}}
      ],
      "asserts": [
        {{"name": "断言名", "assert_type": "equal", "expected": "0", "actually": "${{code}}"}}
      ],
      "pre_conditions": [
        {{"type": 1, "name": "步骤描述", "constructor_json": {{"sql": "delete from sms where mobile='138'"}}}}
      ],
      "post_conditions": []
    }}
  ]
}}

## 字段说明

- `out_parameters[].source`: {_source_doc()}
- `out_parameters[].match_index`: `random` / `all` / 数字, 仅 source 为 0 或 1 时有效
- `asserts[].assert_type` **只能取下面这 {len(ASSERT_TYPES)} 种之一**:
{_assert_type_doc()}
- `pre/post_conditions[].type`: {_constructor_type_doc()}
- `tags`: 多个标签用逗号连接写入用例, 总长不超过 {MAX_TAG} 个字符
{web_part}
## 硬性要求(违反的字段会被平台直接丢弃, 整批可能失败)

1. `name` 不能为空, 且不超过 {MAX_CASE_NAME} 个字符
2. `out_parameters[].name` 只能是字母/数字/下划线, 不能以数字开头, 不超过 {MAX_OUT_PARAMETER_NAME} 个字符
3. `assert_type` 必须是上面列出的那 {len(ASSERT_TYPES)} 种之一
4. `priority` 必须是 {' / '.join(PRIORITIES)} 之一
5. `body_type` 必须是 0~5 之一
6. `method` 必须是 {_method_doc()} 之一
7. `url` 不能为空
8. **断言 `actually` 里引用的每一个 `${{变量}}`, 都必须在同一条用例的 `out_parameters` 里声明过**
   —— 平台断言的取值**只能来自出参提取结果**, 没声明就取不到值,
   断言会**静默失败**(用例一片红却看不出原因)。这是最容易犯的错误, 输出前务必逐条核对。
9. `pre/post_conditions[].type` 必须是 0~4 之一
10. `headers` 与 `body` 必须是**合法的 JSON 对象**(不能是字符串、数组或 null)
{ui_part}
## 示例(正)

输入: 用户登录接口 POST /api/login, 参数 mobile 与 code; 验证码错误返回 code=10001, 成功返回 code=0 与 data.token

输出:
{{"cases": [
  {{"name": "登录-正常路径", "priority": "P0", "category": "正向流程", "tags": ["登录"],
   "request": {{"method": "POST", "url": "/api/login", "body_type": 1,
     "headers": {{"Content-Type": "application/json"}},
     "body": {{"mobile": "13800000000", "code": "123456"}}}},
   "out_parameters": [{{"name": "token", "source": 1, "expression": "$.data.token"}}],
   "asserts": [{{"name": "业务码", "assert_type": "equal", "expected": "0", "actually": "${{code}}"}}],
   "pre_conditions": [], "post_conditions": []}},
  {{"name": "登录-验证码错误", "priority": "P1", "category": "异常流程", "tags": ["登录"],
   "request": {{"method": "POST", "url": "/api/login", "body_type": 1,
     "headers": {{"Content-Type": "application/json"}},
     "body": {{"mobile": "13800000000", "code": "000000"}}}},
   "out_parameters": [{{"name": "code", "source": 1, "expression": "$.code"}}],
   "asserts": [{{"name": "业务码", "assert_type": "equal", "expected": "10001", "actually": "${{code}}"}}],
   "pre_conditions": [], "post_conditions": []}}
]}}

## 示例(反)—— 这三种写法都会被平台丢弃字段

{{"cases": [
  {{"name": "断言取值不可得",
   "request": {{"method": "POST", "url": "/api/login", "body_type": 1}},
   "asserts": [{{"name": "业务码", "assert_type": "equal", "expected": "0", "actually": "${{code}}"}}]}}
]}}
上面的 `actually` 引用了 `${{code}}`, 但 `out_parameters` 里没有声明 `code` —— 违反第 8 条, 该断言会被丢弃。

{{"cases": [
  {{"name": "断言类型非法",
   "request": {{"method": "POST", "url": "/api/login", "body_type": 1}},
   "asserts": [{{"name": "业务码", "assert_type": "equals", "expected": "0", "actually": "0"}}]}}
]}}
上面的 `assert_type` 是 `equals`, 不在白名单里 —— 违反第 3 条, 该断言会被丢弃。

{{"cases": [
  {{"name": "请求体不是对象",
   "request": {{"method": "POST", "url": "/api/login", "body_type": 1, "body": "mobile=138"}}}}
]}}
上面的 `body` 是字符串而不是 JSON 对象 —— 违反第 10 条, 该字段会被丢弃。

## 覆盖要求

- 正常路径、异常路径、边界值都要覆盖到, 分类用 `category` 标出来
- 每条用例**至少一个断言**, 断言要检查业务上真正重要的返回值
- 响应体里的字段要用 `out_parameters` 声明出来, 断言再用 `${{变量}}` 引用它
"""


SYSTEM_PROMPT = build_system_prompt("api")


def build_messages(prompt: str, source_text: str, test_type: str = "api") -> list:
    """
    组装 messages。

    **用户提供的文本(任务标题与需求正文)一律用 `<document>` 标签包裹** ——
    需求文档里出现"忽略前面的规则"是完全可能的, 标签 + system prompt 里的声明
    是防提示词注入的第一层(第二层是输出侧的严格 JSON 解析 + 字段白名单)。

    :param prompt:      任务标题 / 用户给的一句话说明
    :param source_text: 需求正文(文档解析结果或用户粘贴的文本)
    :param test_type:   api / web —— web 时提示词里带 Web UI 用例的规范
    """
    system = build_system_prompt(test_type) if test_type != "api" else SYSTEM_PROMPT
    user = (f"<document>\n[任务标题] {prompt or ''}\n\n[需求正文]\n{source_text or ''}\n</document>\n\n"
            f"请按系统消息里的规范输出 JSON:")
    return base.build_messages(system, user)


# ---------------------------------------------------------------------------
# 变量提取与规则 8
# ---------------------------------------------------------------------------


def extract_variables(text: str) -> List[str]:
    """
    提取 `${...}` 引用的**根名** —— `${data.id}` 取 `data`。

    :param text: 文本
    :return:     根名列表(去重, 保序)
    """
    if not text:
        return []
    names: List[str] = []
    for raw in VARIABLE_PATTERN.findall(text):
        root = raw.split(".")[0].split("[")[0].strip()
        if root and root not in names:
            names.append(root)
    return names


def collect_allowed_variables(case: dict, global_vars: Optional[set] = None,
                             request_vars: Optional[set] = None) -> set:
    """
    规则 8 的「可取值」集合 —— 断言 `actually` 里的变量只要在集合里就不算违规。

    组成:
    - 该用例的 `out_parameters` 里的变量名(**主要来源**)
    - 全局变量(`pity_gconfig`)里的键 —— 由调用方注入
    - 运行时请求参数(数据驱动测试数据)—— 由调用方注入

    > 全局变量与请求参数**不受规则 8 约束**(契约 dsl.md §5 的说明)。
    >
    > ⚠️ **请求体里的字段不算** —— 执行期 `case_params` 里并没有请求体的字段
    > (`Executor.run` 只合并全局变量、`request_param` 与出参提取结果),
    > 请求体是**从** `case_params` 渲染出来的, 不是它的来源。
    > 把请求体字段放进豁免集合, 等于放行一批**永远取不到值**的断言 ——
    > 那正是规则 8 要拦的静默失败。
    """
    allowed = set()
    for item in case.get("out_parameters") or []:
        if isinstance(item, dict) and item.get("name"):
            allowed.add(str(item["name"]))
    if global_vars:
        allowed.update(str(name) for name in global_vars)
    if request_vars:
        allowed.update(str(name) for name in request_vars)
    return allowed


def check_assert_variables(case: dict, global_vars: Optional[set] = None,
                           request_vars: Optional[set] = None) -> List[str]:
    """
    **规则 8** —— 断言 `actually` 引用的变量必须在 `out_parameters` 里存在。

    这条规则**最致命**: 漏配出参不会报错, 而是**静默失败** ——
    渲染得到空串, 断言比对失败, 用例一片红却看不出原因。

    :param case:         规范化后的用例
    :param global_vars:  全局变量名集合(豁免)
    :param request_vars: 运行时请求参数名集合(豁免)
    :return:             问题描述列表(空表示通过)
    """
    allowed = collect_allowed_variables(case, global_vars, request_vars)
    problems = []
    for index, item in enumerate(case.get("asserts") or [], start=1):
        actually = str(item.get("actually") or "")
        missing = [name for name in extract_variables(actually) if name not in allowed]
        if missing:
            problems.append(
                f"断言 {index}「{item.get('name') or actually}」的 actually 引用了未声明的变量"
                f"「{', '.join(missing)}」, 已在 out_parameters 中声明出参后才能取到值")
    return problems


# ---------------------------------------------------------------------------
# 14 条校验规则
# ---------------------------------------------------------------------------


def _validate_out_parameters(raw_list, warnings: List[str]) -> List[dict]:
    """规则 2 —— 出参名 ≤ 24 且匹配 `^[A-Za-z_][A-Za-z0-9_]*$`"""
    result = []
    if not isinstance(raw_list, list):
        return result
    for item in raw_list:
        if not isinstance(item, dict):
            warnings.append("出参格式非法(不是对象), 已丢弃")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            warnings.append("出参名为空, 已丢弃")
            continue
        if len(name) > MAX_OUT_PARAMETER_NAME:
            warnings.append(f"出参名「{name}」超过 {MAX_OUT_PARAMETER_NAME} 个字符, 已丢弃")
            continue
        if not re.match(VARIABLE_NAME_PATTERN, name):
            warnings.append(f"出参名「{name}」非法(只能包含字母/数字/下划线且不能以数字开头), 已丢弃")
            continue
        source = item.get("source")
        try:
            source = int(source)
        except (TypeError, ValueError):
            source = 0
        if source not in OUT_PARAMETER_SOURCES:
            warnings.append(f"出参「{name}」的 source「{source}」不合法, 已置为 0")
            source = 0
        expression = item.get("expression")
        if expression is not None:
            expression = str(expression)
            if len(expression) > 128:
                warnings.append(f"出参「{name}」的 expression 超过 128 个字符, 已丢弃该出参")
                continue
        match_index = item.get("match_index")
        result.append({
            "name": name,
            "source": source,
            "expression": expression,
            "match_index": str(match_index) if match_index is not None else None,
        })
    return result


def _validate_asserts(raw_list, allowed_vars: set, warnings: List[str]) -> List[dict]:
    """
    规则 3 + 规则 8 —— 断言类型白名单 + 取值只能来自出参

    **规则 8 的处置与契约表格不同**(实现决策, 记在 tasks.md 的「实现记录」里):
    表格说"丢弃该断言并告警", 但 spec FR-012 要求"**采纳前拦下**断言取值无法获得的用例"。
    两者只有在**保留**该断言时才都成立 —— 丢掉了, 采纳时就看不出这条草稿还有问题,
    拦下也就无从谈起。

    所以规则 8 的处置是: **保留断言 + 告警 + 采纳时拦截**。
    用户在草稿编辑器里补一条 out_parameters(或删掉该断言)后保存, 校验通过, 即可采纳。
    """
    result = []
    if not isinstance(raw_list, list):
        return result
    for item in raw_list:
        if not isinstance(item, dict):
            warnings.append("断言格式非法(不是对象), 已丢弃")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            warnings.append("断言名为空, 已丢弃")
            continue
        if len(name) > MAX_ASSERT_NAME:
            warnings.append(f"断言名「{name}」超过 {MAX_ASSERT_NAME} 个字符, 已截断")
            name = name[:MAX_ASSERT_NAME]
        assert_type = str(item.get("assert_type") or "").strip()
        if assert_type not in ASSERT_TYPES:
            # 规则 3 —— 类型不在白名单, 这条断言没法执行, 丢弃
            warnings.append(f"断言「{name}」的类型「{assert_type}」不在白名单内, 已丢弃该断言")
            continue
        expected = item.get("expected")
        actually = item.get("actually")
        if expected is None or actually is None:
            warnings.append(f"断言「{name}」缺少 expected 或 actually, 已丢弃该断言")
            continue
        # 规则 8 —— 取值只能来自出参。**保留该断言**, 由采纳时的拦截兜住
        missing = [var for var in extract_variables(str(actually)) if var not in allowed_vars]
        if missing:
            warnings.append(f"断言「{name}」的 actually 引用了未声明的变量「{', '.join(missing)}」, "
                           f"该断言暂时保留, 采纳前必须补 out_parameters 或修掉它")
        result.append({
            "name": name,
            "assert_type": assert_type,
            "expected": str(expected),
            "actually": str(actually),
        })
    return result


def _validate_conditions(raw_list, warnings: List[str]) -> List[dict]:
    """规则 9 —— 构造器 type ∈ {0,1,2,3,4}"""
    result = []
    if not isinstance(raw_list, list):
        return result
    for item in raw_list:
        if not isinstance(item, dict):
            warnings.append("步骤格式非法(不是对象), 已丢弃")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            warnings.append("步骤描述为空, 已丢弃")
            continue
        if len(name) > MAX_CONSTRUCTOR_NAME:
            warnings.append(f"步骤描述「{name}」超过 {MAX_CONSTRUCTOR_NAME} 个字符, 已截断")
            name = name[:MAX_CONSTRUCTOR_NAME]
        try:
            ctype = int(item.get("type"))
        except (TypeError, ValueError):
            ctype = -1
        if ctype not in CONSTRUCTOR_TYPES:
            warnings.append(f"步骤「{name}」的 type「{item.get('type')}」不合法, 已丢弃该步骤")
            continue
        constructor_json = item.get("constructor_json")
        if not isinstance(constructor_json, dict):
            warnings.append(f"步骤「{name}」的 constructor_json 必须是对象, 已丢弃该步骤")
            continue
        value = item.get("value")
        if value is not None:
            value = str(value)
            if len(value) > 16:
                warnings.append(f"步骤「{name}」的返回值变量名超过 16 个字符, 已截断")
                value = value[:16]
        result.append({
            "type": ctype,
            "name": name,
            "constructor_json": constructor_json,
            "value": value or "",
            "public": bool(item.get("public", False)),
            "index": int(item.get("index") or 0),
        })
    return result


def _validate_request(raw, warnings: List[str]) -> Optional[dict]:
    """规则 5 / 6 / 7 / 10 —— 请求体类型 / 请求方法 / url 非空 / headers 与 body 是合法 JSON 对象"""
    if not isinstance(raw, dict):
        warnings.append("request 不是对象, 已丢弃")
        return None
    request = {}
    method = str(raw.get("method") or "").strip().upper()
    if method not in REQUEST_METHODS:
        warnings.append(f"请求方法「{raw.get('method')}」不合法, 已置为 {DEFAULT_REQUEST_METHOD}")
        method = DEFAULT_REQUEST_METHOD
    request["method"] = method

    url = str(raw.get("url") or "").strip()
    request["url"] = url

    try:
        body_type = int(raw.get("body_type"))
    except (TypeError, ValueError):
        body_type = DEFAULT_BODY_TYPE
    if body_type not in BODY_TYPES:
        warnings.append(f"body_type「{raw.get('body_type')}」不合法, 已置为 {DEFAULT_BODY_TYPE}")
        body_type = DEFAULT_BODY_TYPE
    request["body_type"] = body_type

    headers = raw.get("headers")
    if headers is None:
        request["headers"] = None
    elif isinstance(headers, dict):
        request["headers"] = headers
    else:
        warnings.append("headers 必须是合法的 JSON 对象, 已丢弃该字段")
        request["headers"] = None

    body = raw.get("body")
    if body is None:
        request["body"] = None
    elif isinstance(body, dict):
        request["body"] = body
    else:
        warnings.append("body 必须是合法的 JSON 对象, 已丢弃该字段")
        request["body"] = None
    return request


def _default_resolver():
    """默认的元素引用解析器 —— 元素库里的真实元素(注入是为了让回归脚本不依赖数据库)"""
    from app.crud.ui.UIElementDao import UIElementDao
    return UIElementDao.resolve_reference


async def _permissive_resolver(project_id: int, reference: str):
    """
    "总是解析成功"的假解析器。

    给 `validate_steps` 用 —— 元素引用的有效性**单独**查(见 `_validate_ui_steps`),
    不能让 `validate_steps` 把引用了无效元素的步骤悄悄丢掉:
    丢掉之后就看不出这条草稿还有问题, FR-039 的"处理后才能采纳"也就无从谈起。
    """
    return SimpleNamespace(id=0, strategy="", locator="", name_attr=None), ""


async def _validate_ui_steps(project_id: Optional[int], raw_steps, resolver: Optional[Callable],
                             warnings: List[str]) -> List[dict]:
    """
    规则 11 / 12 / 13 —— **复用 `ui_executor.validate_steps`**。

    002 的 `validate_steps` 已经把动作白名单、必填字段、未知字段、
    元素引用有效性全都管了, 且元素引用语义**以 002 的契约为准**。
    001 另写一套只会带来漂移 —— 所以这里直接调它, 只把它的告警翻译成 001 的口径。

    **规则 13 的处置**(与契约表格不同, 见实现记录): 元素引用无效的步骤
    **保留**并告警, 由采纳时的拦截兜住(spec FR-039「处理后才能采纳」)。
    丢掉了就看不出这条草稿还有问题, 拦下也无从谈起。
    """
    if not isinstance(raw_steps, list) or not raw_steps:
        return []
    try:
        steps, step_warnings = await validate_steps(project_id, raw_steps,
                                                     resolver=_permissive_resolver)
    except Exception as e:  # noqa: BLE001 —— 步骤不合法不该让整批草稿失败
        warnings.append(f"Web UI 步骤校验失败: {e}")
        return []
    for message in step_warnings:
        warnings.append(message)

    # 规则 13 —— 元素引用必须存在且启用; 无效的**保留**该步骤并告警
    real_resolver = resolver if resolver is not None else _default_resolver()
    for index, step in enumerate(steps, start=1):
        reference = step.get("element")
        if not reference:
            continue
        try:
            element, reason = await real_resolver(project_id, reference)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"步骤 {index} 的元素引用「{reference}」解析失败: {e}")
            continue
        if element is None:
            warnings.append(f"步骤 {index} {reason or f'引用的元素「{reference}」不存在或已停用'}, "
                           f"该步骤暂时保留, 采纳前必须处理")

    # 校验期注入的内部字段(_element_id / _strategy / _locator / _name_attr)是
    # 执行期的中间产物, **不能落库** —— 存进库的必须是纯 DSL
    return strip_internal(steps)


async def _validate_ui_block(raw, project_id: Optional[int], resolver: Optional[Callable],
                             warnings: List[str]) -> Optional[dict]:
    """规则 14 —— base_url 非空 且 steps 非空; 规则 11~13 见 `_validate_ui_steps`"""
    if not isinstance(raw, dict):
        warnings.append("ui 不是对象, 已丢弃该 ui 块")
        return None
    base_url = str(raw.get("base_url") or "").strip()
    steps = raw.get("steps")
    if not base_url:
        warnings.append("ui.base_url 为空, 已丢弃该 ui 块")
        return None
    if not isinstance(steps, list) or not steps:
        warnings.append("ui.steps 为空, 已丢弃该 ui 块")
        return None
    valid_steps = await _validate_ui_steps(project_id, steps, resolver, warnings)
    viewport = str(raw.get("viewport") or "1280x720")
    try:
        timeout = int(raw.get("timeout") or 30)
    except (TypeError, ValueError):
        timeout = 30
    if timeout <= 0:
        timeout = 30
    return {
        "base_url": base_url,
        "viewport": viewport,
        "timeout": timeout,
        "steps": valid_steps,
    }


async def _validate_one_case(raw: dict, index: int, project_id: Optional[int],
                              resolver: Optional[Callable], global_vars: Optional[set],
                              request_vars: Optional[set],
                              warnings: List[str]) -> Optional[dict]:
    """
    校验单条用例 —— 规则 1~14。

    :return: 规范化后的用例; **None 表示这条用例的全部内容都非法, 整条丢弃**
    """
    label = f"用例 {index}"
    name = str(raw.get("name") or "").strip()
    if not name:
        warnings.append(f"{label} 的 name 为空, 已丢弃该条用例")
        return None
    if len(name) > MAX_CASE_NAME:
        warnings.append(f"{label}「{name}」的名字超过 {MAX_CASE_NAME} 个字符, 已截断")
        name = name[:MAX_CASE_NAME]
    label = f"用例「{name}」"

    # 规则 4 —— 优先级
    priority = str(raw.get("priority") or DEFAULT_PRIORITY).strip().upper()
    if priority not in PRIORITIES:
        warnings.append(f"{label} 的优先级「{raw.get('priority')}」不合法, 已置为 {DEFAULT_PRIORITY}")
        priority = DEFAULT_PRIORITY

    # 类别
    category = str(raw.get("category") or DEFAULT_CATEGORY).strip()
    if category not in CASE_CATEGORIES:
        warnings.append(f"{label} 的类别「{raw.get('category')}」不合法, 已置为 {DEFAULT_CATEGORY}")
        category = DEFAULT_CATEGORY

    # 标签
    tags = []
    raw_tags = raw.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags = [part.strip() for part in raw_tags.split(",") if part.strip()]

    normalized = {
        "name": name,
        "priority": priority,
        "category": category,
        "tags": tags,
        "request": None,
        "ui": None,
        "out_parameters": [],
        "asserts": [],
        "pre_conditions": [],
        "post_conditions": [],
    }

    # API 用例的 request
    request = _validate_request(raw.get("request"), warnings)
    if request is not None:
        if not request.get("url"):
            # 规则 7 —— url 不可空(pity_testcase.url nullable=False)
            warnings.append(f"{label} 的 request.url 为空, 已丢弃该条用例")
            return None
        normalized["request"] = request

    # Web UI 用例的 ui 块
    if raw.get("ui") is not None:
        ui = await _validate_ui_block(raw.get("ui"), project_id, resolver, warnings)
        if ui is not None:
            normalized["ui"] = ui

    if normalized["request"] is None and normalized["ui"] is None:
        # 既没有 request 也没有 ui —— 这条用例没有任何可执行内容
        warnings.append(f"{label} 既没有 request 也没有 ui, 已丢弃该条用例")
        return None

    # 规则 2 —— 出参
    normalized["out_parameters"] = _validate_out_parameters(raw.get("out_parameters"), warnings)

    # 规则 3 + 规则 8 —— 断言
    allowed_vars = collect_allowed_variables(normalized, global_vars, request_vars)
    normalized["asserts"] = _validate_asserts(raw.get("asserts"), allowed_vars, warnings)

    # 规则 9 —— 前后置步骤
    normalized["pre_conditions"] = _validate_conditions(raw.get("pre_conditions"), warnings)
    normalized["post_conditions"] = _validate_conditions(raw.get("post_conditions"), warnings)

    return normalized


async def parse_cases(text: str, project_id: int = None, resolver: Optional[Callable] = None,
                      global_vars: Optional[set] = None,
                      request_vars: Optional[set] = None) -> Tuple[List[dict], List[str]]:
    """
    解析模型输出并逐条过 14 条校验规则。

    :param text:         模型返回的文本
    :param project_id:   所属项目(规则 13 的元素解析要用)
    :param resolver:     元素引用解析器 async (project_id, reference) -> (element, reason);
                         默认走 `UIElementDao.resolve_reference`。做成可注入是为了让回归脚本不依赖数据库。
    :param global_vars:  全局变量名集合(规则 8 的豁免项); None 表示不豁免
    :param request_vars: 运行时请求参数名集合(规则 8 的豁免项)
    :return: (规范化后的用例列表, 告警列表)
    """
    from app.core.ai_service import AIJsonError, extract_json

    try:
        payload = extract_json(text)
    except AIJsonError as e:
        raise e
    if not isinstance(payload, dict):
        raise AIJsonError("模型返回的 JSON 不是对象")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise AIJsonError("模型没有给出任何用例")
    if len(raw_cases) > MAX_CASES:
        raw_cases = raw_cases[:MAX_CASES]

    cases: List[dict] = []
    warnings: List[str] = []
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, dict):
            warnings.append(f"用例 {index}: 不是合法的对象, 已丢弃")
            continue
        # 每条用例的告警单独收集 —— 前端要按草稿逐条展示, 光有一个平铺的列表不够用
        case_warnings: List[str] = []
        normalized = await _validate_one_case(raw, index, project_id, resolver, global_vars,
                                              request_vars, case_warnings)
        warnings.extend(f"用例 {index}: {message}" for message in case_warnings)
        if normalized is not None:
            cases.append(normalized)
    if not cases:
        raise AIJsonError("模型给出的用例全部不合法")
    return cases, warnings


# ---------------------------------------------------------------------------
# DSL → 既有四表的映射
# ---------------------------------------------------------------------------


def build_case_records(case: dict, directory_id: int, test_type: str = "api") -> dict:
    """
    把一条规范化后的 DSL 用例映射成**既有四张表**的行数据。

    逐字对齐 `data-model.md` §3.2 —— 不做二次转换。

    :param case:        规范化后的用例
    :param directory_id: 采纳目标目录
    :param test_type:   api / web
    :return: {"case": {...}, "out_parameters": [...], "asserts": [...],
              "pre_conditions": [...], "post_conditions": [...], "ui": {...} | None}
    """
    from app.enums.RequestTypeEnum import RequestType

    is_ui = test_type == "web" or case.get("ui") is not None
    request = case.get("request") or {}
    ui = case.get("ui") or {}
    base_url = str(ui.get("base_url") or request.get("url") or "")

    tags = case.get("tags") or []
    tag = ",".join(tags)[:MAX_TAG] if tags else None

    case_row = {
        "name": str(case.get("name") or "")[:MAX_CASE_NAME],
        # 1 = http, 4 = web_ui(RequestType.web_ui)
        "request_type": int(RequestType.web_ui) if is_ui else int(RequestType.http),
        # UI 用例的 base_url 存 url —— 该列 nullable=False, 正好复用
        "url": base_url,
        "request_method": request.get("method") if not is_ui else None,
        "request_headers": _dump_json(request.get("headers")),
        "body": _dump_json(request.get("body")),
        "body_type": int(request.get("body_type") or DEFAULT_BODY_TYPE),
        "directory_id": directory_id,
        "tag": tag,
        # 恒为 1(调试中) —— AI 生成的用例大概率还要人工微调,
        # 默认"正常运作"会把未验证的用例放进正常回归集, 污染基线(research §3.10)
        "status": 1,
        "priority": str(case.get("priority") or DEFAULT_PRIORITY),
        # 0 = 普通用例
        "case_type": 0,
    }

    out_parameters = [{
        "name": item["name"],
        "source": item["source"],
        "expression": item.get("expression"),
        "match_index": item.get("match_index"),
    } for item in case.get("out_parameters") or []]

    asserts = [{
        "name": item["name"],
        "assert_type": item["assert_type"],
        "expected": item["expected"],
        "actually": item["actually"],
    } for item in case.get("asserts") or []]

    pre_conditions = [dict(item) for item in case.get("pre_conditions") or []]
    post_conditions = [dict(item) for item in case.get("post_conditions") or []]

    ui_row = None
    if is_ui and ui:
        ui_row = {
            "base_url": str(ui.get("base_url") or ""),
            "viewport": str(ui.get("viewport") or "1280x720"),
            "timeout": int(ui.get("timeout") or 30),
            "steps": ui.get("steps") or [],
        }
    return {
        "case": case_row,
        "out_parameters": out_parameters,
        "asserts": asserts,
        "pre_conditions": pre_conditions,
        "post_conditions": post_conditions,
        "ui": ui_row,
    }


def _dump_json(value) -> Optional[str]:
    """把 dict/None 落成 TEXT 列的内容 —— 运行时会被 json.loads, 必须是合法 JSON"""
    import json
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 采纳前的两道拦截(T027)
# ---------------------------------------------------------------------------


async def check_adopt_blockers(case: dict, project_id: Optional[int] = None,
                               resolver: Optional[Callable] = None,
                               global_vars: Optional[set] = None,
                               request_vars: Optional[set] = None) -> List[str]:
    """
    **采纳前的两道拦截** —— 返回问题列表, 非空表示**拒绝采纳**。

    1. 断言 `actually` 引用了未在 `out_parameters` 声明的变量(规则 8)
       —— 取不到值就是**静默失败**, 用例必然一片红
    2. Web UI 用例的步骤仍引用了元素库中不存在或已停用的元素(规则 13)
       —— 执行时必然在"定位元素"那一步失败

    两条都在**采纳**时拦, 不让脏用例进回归基线。

    :param case:        规范化后的用例
    :param project_id:  所属项目
    :param resolver:    元素引用解析器
    :param global_vars: 全局变量名集合
    :return:            问题描述列表
    """
    problems = check_assert_variables(case, global_vars, request_vars)

    ui = case.get("ui") or {}
    steps = ui.get("steps") or []
    if steps:
        real_resolver = resolver if resolver is not None else _default_resolver()
        for index, step in enumerate(steps, start=1):
            reference = step.get("element")
            if not reference:
                continue
            try:
                element, reason = await real_resolver(project_id, reference)
            except Exception as e:  # noqa: BLE001
                problems.append(f"步骤 {index} 的元素引用「{reference}」解析失败: {e}")
                continue
            if element is None:
                problems.append(f"步骤 {index} {reason or f'引用的元素「{reference}」不存在或已停用'}, "
                                f"该草稿不能被采纳")
    return problems

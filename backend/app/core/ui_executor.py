"""
UI 执行引擎

**本文件是 UI 步骤 DSL 的后端权威出处** —— `ACTIONS`(动作白名单)与 `STRATEGIES`(8 种定位策略)
定义在这里, 前端镜像在 `frontend/src/consts/uiTest.ts`, **改一处必须同时改另一处**
(见 `backend/CLAUDE.md` 与 `specs/002-ui-automation/contracts/steps.md` §8)。

三个必须守住的约束:

1. **动作白名单是封闭集合** —— 不在 `ACTIONS` 里的动作**在加载步骤时就拒绝**, 不是执行时才拦。
   仓库已有两个 `exec()` 执行面(`app/routers/online/script.py`、`app/core/constructor/python_constructor.py`),
   UI 用例不能再开第三个, 所以 `evaluate` / `exec` / `run` / `script` 一律不接受。
2. **确定性等待** —— 条件等待优先, 引擎**不得插入任何隐式 sleep**, 退避必须固定不随机,
   定位到多个元素必须**显式失败**而不是取第一个。
3. **不可重放声明** —— 步骤定义完全确定(同一份 steps 永远产生同一串浏览器操作序列),
   但**执行结果不可重放**: 页面内容与断言成败取决于被测系统当时的状态, 不在平台可控范围。
   平台自身 MUST NOT 引入任何随机源。

另有两处工程约束:
- Browser **进程内单例复用**, 每条用例独立 Context(cookie/storage 隔离)
- `asyncio.Semaphore` 限流(默认 2 条用例并发), 浏览器异常不得带崩 gunicorn worker
"""
import asyncio
import json
import time
from typing import Dict, List, Optional, Tuple

from app.crud.ui.UIElementDao import UIElementDao
from app.utils.ui_security import UINavigationBlocked, check_url, resolve_step_url

# ============================================================================
# 权威常量 —— 前端镜像在 frontend/src/consts/uiTest.ts
# ============================================================================

# 动作白名单(封闭集合)
#   fields   : 该动作允许的字段(超出的一律丢弃并告警)
#   required : 必填字段
#   target   : 是否需要目标(元素引用或内联定位)
#   value    : value 字段的语义 —— locator 表示可作内联定位值, expected 表示期望值,
#              option 表示选项值, target_selector 表示拖拽目标选择器, filename 表示截图文件名,
#              none 表示不用 value
ACTIONS = {
    # ---- 导航 ----
    "goto": {"fields": {"url"}, "required": ["url"], "target": False, "value": "none"},
    "back": {"fields": set(), "required": [], "target": False, "value": "none"},
    "reload": {"fields": set(), "required": [], "target": False, "value": "none"},
    # ---- 交互 ----
    "click": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "dblclick": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "fill": {"fields": {"text"}, "required": ["text"], "target": True, "value": "locator"},
    "clear": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "press": {"fields": {"text"}, "required": ["text"], "target": True, "value": "locator"},
    "select": {"fields": set(), "required": ["value"], "target": True, "value": "option"},
    "check": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "uncheck": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "hover": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "upload": {"fields": {"files"}, "required": ["files"], "target": True, "value": "locator"},
    "drag": {"fields": set(), "required": ["value"], "target": True, "value": "target_selector"},
    # ---- 等待 ----
    "wait_for": {"fields": {"state"}, "required": ["state"], "target": True, "value": "locator"},
    # timeout 在这里是**毫秒**(固定等待, 必须显式配置); 其他动作里 timeout 是秒
    "wait_timeout": {"fields": set(), "required": ["timeout"], "target": False, "value": "none"},
    # ---- 断言 ----
    "expect_text": {"fields": set(), "required": ["value"], "target": True, "value": "expected"},
    "expect_visible": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "expect_hidden": {"fields": set(), "required": [], "target": True, "value": "locator"},
    "expect_url": {"fields": set(), "required": ["value"], "target": False, "value": "expected"},
    "expect_count": {"fields": set(), "required": ["value"], "target": True, "value": "expected"},
    "expect_value": {"fields": set(), "required": ["value"], "target": True, "value": "expected"},
    "expect_enabled": {"fields": set(), "required": [], "target": True, "value": "locator"},
    # ---- 辅助 ----
    "screenshot": {"fields": set(), "required": [], "target": False, "value": "filename"},
    "scroll": {"fields": set(), "required": [], "target": False, "value": "locator"},
    "set_viewport": {"fields": set(), "required": ["value"], "target": False, "value": "expected"},
}

# 8 种定位策略 —— semantic 表示语义定位(比 CSS/XPath 更抗改版, 编辑器优先推荐)
STRATEGIES = {
    "css": {"label": "CSS 选择器", "semantic": False},
    "xpath": {"label": "XPath", "semantic": False},
    "id": {"label": "ID", "semantic": False},
    "text": {"label": "文本", "semantic": True},
    "role": {"label": "Role", "semantic": True},
    "placeholder": {"label": "占位符", "semantic": True},
    "label": {"label": "Label", "semantic": True},
    "testid": {"label": "testid", "semantic": True},
}

# UI 断言 → 既有 assert_type 语义(与接口用例同一套, 不新建断言表)
ASSERT_TYPE_MAPPING = {
    "expect_text": "equal",
    "expect_visible": "equal",
    "expect_hidden": "equal",
    "expect_url": "equal",
    "expect_count": "length_eq",
    "expect_value": "equal",
    "expect_enabled": "equal",
}

# 所有步骤共有的字段
COMMON_FIELDS = {"action", "timeout", "element", "by", "value", "name"}

# 失败原因分类(contracts/api.md §3.2)
REASON_ELEMENT_NOT_FOUND = "element_not_found"
REASON_ELEMENT_AMBIGUOUS = "element_ambiguous"
REASON_TIMEOUT = "timeout"
REASON_ASSERTION_FAILED = "assertion_failed"
REASON_NAVIGATION_BLOCKED = "navigation_blocked"
REASON_BROWSER_ERROR = "browser_error"

# 固定的重试次数与固定退避 —— **写死在实现里, 不在运行时决定, 不带随机抖动**
RETRY_TIMES = 2
RETRY_DELAY = 1.0

# 默认并发上限(每进程)
DEFAULT_MAX_CONCURRENCY = 2

WAIT_STATES = ("visible", "hidden", "attached", "detached")


class UIExecutionError(Exception):
    """UI 执行过程中的错误, 携带机器可读的失败原因分类"""

    def __init__(self, message: str, reason: str = REASON_BROWSER_ERROR):
        super().__init__(message)
        self.message = message
        self.reason = reason


# ============================================================================
# 步骤校验 —— 加载步骤时就拒绝不合规的步骤
# ============================================================================


async def validate_steps(project_id: int, steps) -> Tuple[List[dict], List[str]]:
    """
    校验步骤 DSL。

    - 动作不在白名单 → **丢弃该步骤并告警**(加载阶段就拒绝, 不是执行时才拦)
    - 缺必填字段 → 丢弃并告警
    - 未知字段 → 丢弃该字段并告警
    - 元素引用无效(不存在 / 已停用) → 丢弃该步骤并告警

    :param project_id: 所属项目
    :param steps: 原始步骤数组
    :return: (合法步骤, 告警列表)
    """
    warnings: List[str] = []
    if steps is None:
        return [], warnings
    if not isinstance(steps, list):
        raise Exception("步骤必须是数组")
    valid: List[dict] = []
    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            warnings.append(f"步骤 {index} 不是合法的对象, 已跳过")
            continue
        action = raw.get("action")
        if not action:
            warnings.append(f"步骤 {index} 缺少 action, 已跳过")
            continue
        if action not in ACTIONS:
            # 封闭动作白名单 —— evaluate / exec / run / script 都在这里被拒
            warnings.append(f"步骤 {index} 的动作「{action}」不在白名单内, 已跳过")
            continue
        spec = ACTIONS[action]
        allowed = COMMON_FIELDS | spec["fields"]
        step = {k: v for k, v in raw.items() if k in allowed}
        dropped = [k for k in raw.keys() if k not in allowed]
        if dropped:
            warnings.append(f"步骤 {index} 存在未知字段「{', '.join(sorted(dropped))}」, 已丢弃")
        missing = [f for f in spec["required"] if step.get(f) in (None, "")]
        if missing:
            warnings.append(f"步骤 {index} 缺少必填参数「{', '.join(missing)}」, 已跳过")
            continue
        if spec["target"]:
            if step.get("element"):
                element, err = await UIElementDao.resolve_reference(project_id, step["element"])
                if element is None:
                    warnings.append(f"步骤 {index} {err}, 已丢弃该步骤")
                    continue
                step["_element_id"] = element.id
                step["_strategy"] = element.strategy
                step["_locator"] = element.locator
                step["_name_attr"] = element.name_attr
            else:
                # 内联定位: 只有 value 语义是 locator 的动作才允许
                if spec["value"] != "locator":
                    warnings.append(f"步骤 {index} 必须通过 element 引用元素库中的元素, 已跳过")
                    continue
                if not step.get("by") or not step.get("value"):
                    warnings.append(f"步骤 {index} 未提供元素引用, 也没有完整的内联定位(by + value), 已跳过")
                    continue
                if step["by"] not in STRATEGIES:
                    warnings.append(f"步骤 {index} 的定位策略「{step['by']}」不合法, 已跳过")
                    continue
                step["_strategy"] = step["by"]
                step["_locator"] = step["value"]
                step["_name_attr"] = step.get("name")
        if action == "wait_for" and step.get("state") not in WAIT_STATES:
            warnings.append(f"步骤 {index} 的等待状态「{step.get('state')}」不合法, 已跳过")
            continue
        step["action"] = action
        valid.append(step)
    return valid, warnings


# ============================================================================
# 浏览器管理
# ============================================================================


class BrowserManager(object):
    """
    浏览器进程内单例复用。

    - Browser 只启动一次, 整个 worker 复用
    - 每条用例开独立 Context, cookie / storage 互相隔离
    - `asyncio.Semaphore` 限制同时运行的用例数, 避免把机器打满
    - 浏览器异常 MUST NOT 带崩 gunicorn worker(所有调用点都有兜底)
    """

    _playwright = None
    _browser = None
    _semaphore = None
    _loop = None
    _lock = None
    _max_concurrency = DEFAULT_MAX_CONCURRENCY

    @classmethod
    async def get_browser(cls, headless: bool = True, browser_type: str = "chromium"):
        """取浏览器实例 —— 第一次调用时启动, 之后复用"""
        if cls._browser is not None:
            return cls._browser
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._browser is not None:
                return cls._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise UIExecutionError(
                    "未安装 playwright, 请执行 pip install playwright && playwright install chromium",
                    REASON_BROWSER_ERROR)
            try:
                cls._playwright = await async_playwright().start()
                launcher = getattr(cls._playwright, browser_type, None)
                if launcher is None:
                    raise UIExecutionError(f"不支持的浏览器类型: {browser_type}", REASON_BROWSER_ERROR)
                cls._browser = await launcher.launch(headless=headless)
            except UIExecutionError:
                await cls._cleanup()
                raise
            except Exception as e:
                await cls._cleanup()
                raise UIExecutionError(f"启动浏览器失败: {e}", REASON_BROWSER_ERROR)
            return cls._browser

    @classmethod
    def get_semaphore(cls):
        """并发限流 —— 绑定到当前事件循环, 换 loop 时重建"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if cls._semaphore is None or cls._loop is not loop:
            cls._semaphore = asyncio.Semaphore(cls._max_concurrency)
            cls._loop = loop
        return cls._semaphore

    @classmethod
    async def _cleanup(cls):
        if cls._browser is not None:
            try:
                await cls._browser.close()
            except Exception:
                pass
            cls._browser = None
        if cls._playwright is not None:
            try:
                await cls._playwright.stop()
            except Exception:
                pass
            cls._playwright = None

    @classmethod
    async def close(cls):
        """进程退出时关闭浏览器"""
        await cls._cleanup()


# ============================================================================
# 执行器
# ============================================================================


class UIExecutor(object):
    """
    执行一条 UI 用例。

    :param ui_case: PityUICase
    :param project_id: 所属项目(决定元素库与白名单)
    :param allowed_domains: 项目级允许域名(SSRF 白名单)
    :param params: 变量上下文(全局变量 + 请求参数), 供 Render 渲染
    :param logger: CaseLog, 逐步骤写日志
    """

    def __init__(self, ui_case, project_id: int, allowed_domains: List[str], params: dict = None,
                 logger=None):
        self.ui_case = ui_case
        self.project_id = project_id
        self.allowed_domains = list(allowed_domains or [])
        self.params = params or {}
        self.logger = logger
        self.steps: List[dict] = []
        self.assertions: List[dict] = []
        self.current_url = None
        self.screenshot = None
        self.screenshot_name = None
        # 主机名 → 是否放行, 避免每个子资源请求都做一次 DNS 解析
        self._host_cache = dict()

    # ---------- 日志 ----------

    def append(self, content: str):
        if self.logger is not None:
            self.logger.append(content)

    # ---------- 变量渲染 ----------

    def render(self, value):
        """用平台既有的 Render 渲染字符串字段(FR-013)"""
        if not isinstance(value, str) or "${" not in value:
            return value
        from app.core.render import Render
        return Render.render(self.params, value)

    # ---------- 主流程 ----------

    async def run(self) -> dict:
        """
        执行用例。

        :return: dict(status, steps, assertions, asserts, error, error_reason, screenshot, ...)
        """
        from app.crud.ui.UICaseDao import UICaseDao

        steps = await UICaseDao.load_steps(self.ui_case.case_id)
        if not steps:
            return self._result(status=2, error="用例没有可执行的步骤", error_reason=REASON_BROWSER_ERROR)
        base_url = self.render(self.ui_case.base_url or "")
        # base_url 必须先过 SSRF 校验 —— 空白名单 = 不可执行
        try:
            base_url = check_url(base_url, self.allowed_domains)
        except UINavigationBlocked as e:
            return self._result(status=2, error=e.message, error_reason=REASON_NAVIGATION_BLOCKED)
        viewport = self._parse_viewport(self.ui_case.viewport or "1280x720")
        semaphore = BrowserManager.get_semaphore()
        async with semaphore:
            try:
                browser = await BrowserManager.get_browser(
                    headless=True, browser_type=self.ui_case.browser or "chromium")
            except UIExecutionError as e:
                return self._result(status=2, error=e.message, error_reason=e.reason)
            try:
                context = await browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
            except Exception as e:
                return self._result(status=2, error=f"创建浏览器上下文失败: {e}", error_reason=REASON_BROWSER_ERROR)
            try:
                page = await context.new_page()
                # 页面内的子资源请求同样受 SSRF 约束(检查点 5)
                await page.route("**/*", self._make_route_guard())
                try:
                    await self._run_steps(page, steps, base_url)
                except UINavigationBlocked as e:
                    await self._capture(page)
                    return self._result(status=2, error=e.message, error_reason=REASON_NAVIGATION_BLOCKED)
                except Exception as e:
                    await self._capture(page)
                    return self._result(status=2, error=str(e), error_reason=self._reason_of(e))
                failed = self._failed_step()
                if failed is not None:
                    await self._capture(page)
                    return self._result(status=1, error=failed.get("error"),
                                        error_reason=failed.get("reason") or REASON_BROWSER_ERROR)
                return self._result()
            finally:
                try:
                    await context.close()
                except Exception:
                    pass

    def _failed_step(self) -> Optional[dict]:
        for step in self.steps:
            if step.get("status") == "failed":
                return step
        return None

    @staticmethod
    def _reason_of(exc: Exception) -> str:
        """从异常里取失败原因分类 —— 定位器错误自带 reason"""
        reason = getattr(exc, "reason", None)
        if reason:
            return reason
        return REASON_BROWSER_ERROR

    async def _capture(self, page):
        """失败时截图, 保留现场"""
        try:
            if not self.ui_case.screenshot:
                return
            self.screenshot = await page.screenshot(type="png")
            self.screenshot_name = f"ui_{self.ui_case.case_id}_fail.png"
        except Exception:
            self.screenshot = None

    async def _run_steps(self, page, steps: List[dict], base_url: str):
        """逐步骤执行 —— 单步失败即停止后续步骤并保留现场"""
        for index, step in enumerate(steps, start=1):
            record = {
                "index": index,
                "action": step.get("action"),
                "target": self._target_text(step),
                "strategy": step.get("_strategy"),
                "locator": step.get("_locator"),
                "name_attr": step.get("_name_attr"),
                "status": "ok",
                "cost": 0.0,
                "error": None,
                "reason": None,
            }
            start = time.perf_counter()
            try:
                await self._dispatch(page, step, base_url)
            except UINavigationBlocked as e:
                record["status"] = "failed"
                record["error"] = e.message
                record["reason"] = REASON_NAVIGATION_BLOCKED
                record["cost"] = round(time.perf_counter() - start, 3)
                self.steps.append(record)
                self.append(f"步骤 {index} 失败: {e.message}")
                raise
            except Exception as e:
                record["status"] = "failed"
                record["error"] = str(e)
                record["reason"] = self._reason_of(e)
                record["cost"] = round(time.perf_counter() - start, 3)
                self.steps.append(record)
                self.append(f"步骤 {index} 失败: {e}")
                # 单步失败 → 停止后续步骤(FR-024), 保留现场
                return
            record["cost"] = round(time.perf_counter() - start, 3)
            self.steps.append(record)
            self.append(f"步骤 {index} {record['action']} 执行完成, 耗时 {record['cost']}s")

    # ---------- 动作分派 ----------

    async def _dispatch(self, page, step: dict, base_url: str):
        """把一个步骤翻译成浏览器操作 —— 白名单分派, 没有兜底的「执行任意动作」分支"""
        action = step["action"]
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            # 理论上 validate_steps 已经拦掉了, 这里是最后一道防线
            raise UIExecutionError(f"不支持的动作: {action}", REASON_BROWSER_ERROR)
        timeout = self._step_timeout(step)
        await handler(page, step, base_url, timeout)

    def _step_timeout(self, step: dict) -> float:
        """单步超时(秒) —— 步骤级 timeout 覆盖用例级 timeout"""
        value = step.get("timeout")
        if value is None:
            return float(self.ui_case.timeout or 30)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(self.ui_case.timeout or 30)

    async def _locator_of(self, page, step: dict):
        """构造 Locator —— 元素引用优先, 内联定位兜底"""
        from app.core.ui_locator import build_locator
        strategy = step.get("_strategy")
        locator = step.get("_locator")
        name_attr = step.get("_name_attr")
        return build_locator(page, strategy, locator, name_attr)

    async def _unique(self, page, step: dict):
        """
        取**唯一**匹配的元素。

        定位到 0 个或多个元素时显式抛错 —— 静默取第一个就是不确定性,
        违反 constitution 原则 I。
        """
        from app.core.ui_locator import resolve_unique
        return await resolve_unique(await self._locator_of(page, step))

    # ---- 导航 ----

    async def _do_goto(self, page, step, base_url, timeout):
        url = resolve_step_url(base_url, self.render(step.get("url")), self.allowed_domains)
        await self._goto_with_retry(page, url, timeout)
        self.current_url = page.url

    async def _goto_with_retry(self, page, url, timeout):
        """导航失败时按**固定**次数与**固定**退避重试 —— 不带随机抖动"""
        last = None
        for attempt in range(RETRY_TIMES):
            try:
                await page.goto(url, timeout=timeout * 1000)
                return
            except Exception as e:
                last = e
                if attempt < RETRY_TIMES - 1:
                    # 固定退避, 不随机
                    await page.wait_for_timeout(int(RETRY_DELAY * 1000))
        raise UIExecutionError(f"打开页面失败: {last}", REASON_TIMEOUT)

    async def _do_back(self, page, step, base_url, timeout):
        await page.go_back(timeout=timeout * 1000)
        self.current_url = page.url

    async def _do_reload(self, page, step, base_url, timeout):
        await page.reload(timeout=timeout * 1000)
        self.current_url = page.url

    # ---- 交互 ----

    async def _do_click(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.click(timeout=timeout * 1000)

    async def _do_dblclick(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.dblclick(timeout=timeout * 1000)

    async def _do_fill(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.fill(self.render(step.get("text")), timeout=timeout * 1000)

    async def _do_clear(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.clear(timeout=timeout * 1000)

    async def _do_press(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.press(self.render(step.get("text")), timeout=timeout * 1000)

    async def _do_select(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.select_option(self.render(step.get("value")), timeout=timeout * 1000)

    async def _do_check(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.check(timeout=timeout * 1000)

    async def _do_uncheck(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.uncheck(timeout=timeout * 1000)

    async def _do_hover(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        await target.hover(timeout=timeout * 1000)

    async def _do_upload(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        files = step.get("files")
        if isinstance(files, str):
            files = [files]
        await target.set_input_files(files, timeout=timeout * 1000)

    async def _do_drag(self, page, step, base_url, timeout):
        source = await self._unique(page, step)
        target_selector = self.render(step.get("value"))
        await source.drag_to(page.locator(target_selector), timeout=timeout * 1000)

    # ---- 等待 ----

    async def _do_wait_for(self, page, step, base_url, timeout):
        """条件等待 —— 首选的等待方式, 引擎不插入任何隐式 sleep"""
        target = await self._unique(page, step)
        await target.wait_for(state=step.get("state"), timeout=timeout * 1000)

    async def _do_wait_timeout(self, page, step, base_url, timeout):
        """固定等待 —— 毫秒数由用户在步骤里显式配置, 不是引擎的默认值"""
        try:
            millis = int(step.get("timeout"))
        except (TypeError, ValueError):
            raise UIExecutionError("wait_timeout 的 timeout 必须是毫秒数", REASON_BROWSER_ERROR)
        if millis < 0:
            raise UIExecutionError("wait_timeout 的 timeout 不能为负数", REASON_BROWSER_ERROR)
        await page.wait_for_timeout(millis)

    # ---- 断言 ----

    async def _do_expect_text(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        actual = (await target.inner_text()).strip()
        expected = self.render(step.get("value"))
        self._add_assertion(step, "equal", expected, actual)

    async def _do_expect_visible(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        visible = await target.is_visible()
        self._add_assertion(step, "equal", True, visible)

    async def _do_expect_hidden(self, page, step, base_url, timeout):
        """元素不存在也算「不可见」—— 隐藏是「看不到」, 不是「必须在 DOM 里」"""
        locator = await self._locator_of(page, step)
        count = await locator.count()
        if count == 0:
            self._add_assertion(step, "equal", False, False)
            return
        if count > 1:
            from app.core.ui_locator import UILocatorError
            raise UILocatorError(f"定位到 {count} 个匹配元素, 请用更精确的定位策略",
                                 REASON_ELEMENT_AMBIGUOUS)
        visible = await locator.first.is_visible()
        self._add_assertion(step, "equal", False, visible)

    async def _do_expect_url(self, page, step, base_url, timeout):
        actual = page.url
        expected = self.render(step.get("value"))
        self._add_assertion(step, "equal", expected, actual)

    async def _do_expect_count(self, page, step, base_url, timeout):
        locator = await self._locator_of(page, step)
        count = await locator.count()
        try:
            expected = int(step.get("value"))
        except (TypeError, ValueError):
            expected = self.render(step.get("value"))
        self._add_assertion(step, "length_eq", expected, count)

    async def _do_expect_value(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        actual = await target.input_value()
        expected = self.render(step.get("value"))
        self._add_assertion(step, "equal", expected, actual)

    async def _do_expect_enabled(self, page, step, base_url, timeout):
        target = await self._unique(page, step)
        enabled = await target.is_enabled()
        self._add_assertion(step, "equal", True, enabled)

    # ---- 辅助 ----

    async def _do_screenshot(self, page, step, base_url, timeout):
        """主动截图 —— 失败截图由外层统一处理, 这里只在用户显式指定动作时截一次"""
        self.screenshot = await page.screenshot(type="png")
        self.screenshot_name = self.render(step.get("value")) or "manual.png"

    async def _do_scroll(self, page, step, base_url, timeout):
        if step.get("element"):
            target = await self._unique(page, step)
            await target.scroll_into_view_if_needed(timeout=timeout * 1000)
        else:
            # 滚到底 —— 用滚轮事件而不是 evaluate, 不在浏览器里执行脚本
            await page.mouse.wheel(0, 100000)

    async def _do_set_viewport(self, page, step, base_url, timeout):
        width, height = self._parse_viewport(self.render(step.get("value")))
        await page.set_viewport_size({"width": width, "height": height})

    # ---------- 断言汇总 ----------

    def _add_assertion(self, step: dict, assert_type: str, expected, actually):
        """
        记录一条断言。

        汇总成**与接口用例同结构**的 JSON(写入 pity_test_result.asserts),
        报告页与统计口径复用既有逻辑, 不做第二套。
        """
        status, msg = self._compare(assert_type, expected, actually)
        index = len(self.steps) + 1
        self.assertions.append({
            "name": f"步骤 {index} {step.get('action')}",
            "assert_type": assert_type,
            "expected": expected,
            "actually": actually,
            "status": status,
            "msg": msg,
        })
        self.append(msg)

    @staticmethod
    def _compare(assert_type: str, expected, actually) -> Tuple[bool, str]:
        """断言比较 —— 语义与 Executor.ops 的 equal / length_eq 一致"""
        if assert_type == "equal":
            if expected == actually:
                return True, f"预期结果: {expected} 等于 实际结果: {actually}【✔】"
            return False, f"预期结果: {expected} 不等于 实际结果: {actually}【❌】"
        if assert_type == "length_eq":
            if expected == actually:
                return True, f"预期数量: {expected} 等于 实际数量: {actually}【✔】"
            return False, f"预期数量: {expected} 不等于 实际数量: {actually}【❌】"
        return False, "不支持的断言方式💔"

    # ---------- 结果组装 ----------

    @staticmethod
    def _target_text(step: dict) -> str:
        if step.get("element"):
            return step["element"]
        if step.get("url"):
            return step["url"]
        if step.get("_locator"):
            return step["_locator"]
        if step.get("value"):
            return str(step["value"])
        return ""

    @staticmethod
    def _parse_viewport(viewport: str) -> Tuple[int, int]:
        try:
            parts = str(viewport).lower().split("x")
            width, height = int(parts[0]), int(parts[1])
            if width <= 0 or height <= 0:
                raise ValueError
            return width, height
        except Exception:
            return 1280, 720

    def _make_route_guard(self):
        """
        浏览器层的请求拦截 —— 页面内的子资源同样受 SSRF 约束(检查点 5)。

        重定向的每一跳也会重新走这个拦截器, 所以「重定向跳到内网」同样会被拦下。
        """
        async def handler(route, request):
            try:
                url = request.url
                if "://" not in url:
                    await route.abort()
                    return
                scheme, rest = url.split("://", 1)
                if scheme.lower() not in ("http", "https"):
                    await route.abort()
                    return
                host = rest.split("/", 1)[0].split(":", 1)[0].lower()
                if not self._host_allowed(host):
                    await route.abort()
                    return
                await route.continue_()
            except Exception:
                # 拦截器自身出错时**放行**会放大风险, 宁可直接中断该请求
                try:
                    await route.abort()
                except Exception:
                    pass

        return handler

    def _host_allowed(self, host: str) -> bool:
        """主机是否放行 —— 带缓存, 避免每个子资源请求都做一次 DNS 解析"""
        if host in self._host_cache:
            return self._host_cache[host]
        from app.utils.ui_security import domain_allowed, is_blocked_ip, resolve_host
        allowed = domain_allowed(host, self.allowed_domains)
        if allowed:
            ips = resolve_host(host)
            if not ips:
                allowed = False
            else:
                for ip in ips:
                    if is_blocked_ip(ip):
                        allowed = False
                        break
        self._host_cache[host] = allowed
        return allowed

    def _result(self, status: int = 0, error: str = None, error_reason: str = None) -> dict:
        """
        组装执行结果。

        `asserts` 用**与接口用例同结构**的 JSON(键 → {status, msg}),
        这样报告页与统计口径完全一致(FR-034)。
        """
        asserts = dict()
        failed = False
        for index, item in enumerate(self.assertions):
            asserts[f"ui_{index}"] = {"status": item["status"], "msg": item["msg"]}
            if not item["status"]:
                failed = True
        if failed and status == 0:
            status = 1
        return {
            "status": status,
            "steps": self.steps,
            "assertions": self.assertions,
            "asserts": json.dumps(asserts, ensure_ascii=False),
            "error": error,
            "error_reason": error_reason,
            "url": self.current_url,
            "screenshot": self.screenshot,
            "screenshot_name": self.screenshot_name,
        }


# ============================================================================
# 对外的执行入口 —— 批量执行与单条调试共用同一个函数
# ============================================================================


async def run_ui_case(case_id: int, env: int = None, params: dict = None, logger=None) -> dict:
    """
    执行一条 UI 用例。

    批量执行(`Executor.run_single` 按 request_type 分派)与单条调试(`/ui/case/run`)
    **最终调的是同一个函数**, 产生同一种结果, 都写 `pity_test_result`。

    :param case_id: pity_testcase.id
    :param env: 环境 id(决定生效的域名白名单)
    :param params: 变量上下文(全局变量 + 请求参数)
    :param logger: CaseLog
    :return: 执行结果 dict
    """
    from app.crud.test_case.TestCaseDao import TestCaseDao
    from app.crud.ui.UIAllowedDomainDao import UIAllowedDomainDao
    from app.crud.ui.UICaseDao import UICaseDao

    case_info = await TestCaseDao.async_query_test_case(case_id)
    ui_case = await UICaseDao.query_ui_case(case_id)
    if ui_case is None:
        return dict(status=2, steps=[], assertions=[], asserts="{}", error="用例不存在或不是 UI 用例",
                    error_reason=REASON_BROWSER_ERROR, url=None, screenshot=None, screenshot_name=None,
                    case_id=case_id, case_name=case_info.name if case_info else None)
    project_id = await UICaseDao.query_project_id(case_id)
    if project_id is None:
        return dict(status=2, steps=[], assertions=[], asserts="{}", error="无法确定用例所属项目",
                    error_reason=REASON_BROWSER_ERROR, url=None, screenshot=None, screenshot_name=None,
                    case_id=case_id, case_name=case_info.name if case_info else None)
    domains = await UIAllowedDomainDao.list_domain_names(project_id, env)
    executor = UIExecutor(ui_case, project_id, domains, params=params, logger=logger)
    result = await executor.run()
    result["case_id"] = case_id
    result["case_name"] = case_info.name if case_info else None
    result["project_id"] = project_id
    return result


async def upload_failure_screenshot(user_id: int, case_id: int, name: str, content: bytes) -> str:
    """
    失败截图上传 OSS, 返回可访问的 URL。

    上传失败不影响用例结论 —— 截图只是排查用的证据, 不该把用例结果搞成出错。
    """
    try:
        from app.crud.oss.PityOssDao import PityOssDao
        from app.middleware.oss import OssClient
        from app.models.oss_file import PityOssFile
        client = OssClient.get_oss_client()
        filepath = f"ui/{case_id}/{name}"
        file_url, file_size = await client.create_file(filepath, content, base_path="ui")
        model = PityOssFile(user_id, filepath, file_url, PityOssFile.get_size(file_size))
        await PityOssDao.insert(model=model, log=False)
        return file_url
    except Exception:
        return ""

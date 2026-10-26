"""
定位器 —— 把「定位策略 + 定位值」翻译成 Playwright 的 Locator

**定位到多个元素时显式失败, 不静默取第一个** —— 静默取第一个就是不确定性,
违反 constitution 原则 I(确定性优先)。见 contracts/steps.md §4.4。

STRATEGIES 的权威定义在 `app/core/ui_executor.py`(8 种定位策略),
前端镜像在 `frontend/src/consts/uiTest.ts` —— 改一处必须同时改另一处。
"""
from typing import Optional

# 定位失败的两类错误 —— 对应 contracts/api.md §3.2 的失败原因分类
UI_ELEMENT_NOT_FOUND = "element_not_found"
UI_ELEMENT_AMBIGUOUS = "element_ambiguous"


class UILocatorError(Exception):
    def __init__(self, message: str, reason: str = UI_ELEMENT_NOT_FOUND):
        super().__init__(message)
        self.message = message
        self.reason = reason


def build_locator(page, strategy: str, locator: str, name_attr: Optional[str] = None):
    """
    按定位策略构造 Playwright 的 Locator。

    :param page: Playwright Page
    :param strategy: 8 种策略之一(css / xpath / id / text / role / placeholder / label / testid)
    :param locator: 定位值
    :param name_attr: role 策略时的 accessible name
    """
    if not strategy:
        raise UILocatorError("缺少定位策略")
    if not locator:
        raise UILocatorError("缺少定位值")
    if strategy == "css":
        return page.locator(locator)
    if strategy == "xpath":
        return page.locator(f"xpath={locator}")
    if strategy == "id":
        return page.locator(f"#{locator}")
    if strategy == "text":
        return page.get_by_text(locator)
    if strategy == "role":
        # role 策略额外用 accessible name 缩小范围, 但 name_attr 可以为空
        if name_attr:
            return page.get_by_role(locator, name=name_attr)
        return page.get_by_role(locator)
    if strategy == "placeholder":
        return page.get_by_placeholder(locator)
    if strategy == "label":
        return page.get_by_label(locator)
    if strategy == "testid":
        return page.get_by_test_id(locator)
    raise UILocatorError(f"不支持的定位策略: {strategy}")


async def resolve_unique(target):
    """
    要求定位结果**恰好一个**元素。

    - 0 个 → element_not_found
    - 多个 → element_ambiguous(显式失败, 不静默取第一个)
    """
    count = await target.count()
    if count == 0:
        raise UILocatorError("未找到匹配的元素", UI_ELEMENT_NOT_FOUND)
    if count > 1:
        raise UILocatorError(f"定位到 {count} 个匹配元素, 请用更精确的定位策略, 或在元素定义中指定索引",
                             UI_ELEMENT_AMBIGUOUS)
    return target.first

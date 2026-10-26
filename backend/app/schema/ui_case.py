"""
UI 自动化相关表单模型(pydantic v1)

步骤 DSL 的动作白名单与定位策略的**权威定义在 `app/core/ui_executor.py`**,
这里只做「入参形状」的校验, 不重复定义白名单 —— 避免两处漂移。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, validator

from app.schema.base import PityModel

# 与 app/core/ui_executor.py 的 STRATEGIES 一致(8 种)
STRATEGIES = ("css", "xpath", "id", "text", "role", "placeholder", "label", "testid")


class UIPageForm(BaseModel):
    """页面表单"""
    id: int = None
    project_id: int
    name: str
    url: str = None
    parent: int = None
    description: str = ""

    @validator("project_id", "name")
    def page_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("name")
    def name_length(cls, v):
        if len(v) > 64:
            raise ValueError("页面名不能超过 64 个字符")
        return v


class UIElementForm(BaseModel):
    """元素表单 —— 元素 = 一条定位策略"""
    id: int = None
    project_id: int
    page_id: int
    name: str
    strategy: str
    locator: str
    name_attr: str = None
    description: str = ""

    @validator("project_id", "page_id", "name", "strategy", "locator")
    def element_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("strategy")
    def strategy_valid(cls, v):
        if v not in STRATEGIES:
            raise ValueError(f"不支持的定位策略: {v}")
        return v

    @validator("name")
    def name_length(cls, v):
        if len(v) > 64:
            raise ValueError("元素名不能超过 64 个字符")
        return v

    @validator("locator")
    def locator_length(cls, v):
        if len(v) > 256:
            raise ValueError("定位值不能超过 256 个字符")
        return v

    @validator("name_attr")
    def name_attr_only_for_role(cls, v, values):
        strategy = values.get("strategy")
        if strategy and strategy != "role" and v:
            raise ValueError("只有 role 策略才能填可访问名称")
        return v


class UIElementStatusForm(BaseModel):
    """元素启用 / 停用"""
    id: int
    project_id: int
    status: int

    @validator("id", "project_id")
    def not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("status")
    def status_valid(cls, v):
        if v not in (0, 1):
            raise ValueError("元素状态只能是 0(停用) 或 1(启用)")
        return v


class UIAllowedDomainForm(BaseModel):
    """允许域名白名单 —— SSRF 安全边界"""
    id: int = None
    project_id: int
    domain: str
    env: int = None

    @validator("project_id", "domain")
    def domain_not_empty(cls, v):
        return PityModel.not_empty(v)


class UICaseForm(BaseModel):
    """UI 用例表单 —— 主体落在既有的 pity_testcase, 这里只带 UI 专有字段"""
    id: int = None
    project_id: int
    directory_id: int
    name: str
    priority: str = "P1"
    base_url: str
    viewport: str = "1280x720"
    timeout: int = 30
    steps: List[Dict[str, Any]] = []

    @validator("project_id", "directory_id", "name", "base_url")
    def case_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("name")
    def name_length(cls, v):
        # pity_testcase.name 是 String(32) —— 超长由路由层**截断并回显告警**(FR-035),
        # 不在这里直接拒绝, 否则用户看不到截断后的结果
        return v

    @validator("viewport")
    def viewport_valid(cls, v):
        parts = str(v).lower().split("x")
        if len(parts) != 2:
            raise ValueError("视口格式应为 宽x高, 例如 1280x720")
        try:
            width, height = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("视口格式应为 宽x高, 例如 1280x720")
        if width <= 0 or height <= 0:
            raise ValueError("视口宽高必须大于 0")
        return v

    @validator("timeout")
    def timeout_valid(cls, v):
        if v <= 0:
            raise ValueError("单步超时必须大于 0")
        return v

    @validator("steps")
    def steps_valid(cls, v):
        if not isinstance(v, list):
            raise ValueError("步骤必须是数组")
        return v


class UIRunForm(BaseModel):
    """单条调试执行"""
    case_id: int
    env: int = None
    node_id: int = None

    @validator("case_id")
    def case_not_empty(cls, v):
        return PityModel.not_empty(v)


class UIImportForm(BaseModel):
    """录制脚本导入"""
    project_id: int
    source: str = "codegen"
    script: str

    @validator("project_id", "script")
    def import_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("source")
    def source_valid(cls, v):
        if v not in ("codegen", "manual"):
            raise ValueError("导入来源只支持 codegen 或 manual")
        return v

"""
Mock 配置的表单模型(pydantic v1)

白名单与上限的**权威定义在 `app/enums/MockEnum.py`**, 这里只做「入参形状」的校验,
不重复定义白名单 —— 避免两处漂移。

**回显变量白名单**(与 `app/core/mock_render.py` 共用同一语义, data-model.md §4):
`$request.path` / `$request.query.<name>` / `$request.body.<key.path>` / `$request.header.<name>`
未知变量在保存时被拦截并指出 —— 前端就地列出合法变量清单(spec FR-005)。
"""
import json
import re
from typing import Optional

from pydantic import BaseModel, validator

from app.core.mock_render import VARIABLE_PATTERN
from app.enums.MockEnum import MAX_DELAY, MAX_PATH_LENGTH, MAX_STATUS_CODE, METHODS, MIN_STATUS_CODE
from app.schema.base import PityModel

# 合法回显变量 —— 封闭白名单。**权威定义在 app/core/mock_render.py**(渲染器用它替换,
# 这里引用同一 pattern 派生锚定版做保存校验, 保证单一出处不漂移)。注意 body 的「路径」
# 支持点分逐层取(含数字索引), query / header 的键名允许字母数字与 _ . -。
REQUEST_VARIABLE_PATTERN = re.compile(f"^{VARIABLE_PATTERN.pattern}$")

MAX_NAME = 50
MAX_REMARK = 200


class MockRuleForm(BaseModel):
    """新建 / 编辑规则表单"""
    id: int = None
    project_id: int
    name: str
    method: str
    path: str
    priority: int = 0
    status_code: int = 200
    response_headers: str = None
    response_body: str = None
    delay: int = 0
    status: int = 1
    remark: str = ""

    @validator("project_id", "name", "method", "path")
    def rule_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("name")
    def name_length(cls, v):
        if len(v) > MAX_NAME:
            raise ValueError(f"规则名不能超过 {MAX_NAME} 个字符")
        return v

    @validator("method")
    def method_valid(cls, v):
        if v not in METHODS:
            raise ValueError(f"不支持的请求方法: {v}")
        return v

    @validator("path")
    def path_valid(cls, v):
        if len(v) > MAX_PATH_LENGTH:
            raise ValueError(f"路径不能超过 {MAX_PATH_LENGTH} 个字符")
        if not v.startswith("/"):
            raise ValueError("路径必须以 / 开头")
        if any(c.isspace() for c in v):
            raise ValueError("路径不能包含空白字符")
        if "*" in v[:-1]:
            raise ValueError("* 通配只能出现在路径末尾")
        return v

    @validator("response_headers")
    def headers_valid(cls, v):
        if v is None or v == "":
            return v
        try:
            parsed = json.loads(v)
        except Exception as e:
            raise ValueError(f"响应头必须是合法的 JSON 对象: {e}")
        if not isinstance(parsed, dict):
            raise ValueError("响应头必须是 JSON 对象")
        return v

    @validator("response_body")
    def body_variables_valid(cls, v):
        """
        含 `$` 的变量名必须在白名单内 —— 未知变量拦截保存(spec FR-005)。

        规则: 扫描所有「$ + 字母开头」的标识符形态 token:
        - `$request.` 开头 → 必须匹配白名单(REQUEST_VARIABLE_PATTERN)
        - 其他 `$字母...`(如 $randomInt / $timestamp / $foo)→ 拒绝并提示合法清单
        - `$5`(数字开头)与 `${...}`(非本系统变量语法)→ 放行, 原样输出
        """
        if v is None:
            return v
        for token in re.findall(r"\$[A-Za-z][A-Za-z0-9_.-]*", v):
            if token.startswith("$request."):
                if not REQUEST_VARIABLE_PATTERN.match(token):
                    raise ValueError(
                        f"不支持的变量: {token}, 合法变量见 $request.path / $request.query.* / $request.body.* / $request.header.*")
            else:
                raise ValueError(
                    f"不支持的变量: {token}, 合法变量见 $request.path / $request.query.* / $request.body.* / $request.header.*")
        return v

    @validator("delay")
    def delay_valid(cls, v):
        if v < 0 or v > MAX_DELAY:
            raise ValueError(f"延迟必须在 0~{MAX_DELAY} 毫秒之间")
        return v

    @validator("status_code")
    def status_code_valid(cls, v):
        if v < MIN_STATUS_CODE or v > MAX_STATUS_CODE:
            raise ValueError(f"状态码必须在 {MIN_STATUS_CODE}~{MAX_STATUS_CODE} 之间")
        return v

    @validator("status")
    def status_valid(cls, v):
        if v not in (0, 1):
            raise ValueError("状态只能是 0(停用) 或 1(启用)")
        return v

    @validator("remark")
    def remark_length(cls, v):
        if v is None:
            return ""
        if len(v) > MAX_REMARK:
            raise ValueError(f"备注不能超过 {MAX_REMARK} 个字符")
        return v


class MockRuleStatusForm(BaseModel):
    """启停规则表单"""
    id: int
    project_id: int
    status: int

    @validator("id", "project_id")
    def id_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("status")
    def status_valid(cls, v):
        if v not in (0, 1):
            raise ValueError("状态只能是 0(停用) 或 1(启用)")
        return v


class MockRulePreviewForm(BaseModel):
    """规则调试表单 —— 就地模拟一次匹配, 不经过对外服务、不产生真实延迟等待"""
    project_id: int
    method: str
    path: str
    body: str = None
    headers: str = None

    @validator("project_id", "method", "path")
    def preview_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("method")
    def method_valid(cls, v):
        if v not in METHODS:
            raise ValueError(f"不支持的请求方法: {v}")
        return v

    @validator("headers")
    def headers_valid(cls, v):
        if v is None or v == "":
            return v
        try:
            parsed = json.loads(v)
        except Exception as e:
            raise ValueError(f"headers 必须是合法的 JSON 对象: {e}")
        if not isinstance(parsed, dict):
            raise ValueError("headers 必须是 JSON 对象")
        return v

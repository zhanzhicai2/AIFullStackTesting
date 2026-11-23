"""
持续集成(CI)的表单模型(pydantic v1)

字段上限与枚举的**权威定义在 `app/enums/CiEnum.py`**, 这里只做「入参形状」校验,
不重复定义常量 —— 避免两处漂移(契约 `specs/004-ci/contracts/api.md`)。

**`expires_at` 的三态语义(决定 Q4)**:
- 请求体**不含** `expires_at` 键      → 默认 `now + 365 天`
- 显式传 `null`                        → 长期有效(永不过期)
- 传具体时间                            → 按该时间

pydantic v1 下「不传」与「传 null」都会落成 `None`, 无法区分 —— 因此路由层用
`form.__fields_set__` 判断该键是否被显式提供(见 `routers/ci/integration.py`)。
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, validator

from app.enums.CiEnum import (
    ALLOWED_URL_SCHEMES,
    CALLBACK_URL_MAX_LEN,
    EXTERNAL_BUILD_ID_MAX_LEN,
    EXTERNAL_URL_MAX_LEN,
    INTEGRATION_NAME_MAX_LEN,
    WAIT_TIMEOUT_DEFAULT_SEC,
    WAIT_TIMEOUT_MAX_SEC,
    WAIT_TIMEOUT_MIN_SEC,
)
from app.schema.base import PityModel


def check_url_field(value: Optional[str], field_label: str, max_len: int) -> Optional[str]:
    """
    外部可控 URL 的统一校验: 长度 + **scheme 白名单**(安全审查 F1/F4)。

    `external_url` 会被前端渲染成可点链接, `callback_url` 二期要出网 ——
    放过 `javascript:` / `data:` / `ftp:` 等就等于给它们开了执行/出网的口子。
    白名单只认 `http` / `https`, 权威定义在 `app/enums/CiEnum.ALLOWED_URL_SCHEMES`。
    """
    if value is None or value == "":
        return None
    if len(value) > max_len:
        raise ValueError(f"{field_label}不能超过 {max_len} 个字符")
    if "://" not in value:
        raise ValueError(f"{field_label}必须是完整的 http/https 地址")
    scheme = value.split("://", 1)[0].lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(f"{field_label}只允许 {'/'.join(ALLOWED_URL_SCHEMES)}, 不接受 {scheme}")
    return value


class CiIntegrationForm(BaseModel):
    """新建 / 编辑接入凭据。**不接受任何凭据字段** —— 凭据不可改, 只能删了重签。"""

    id: int = None
    project_id: int
    name: str
    plan_id: int = None
    callback_url: str = None
    expires_at: datetime = None

    @validator("project_id", "name")
    def required_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("name")
    def name_length(cls, v):
        if len(v) > INTEGRATION_NAME_MAX_LEN:
            raise ValueError(f"集成名不能超过 {INTEGRATION_NAME_MAX_LEN} 个字符")
        return v

    @validator("callback_url")
    def callback_url_valid(cls, v):
        # 一期只存不发(决定 Q5) —— 但 scheme 白名单现在就上, 先把二期的口子堵住
        return check_url_field(v, "回调地址", CALLBACK_URL_MAX_LEN)

    @validator("plan_id")
    def plan_id_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("测试计划 id 必须为正整数")
        return v


class CiRunForm(BaseModel):
    """
    触发测试计划(spec FR-009~019)。

    `wait` 默认 `false`(决定 Q3: 默认不等待, 文档主推轮询);
    `timeout_sec` 仅 `wait=true` 生效, 默认 300、上限 1800(spec FR-011)。
    """

    plan_id: int = None          # 凭据未绑定默认计划时必填(路由层判定, 见 contracts §3.1)
    env: List[int] = None        # 覆盖计划的执行环境; 不传 = 按计划配置(FR-019)
    wait: bool = False
    timeout_sec: int = WAIT_TIMEOUT_DEFAULT_SEC
    external_build_id: str = None
    external_url: str = None

    @validator("plan_id")
    def plan_id_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("测试计划 id 必须为正整数")
        return v

    @validator("env")
    def env_positive(cls, v):
        if v is None:
            return v
        if not v:
            raise ValueError("环境列表不能为空, 不传该字段表示按计划配置")
        if any(e <= 0 for e in v):
            raise ValueError("环境 id 必须为正整数")
        return v

    @validator("timeout_sec")
    def timeout_range(cls, v):
        if v < WAIT_TIMEOUT_MIN_SEC or v > WAIT_TIMEOUT_MAX_SEC:
            raise ValueError(
                f"timeout_sec 必须在 {WAIT_TIMEOUT_MIN_SEC}~{WAIT_TIMEOUT_MAX_SEC} 秒之间")
        return v

    @validator("external_build_id")
    def build_id_length(cls, v):
        if v is None or v == "":
            return None
        if len(v) > EXTERNAL_BUILD_ID_MAX_LEN:
            raise ValueError(f"外部构建号不能超过 {EXTERNAL_BUILD_ID_MAX_LEN} 个字符")
        return v

    @validator("external_url")
    def external_url_valid(cls, v):
        # 安全审查 F1: 该值会被 RunHistoryPanel 渲染成可点链接,
        # 放过 javascript:/data: 等 = 存储型链接注入
        return check_url_field(v, "外部地址", EXTERNAL_URL_MAX_LEN)

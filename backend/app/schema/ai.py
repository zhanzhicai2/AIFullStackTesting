from typing import List

from pydantic import BaseModel, validator

from app.schema.base import PityModel


class AIVendorUpdateForm(BaseModel):
    id: int
    en_name: str = None
    api_key: str = None
    base_url: str = None
    console_url: str = None
    enable: bool = False

    @validator("id")
    def id_not_empty(cls, v):
        return PityModel.not_empty(v)


class AIModelForm(BaseModel):
    id: int = None
    vendor_id: int
    name: str
    model_type: str = 'chat'
    enable: bool = False

    @validator("vendor_id", "name")
    def not_empty(cls, v):
        return PityModel.not_empty(v)


class AIModelUpdateForm(AIModelForm):
    id: int
    # 模型参数,JSON 字符串: {"temperature": 0.7, "max_tokens": 2048, "top_p": 0.9}
    params: str = None

    @validator("id")
    def id_not_empty(cls, v):
        return PityModel.not_empty(v)


class AIModelFetchForm(BaseModel):
    vendor_id: int

    @validator("vendor_id")
    def id_not_empty(cls, v):
        return PityModel.not_empty(v)


class AIModelSystemForm(BaseModel):
    vendor_code: str

    @validator("vendor_code")
    def code_not_empty(cls, v):
        return PityModel.not_empty(v)


class AIModelImportDto(BaseModel):
    vendor_id: int
    # 1=系统模板 2=厂商拉取 3=自定义
    source: int = 3
    models: List[str]
    model_types: dict = None

    @validator("vendor_id", "models")
    def not_empty(cls, v):
        return PityModel.not_empty(v)

class ChatSessionInsertForm(BaseModel):
    vendor_id: int = None
    model_id: int = None


class ChatSessionUpdateForm(BaseModel):
    session_id: int
    title: str = None
    vendor_id: int = None
    model_id: int = None

    @validator("session_id")
    def id_not_empty(cls, v):
        return PityModel.not_empty(v)


class ChatStreamForm(BaseModel):
    session_id: int
    content: str
    # 可覆盖会话上记录的模型, 前端切换模型后立即生效
    vendor_id: int = None
    model_id: int = None

    @validator("session_id")
    def id_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("content")
    def content_not_empty(cls, v):
        return PityModel.not_empty(v)

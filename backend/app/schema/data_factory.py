"""
数据工厂相关表单模型

columns 字段统一存 JSON 字符串(与 Constructor.constructor_json / PityTestcaseData.json_data 一致),
后端在 DAO/内核层负责 json.loads。
"""
import json
from typing import Any, List, Optional

from pydantic import BaseModel, validator

from app.schema.base import PityModel


class DataFactoryColumn(BaseModel):
    """单个字段的生成规则"""
    name: str
    type: str = "string"
    rule: dict = {}
    unique: bool = False
    nullable: bool = False
    default: Any = None
    comment: str = ""


class DataFactoryColumns(BaseModel):
    """整份规则集"""
    columns: List[DataFactoryColumn] = []


class PityDataFactoryForm(BaseModel):
    id: int = None
    name: str
    env: int
    project_id: int = None
    database_id: int = None
    table_name: str = None
    columns: str
    count: int = 10
    seed: int = 0
    remark: str = ""
    status: int = 1

    @validator("name", "env", "columns")
    def name_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("columns")
    def columns_valid(cls, v):
        """必须是合法 JSON, 且至少有一个字段"""
        try:
            data = json.loads(v)
        except Exception:
            raise ValueError("字段规则不是合法的 JSON")
        if not isinstance(data, dict) or not data.get("columns"):
            raise ValueError("字段规则不能为空")
        return v


class GenerateForm(BaseModel):
    """生成/导出/写库/绑定的公共入参"""
    dataset_id: int = None
    columns: str = None      # 不传 dataset_id 时用内联规则
    count: int = None        # 不传则用数据集里配置的默认条数
    seed: int = None         # 不传则用数据集里配置的种子; 0 表示每次随机
    rows: List[dict] = None  # 前端手动改过预览数据时直传, 不传则按 dataset+seed 重新生成

    @validator("count")
    def count_valid(cls, v):
        if v is None:
            return v
        if v <= 0:
            raise ValueError("生成条数必须大于 0")
        if v > 10000:
            raise ValueError("单次最多生成 10000 条")
        return v


class WriteDbForm(GenerateForm):
    database_id: int
    table_name: str

    @validator("database_id", "table_name")
    def target_not_empty(cls, v):
        return PityModel.not_empty(v)


class BindCaseForm(GenerateForm):
    case_id: int
    env: int
    name_prefix: str = "数据工厂"
    replace: bool = True     # True = 先软删同前缀的旧数据再写入

    @validator("case_id", "env")
    def case_not_empty(cls, v):
        return PityModel.not_empty(v)


class ExportForm(GenerateForm):
    file_type: str = "json"   # json / sql
    table_name: str = "data"

    @validator("file_type")
    def file_type_valid(cls, v):
        if v not in ("json", "sql"):
            raise ValueError("导出格式只支持 json 或 sql")
        return v


class AiParseForm(BaseModel):
    prompt: str
    vendor_id: int
    model_id: int

    @validator("prompt", "vendor_id", "model_id")
    def parse_not_empty(cls, v):
        return PityModel.not_empty(v)

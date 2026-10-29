"""
AI 工作台的表单模型(pydantic v1)

只做「入参形状」的校验 —— **业务规则校验不在这儿**:
- 断言类型白名单 / 优先级 / 类别 / 测试类型的权威定义在
  `app/enums/AIWorkbenchEnum.py`, 这里只引用不重定义
- 14 条 DSL 校验规则在 `app/core/ai_prompts/case_gen.py`

契约:`specs/001-ai-workbench/contracts/api.md`
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, validator

from app.enums.AIWorkbenchEnum import CASE_CATEGORIES, PRIORITIES, TEST_TYPES
from app.schema.base import PityModel


class GenerateForm(BaseModel):
    """生成用例草稿 —— contracts/api.md §3.1"""

    project_id: int
    directory_id: int
    title: str
    test_type: str = "api"
    vendor_id: int
    model_id: int
    source_type: str = "text"
    source_name: str = None
    content: str
    # 覆盖模型自身配置的参数(白名单键由 ai_client 兜底)
    params: Dict[str, Any] = None

    @validator("project_id", "directory_id", "vendor_id", "model_id")
    def ids_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("title", "content")
    def text_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("title")
    def title_length(cls, v):
        if len(v) > 64:
            raise ValueError("任务标题不能超过 64 个字符")
        return v

    @validator("test_type")
    def test_type_valid(cls, v):
        if v not in TEST_TYPES:
            raise ValueError(f"不支持的测试类型: {v}, 可选 {'/'.join(TEST_TYPES)}")
        return v

    @validator("source_type")
    def source_type_valid(cls, v):
        if v not in ("text", "document"):
            raise ValueError("来源类型只支持 text 或 document")
        return v

    @validator("source_name")
    def source_name_required(cls, v, values):
        if values.get("source_type") == "document" and not (v or "").strip():
            raise ValueError("文档来源必须提供文档名")
        return v

    @validator("content")
    def content_size(cls, v):
        # 文档上限 20MB —— 送进模型的内容量上限, 防止一个超大文档把上下文吃满
        if len(v) > 20 * 1024 * 1024:
            raise ValueError("需求正文超过 20MB 上限")
        return v


class UpdateDraftForm(BaseModel):
    """修改单条草稿 —— contracts/api.md §3.3"""

    draft_id: int
    # 用户修正后的 DSL JSON(整体替换草稿内容); 不传则只更新元数据
    content: Dict[str, Any] = None
    title: str = None
    priority: str = None
    category: str = None

    @validator("draft_id")
    def draft_id_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("priority")
    def priority_valid(cls, v):
        if v is not None and v not in PRIORITIES:
            raise ValueError(f"优先级只支持 {'/'.join(PRIORITIES)}")
        return v

    @validator("category")
    def category_valid(cls, v):
        if v is not None and v not in CASE_CATEGORIES:
            raise ValueError(f"类别只支持 {'/'.join(CASE_CATEGORIES)}")
        return v

    @validator("title")
    def title_length(cls, v):
        if v is not None and len(v) > 64:
            raise ValueError("用例标题不能超过 64 个字符")
        return v


class DraftIdsForm(BaseModel):
    """批量操作草稿 —— 采纳 / 驳回 共用"""

    draft_ids: List[int]

    @validator("draft_ids")
    def ids_not_empty(cls, v):
        if not v:
            raise ValueError("请至少选择一条草稿")
        return v


class AcceptForm(DraftIdsForm):
    """批量采纳 —— contracts/api.md §3.4"""


class RejectForm(DraftIdsForm):
    """批量驳回 —— contracts/api.md §3.5"""


class DocumentForm(BaseModel):
    """
    文档元信息 —— 上传**前**的类型与大小校验(前后端同一份口径)。

    真正的解析走 `POST /ai/document/parse`(multipart/form-data),
    这里的字段用于前端上传前预校验, 以及后端对非 multipart 入口的兜底校验。
    """

    filename: str
    size: int = 0
    content_type: str = ""

    @validator("filename")
    def filename_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("size")
    def size_valid(cls, v):
        if v and v > 20 * 1024 * 1024:
            raise ValueError("文件超过 20MB 上限")
        return v


class BugAnalyzeForm(BaseModel):
    """Bug 分析 —— contracts/api.md §4.1(result_id 与 text 二选一)"""

    result_id: int = None
    text: str = None
    # 模型: 不传则用平台第一个可用的对话模型
    vendor_id: int = None
    model_id: int = None

    @validator("result_id")
    def result_id_not_empty(cls, v):
        if v is not None and v <= 0:
            raise ValueError("执行记录 id 不合法")
        return v

    @validator("text")
    def text_not_empty(cls, v):
        if v is not None and not v.strip():
            return None
        return v


class LogClusterForm(BaseModel):
    """日志聚类 —— contracts/api.md §4.2(纯确定性, 不调模型)"""

    source: str = "text"
    file_id: int = None
    text: str = None
    since: str = None
    until: str = None
    max_lines: int = 20000

    @validator("source")
    def source_valid(cls, v):
        if v not in ("platform", "file", "text"):
            raise ValueError("日志来源只支持 platform / file / text")
        return v

    @validator("max_lines")
    def max_lines_valid(cls, v):
        if v is not None and (v <= 0 or v > 200000):
            raise ValueError("最大行数必须在 1 ~ 200000 之间")
        return v


class LogAnalyzeForm(BaseModel):
    """错误簇归因 —— contracts/api.md §4.4"""

    fingerprint: str
    samples: List[str] = []
    count: int = 0
    vendor_id: int = None
    model_id: int = None

    @validator("fingerprint")
    def fingerprint_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("samples")
    def samples_size(cls, v):
        # 样例是要送进模型的, 不限大小等于给了一个内存放大器
        if len(v) > 200:
            raise ValueError("样例条数过多, 请分批分析")
        total = sum(len(str(item or "")) for item in v)
        if total > 10 * 1024 * 1024:
            raise ValueError("样例内容超过 10MB 上限")
        return v


class SqlAnalyzeForm(BaseModel):
    """SQL 分析 —— contracts/api.md §4.3(sql 与 sql_history_id 二选一)"""

    sql: str = None
    database_id: int
    sql_history_id: int = None
    vendor_id: int = None
    model_id: int = None

    @validator("database_id")
    def database_id_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("sql")
    def sql_not_empty(cls, v):
        if v is not None and not v.strip():
            return None
        return v

    @validator("sql")
    def sql_size(cls, v):
        if v is not None and len(v) > 1024 * 1024:
            raise ValueError("SQL 过长")
        return v


class InvokeLogQueryForm(BaseModel):
    """调用流水查询条件 —— contracts/api.md §2.1"""

    page: int = 1
    size: int = 10
    scene: str = None
    model_name: str = None
    start_time: str = None
    end_time: str = None

"""
Mock 配置的一张表

- `pity_mock_rule`  Mock 规则(按项目隔离, 供对外 mock 服务匹配)

**确定性声明(constitution 原则 I)**: 本表与匹配引擎(`app/core/mock_engine.py`)、
渲染器(`app/core/mock_render.py`)不引入任何随机源 —— 同一请求 + 同一规则集 MUST
命中同一条规则;响应体变量仅「请求回显」($request.*), 由请求内容决定, 可重放。

**唯一约束说明**: 不设 DB 级唯一 —— 允许同「项目+方法+精确路径」存在多条规则
(靠优先级区分返回), 但新建精确路径规则时 DAO 层就地提示已存在(FR-007)。
"""
from sqlalchemy import Column, INT, String, TEXT

from app.models.basic import PityBase


class PityMockRule(PityBase):
    """Mock 规则 —— 命中即返回配置的静态响应"""

    __tablename__ = "pity_mock_rule"

    project_id = Column(INT, index=True, nullable=False, comment="所属项目id")
    name = Column(String(50), nullable=False, comment="规则名")
    method = Column(String(10), nullable=False, default="ANY",
                    comment="请求方法, 见 app/enums/MockEnum.py 的 METHODS")
    path = Column(String(255), nullable=False, comment="被测接口路径, 支持 :xxx 参数占位与末尾 * 通配")
    path_type = Column(INT, nullable=False, default=0,
                       comment="路径类型: 0 精确 1 参数化 2 通配(由 path 推导并固化, 见 mock_engine.derive_path_type)")
    priority = Column(INT, nullable=False, default=0, comment="匹配优先级, 数字越小越优先")
    status_code = Column(INT, nullable=False, default=200, comment="响应 HTTP 状态码")
    response_headers = Column(TEXT, comment="响应头, JSON 对象字符串")
    response_body = Column(TEXT, comment="响应体, JSON 或纯文本, 可含 $request.* 回显变量")
    delay = Column(INT, nullable=False, default=0, comment="模拟延迟(毫秒), 0~5000")
    status = Column(INT, nullable=False, default=1, comment="1: 启用 0: 停用")
    remark = Column(String(200), comment="备注")

    __tag__ = "Mock规则"
    __fields__ = (name, method, path)
    __show__ = 3
    __alias__ = dict(name="规则名", method="请求方法", path="接口路径", priority="优先级",
                     status_code="状态码", delay="延迟(ms)", status="状态", project_id="所属项目",
                     remark="备注")

    def __init__(self, name, method, path, user, project_id, priority=0, status_code=200,
                 response_headers=None, response_body=None, delay=0, status=1, remark="", id=None):
        super().__init__(user, id)
        self.name = name
        self.method = method
        self.path = path
        self.project_id = project_id
        self.priority = priority
        self.status_code = status_code
        self.response_headers = response_headers
        self.response_body = response_body
        self.delay = delay
        self.status = status
        self.remark = remark
        # path_type 由 DAO 层用 derive_path_type() 推导后回填 —— __init__ 不接收,
        # 防止手工构造时出现「path 与 path_type 不一致」的不变量破裂

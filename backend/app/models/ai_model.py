from sqlalchemy import BOOLEAN, INT, Column, String, TEXT, UniqueConstraint

from app.models.basic import PityBase


class AIModel(PityBase):
    __tablename__ = 'pity_ai_model'

    vendor_id = Column(INT, nullable=False, comment="所属厂商id")
    name = Column(String(128), nullable=False, comment="模型名称")
    # chat/embedding/rerank/image,对应 AIModelTypeEnum
    model_type = Column(String(16), default='chat', comment="模型类型")
    enable = Column(BOOLEAN, default=False, comment="是否启用")
    # 1=系统模板 2=厂商拉取 3=自定义,对应 AIModelSourceEnum
    source = Column(INT, default=3, comment="模型来源")
    params = Column(TEXT, comment="模型参数 JSON: temperature/max_tokens/top_p")
    sort = Column(INT, default=0, comment="排序")

    __table_args__ = (
        UniqueConstraint('vendor_id', 'name', 'deleted_at'),
    )

    __fields__ = (name, vendor_id)
    __tag__ = "AI模型"
    __alias__ = dict(name="模型名称", vendor_id="所属厂商", model_type="类型",
                     enable="启用", source="来源")
    __show__ = 2

    def __init__(self, vendor_id, name, model_type='chat', enable=False, source=3,
                 params=None, sort=0, user=None, id=None):
        super().__init__(user, id)
        self.vendor_id = vendor_id
        self.name = name
        self.model_type = model_type
        self.enable = enable
        self.source = source
        self.params = params
        self.sort = sort
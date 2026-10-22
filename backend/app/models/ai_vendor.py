from sqlalchemy import BOOLEAN, INT, Column, String, UniqueConstraint

from app.models.basic import PityBase


class AIVendor(PityBase):
    __tablename__ = 'pity_ai_vendor'

    name = Column(String(64), nullable=False, comment="厂商中文名称")
    en_name = Column(String(64), comment="厂商英文名称")
    # 厂商唯一标识,前端据此映射 logo 与预置模型模板
    code = Column(String(32), nullable=False, comment="厂商唯一标识")
    api_key = Column(String(256), comment="API Key")
    base_url = Column(String(256), comment="OpenAI 兼容 Base URL")
    console_url = Column(String(256), comment="获取 API Key 的控制台地址")
    enable = Column(BOOLEAN, default=False, comment="是否启用")
    builtin = Column(BOOLEAN, default=True, comment="是否预置厂商")
    sort = Column(INT, default=0, comment="排序")

    __table_args__ = (
        UniqueConstraint('code', 'deleted_at'),
    )

    __fields__ = (name, en_name)
    __tag__ = "AI模型厂商"
    __alias__ = dict(name="厂商名称", en_name="英文名称", code="标识",
                     api_key="API Key", base_url="Base URL", enable="启用")
    __show__ = 2

    def __init__(self, name, code, en_name=None, api_key=None, base_url=None, console_url=None,
                 enable=False, builtin=True, sort=0, user=None, id=None):
        super().__init__(user, id)
        self.name = name
        self.code = code
        self.en_name = en_name
        self.api_key = api_key
        self.base_url = base_url
        self.console_url = console_url
        self.enable = enable
        self.builtin = builtin
        self.sort = sort
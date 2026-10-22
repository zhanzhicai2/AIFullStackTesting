from sqlalchemy import INT, Column, String, TEXT

from app.models.basic import PityBase


class PityChatSession(PityBase):
    """AI 聊天会话,用户私有"""

    __tablename__ = 'pity_chat_session'

    title = Column(String(128), comment="会话标题")
    # 业务归属用户。刻意与 create_user 分开: create_user 是审计字段(谁建的),
    # user_id 是"这条会话归谁"的查询条件,两者语义不同
    user_id = Column(INT, nullable=False, index=True, comment="会话归属用户")
    vendor_id = Column(INT, comment="使用的厂商id")
    model_name = Column(String(128), comment="使用的模型名")

    __fields__ = (title,)
    __tag__ = "AI会话"
    __alias__ = dict(title="会话标题", user_id="归属用户", vendor_id="厂商", model_name="模型")
    __show__ = 1

    def __init__(self, user_id, title='新会话', vendor_id=None, model_name=None, user=None, id=None):
        super().__init__(user, id)
        self.user_id = user_id
        self.title = title
        self.vendor_id = vendor_id
        self.model_name = model_name


class PityChatMessage(PityBase):
    """AI 聊天消息,归属某个会话"""

    __tablename__ = 'pity_chat_message'

    session_id = Column(INT, nullable=False, index=True, comment="所属会话id")
    # system / user / assistant
    role = Column(String(16), nullable=False, comment="消息角色")
    content = Column(TEXT, comment="消息正文")
    model_name = Column(String(128), comment="assistant 消息使用的模型")
    tokens = Column(INT, default=0, comment="token 用量")

    __fields__ = (role,)
    __tag__ = "AI消息"
    __alias__ = dict(session_id="所属会话", role="角色", content="内容", model_name="模型")
    __show__ = 1

    def __init__(self, session_id, role, content, model_name=None, tokens=0, user=None, id=None):
        super().__init__(user, id)
        self.session_id = session_id
        self.role = role
        self.content = content
        self.model_name = model_name
        self.tokens = tokens
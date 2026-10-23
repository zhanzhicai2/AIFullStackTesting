"""
数据工厂数据集表

一个数据集 = 一组字段生成规则 + 生成条数 + 随机种子 + 目标落库位置。
生成结果本身不落库(seed 可重放), 用例联动时把生成结果物化成 pity_testcase_data。
"""
from sqlalchemy import Column, INT, String, UniqueConstraint, TEXT

from app.models.basic import PityBase


class PityDataFactory(PityBase):
    __tablename__ = "pity_data_factory"
    __table_args__ = (
        UniqueConstraint('env', 'name', 'deleted_at'),
    )

    name = Column(String(64), nullable=False, comment="数据集名称")
    env = Column(INT, nullable=False, comment="所属环境id")
    project_id = Column(INT, index=True, comment="所属项目id, 可为空")
    database_id = Column(INT, index=True, comment="目标库配置id, 对应 pity_database_info.id")
    table_name = Column(String(64), comment="目标表名")
    columns = Column(TEXT, nullable=False, comment="字段生成规则JSON")
    count = Column(INT, default=10, comment="默认生成条数")
    seed = Column(INT, default=0, comment="随机种子, 0表示每次随机")
    remark = Column(String(255), comment="备注")
    status = Column(INT, default=1, comment="1: 启用 0: 禁用")

    __tag__ = "数据工厂"
    __fields__ = (name, env)
    __show__ = 2
    __alias__ = dict(name="数据集名称", env="环境", project_id="项目", database_id="目标库",
                     table_name="目标表", count="生成条数", seed="随机种子",
                     remark="备注", status="状态")

    def __init__(self, name, env, columns, user, project_id=None, database_id=None,
                 table_name=None, count=10, seed=0, remark="", status=1, id=None):
        super().__init__(user, id)
        self.name = name
        self.env = env
        self.project_id = project_id
        self.database_id = database_id
        self.table_name = table_name
        self.columns = columns
        self.count = count
        self.seed = seed
        self.remark = remark
        self.status = status

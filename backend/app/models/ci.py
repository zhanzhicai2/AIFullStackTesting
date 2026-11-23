"""
持续集成(CI)的两张表

- `pity_ci_integration`  项目级接入凭据(外部流水线调平台用的长期凭据)
- `pity_ci_run`          一次外部触发的完整生命周期(执行标识 + 结果 + 外部构建号)

**凭据不存明文(spec FR-008 / GATE-SEC)**: 只存 `sha256(明文)` 等值摘要 + 可辨识前缀。
明文只在签发响应里出现一次, 此后任何读路径都拿不到。

**不可重放声明(constitution 原则 I 豁免条款)**:
`token` 由 `secrets.token_hex(16)` 生成(CSPRNG, 128 bit 熵), **MUST NOT 可重放** ——
这是安全属性而非缺陷: 可重放的凭据等于可预测的凭据。除本字段外, 本特性不引入任何
随机源; 通过/未通过判定是纯函数(见 `app/core/ci_runner.py`)。

**不改动的既有表**: `pity_test_plan`(只读消费其 `state` 做防重)、`pity_report` /
`pity_test_result`(只引用入口)、`pity_project`(只按 project_id 归属)。
"""
from sqlalchemy import BOOLEAN, Column, Index, INT, SMALLINT, String, TEXT, TIMESTAMP, UniqueConstraint

from app.models.basic import PityBase


class PityCiIntegration(PityBase):
    """接入凭据 —— 作用域 = project_id(FR-005 越权边界)"""

    __tablename__ = "pity_ci_integration"

    project_id = Column(INT, index=True, nullable=False, comment="归属项目, 凭据作用域边界")
    name = Column(String(32), nullable=False, comment="集成名, 如 Jenkins-main")
    # sha256(明文) 十六进制小写 64 字符; **绝不存明文**
    token_hash = Column(String(64), nullable=False, unique=True, comment="凭据摘要(sha256), 非明文")
    # 明文前 12 位, 仅供列表辨识与排障; **校验不使用它**
    token_prefix = Column(String(12), nullable=False, index=True, comment="凭据前缀, 仅展示")
    plan_id = Column(INT, index=True, comment="绑定的默认测试计划; 为空则调用方必须显式指定")
    # 一期只存不发(决定 Q5): 任何代码路径都不读它发送, ci_selftest 静态扫描保证
    callback_url = Column(String(255), comment="二期回调地址, 一期只存不发")
    enabled = Column(BOOLEAN, nullable=False, default=True, comment="停用即吊销, 立即生效")
    expires_at = Column(TIMESTAMP, comment="为空=长期有效(决定 Q4); 默认签发时写 now+1年")
    last_used_at = Column(TIMESTAMP, comment="最近一次校验通过的时间")

    __tag__ = "CI集成"
    __fields__ = (name, project_id, plan_id)
    __show__ = 3
    __alias__ = dict(name="集成名", project_id="所属项目", plan_id="默认计划",
                     enabled="状态", expires_at="有效期", last_used_at="最后使用",
                     callback_url="回调地址")

    __table_args__ = (
        # 同项目下集成名不重复, 便于排查(与 pity_test_plan 同款)
        UniqueConstraint("project_id", "name", "deleted_at", name="uq_ci_integration_project_name"),
    )

    def __init__(self, project_id, name, token_hash, token_prefix, user, plan_id=None,
                 callback_url=None, enabled=True, expires_at=None, id=None):
        super().__init__(user, id)
        self.project_id = project_id
        self.name = name
        self.token_hash = token_hash
        self.token_prefix = token_prefix
        self.plan_id = plan_id
        self.callback_url = callback_url
        self.enabled = enabled
        self.expires_at = expires_at
        self.last_used_at = None


class PityCiRun(PityBase):
    """一次外部触发 —— `id` 即 FR-012 的「唯一可查询的执行标识」"""

    __tablename__ = "pity_ci_run"

    integration_id = Column(INT, index=True, nullable=False, comment="触发所用的集成配置")
    project_id = Column(INT, index=True, nullable=False, comment="冗余自集成配置, 供分页免 join")
    plan_id = Column(INT, index=True, nullable=False, comment="实际执行的测试计划")
    env = Column(String(64), nullable=False, comment="实际执行的环境 id 列表(逗号分隔)")
    external_build_id = Column(String(64), comment="调用方传入的外部构建号(如 Jenkins BUILD_NUMBER)")
    external_url = Column(String(255), comment="调用方传入的流水线地址, 历史中可跳转")
    status = Column(SMALLINT, nullable=False, default=0, index=True,
                    comment="0 pending 1 running 2 success 3 failed 4 timeout 5 error")
    report_ids = Column(TEXT, comment="本次产生的 pity_report.id 列表(JSON 数组字符串)")
    success_count = Column(INT, nullable=False, default=0, comment="通过用例数")
    failed_count = Column(INT, nullable=False, default=0, comment="失败用例数")
    error_count = Column(INT, nullable=False, default=0, comment="异常用例数")
    skipped_count = Column(INT, nullable=False, default=0, comment="跳过用例数")
    pass_rate = Column(SMALLINT, nullable=False, default=0, comment="通过率(整数百分比); total=0 时保持 0")
    error_msg = Column(String(500), comment="status=5 时的失败原因, 已脱敏且截断到 500")
    started_at = Column(TIMESTAMP, comment="开始执行时间")
    finished_at = Column(TIMESTAMP, comment="结束时间")
    cost = Column(String(8), comment="耗时秒数, 格式与 pity_report.cost 一致(%.2f)")
    waited = Column(BOOLEAN, nullable=False, default=False, comment="本次触发是否使用等待语义(FR-010)")

    __tag__ = "CI触发记录"
    __fields__ = (plan_id, project_id, status)
    __show__ = 3
    __alias__ = dict(plan_id="测试计划", project_id="所属项目", status="结果",
                     external_build_id="外部构建号", env="环境", cost="耗时",
                     pass_rate="通过率", waited="等待语义")

    # 复合索引: 触发历史按「项目 + 时间」分页是主查询路径(FR-022 / SC-009);
    # 单列索引只覆盖 project_id, 加上 created_at 才能让 ORDER BY created_at DESC 走索引
    __table_args__ = (
        Index("idx_ci_run_project_created", "project_id", "created_at"),
    )

    def __init__(self, integration_id, project_id, plan_id, env, user, status=0,
                 external_build_id=None, external_url=None, waited=False, id=None):
        super().__init__(user, id)
        self.integration_id = integration_id
        self.project_id = project_id
        self.plan_id = plan_id
        self.env = env
        self.status = status
        self.external_build_id = external_build_id
        self.external_url = external_url
        self.waited = waited
        self.report_ids = None
        self.success_count = 0
        self.failed_count = 0
        self.error_count = 0
        self.skipped_count = 0
        self.pass_rate = 0
        self.error_msg = None
        self.started_at = None
        self.finished_at = None
        self.cost = None

"""
AI 工作台的四张新表

- pity_ai_draft_batch   生成批次(一次生成任务)
- pity_ai_case_draft    用例草稿(待审核 → 已采纳 / 已驳回)
- pity_ai_invoke_log    模型调用流水(每次调用一行)
- pity_ai_analysis      分析结论(**每次分析一行, 永不覆盖**)

**为什么必须建表**(对比数据工厂的"不建批次表"):
数据工厂的产物由 `rules + seed` 唯一确定, 可重放, 所以不建表。
本功能的产物来自**模型输出, 不可重放**(constitution 原则 I), 因此必须落库固定。

⚠️ **不可重放声明(constitution 原则 I)**:
`pity_ai_case_draft.content` 由模型生成 —— 同一份需求输入, 两次生成得到的草稿不同,
这是 AI 的本质, 无法通过工程手段消除。确定性的锚点是草稿的**当前 content 版本**:
- 重复采纳同一版本 → 结果逐字段相等 ✅(可重放)
- 重新生成 → 产生新批次的新草稿, 旧草稿保留供对比 ❌(不可重放)

草稿一旦落库, `content` 即为不可变快照; `status != 1`(已采纳/已驳回)时内容冻结。
"""
from sqlalchemy import Column, FLOAT, INT, String, TEXT, UniqueConstraint

from app.models.basic import PityBase


class PityAIDraftBatch(PityBase):
    """
    生成批次 —— 这次生成任务是什么、用了哪个模型、花了多少

    生命周期: 任务完成后长期留存, 可归档(3已归档)。
    """

    __tablename__ = "pity_ai_draft_batch"

    title = Column(String(64), nullable=False, comment="任务标题")
    project_id = Column(INT, index=True, comment="所属项目id")
    directory_id = Column(INT, comment="采纳目标目录id")
    vendor_id = Column(INT, comment="使用的厂商id")
    # 模型名是**快照** —— 厂商配置改了也不影响历史批次的可追溯性
    model_name = Column(String(128), comment="使用的模型名(快照)")
    test_type = Column(String(16), default="api", comment="api / web / manual / mobile")
    source_type = Column(String(16), comment="text / document")
    source_name = Column(String(128), comment="文档名, 文本输入时为空")
    source_chars = Column(INT, default=0, comment="实际送入模型的字符数(截断后)")
    status = Column(INT, default=1, comment="1生成中 / 2已完成 / 3已归档")
    case_count = Column(INT, default=0, comment="草稿数量")
    total_tokens = Column(INT, default=0, comment="本批消耗token")
    warnings = Column(TEXT, comment="JSON数组: 截断提示、解析告警、校验告警汇总")

    __tag__ = "AI生成批次"
    __fields__ = (title, model_name, status)
    __show__ = 2
    __alias__ = dict(title="任务标题", project_id="所属项目", directory_id="目标目录",
                     vendor_id="厂商", model_name="模型", test_type="测试类型",
                     source_type="来源类型", source_name="文档名", source_chars="输入字符数",
                     status="状态", case_count="草稿数", total_tokens="消耗token")

    def __init__(self, title, user, project_id=None, directory_id=None, vendor_id=None,
                 model_name=None, test_type="api", source_type=None, source_name=None,
                 source_chars=0, status=1, case_count=0, total_tokens=0, warnings=None, id=None):
        super().__init__(user, id)
        self.title = title
        self.project_id = project_id
        self.directory_id = directory_id
        self.vendor_id = vendor_id
        self.model_name = model_name
        self.test_type = test_type
        self.source_type = source_type
        self.source_name = source_name
        self.source_chars = source_chars
        self.status = status
        self.case_count = case_count
        self.total_tokens = total_tokens
        self.warnings = warnings


class PityAICaseDraft(PityBase):
    """
    用例草稿 —— AI 的产物先进这里, 人工审核后才写业务表

    **不可重放声明(constitution 原则 I)**:
    `content` 由模型生成, **同一份需求两次生成结果不同**。
    确定性的锚点是草稿的**当前 content 版本**:
    - 重复采纳同一版本 → 写入完全相同的用例(逐字段相等)
    - 重新生成 → 产生新批次的新草稿, 旧草稿保留供对比

    状态流转:
        生成成功 → (1待审核) → 批量采纳 → (2已采纳)
                              → 批量驳回 → (3已驳回, 终态)
    `status != 1` 时 `content` 冻结, 不再接受修改; `status = 2` 时 `case_id` 必非空。
    """

    __tablename__ = "pity_ai_case_draft"

    batch_id = Column(INT, index=True, nullable=False, comment="所属批次id")
    code = Column(String(32), comment="用例编码, 如 AUTO-001(批次内序号)")
    title = Column(String(64), nullable=False, comment="用例标题")
    category = Column(String(32), default="正向流程", comment="类别")
    priority = Column(String(3), default="P1", comment="P0-P4")
    status = Column(INT, default=1, comment="1待审核 / 2已采纳 / 3已驳回")
    steps = Column(INT, default=1, comment="步骤数")
    # content 是完整 DSL JSON —— **唯一真源**, 草稿详情展示的与用户能改的都是它
    content = Column(TEXT, nullable=False, comment="完整DSL JSON")
    case_id = Column(INT, comment="采纳后回填 pity_testcase.id")
    warn = Column(TEXT, comment="JSON数组: 本条的校验告警")
    order = Column(INT, default=0, comment="批次内排序")

    __table_args__ = (
        UniqueConstraint('batch_id', 'code', 'deleted_at'),
    )

    __tag__ = "AI用例草稿"
    __fields__ = (title, code, priority, status)
    __show__ = 2
    __alias__ = dict(title="用例标题", code="编码", batch_id="所属批次", category="类别",
                     priority="优先级", status="状态", steps="步骤数", case_id="正式用例id")

    def __init__(self, title, user, batch_id, content, code=None, category="正向流程",
                 priority="P1", status=1, steps=1, case_id=None, warn=None, order=0, id=None):
        super().__init__(user, id)
        self.batch_id = batch_id
        self.code = code
        self.title = title
        self.category = category
        self.priority = priority
        self.status = status
        self.steps = steps
        self.content = content
        self.case_id = case_id
        self.warn = warn
        self.order = order


class PityAIInvokeLog(PityBase):
    """
    模型调用流水 —— 谁在什么时候用什么模型调了 AI、花了多少、成没成

    用途(spec FR-015):
    1. 成本核算 —— 按场景/用户/模型统计 token 与耗时
    2. 效果评测 —— 按 `scene` 聚合, 比较不同模型在同一场景下的表现
    3. 故障定位 —— 区分"模型返回了但解析失败"与"调用本身失败"

    ⚠️ `error_msg` **不得含 API Key**, 也不得含完整 prompt 正文
    (prompt 里可能含需求文档正文, 属敏感数据)。
    """

    __tablename__ = "pity_ai_invoke_log"

    scene = Column(String(32), index=True, comment="case_gen / bug / log / sql")
    user_id = Column(INT, index=True, comment="调用人id")
    vendor_id = Column(INT, comment="厂商id")
    model_name = Column(String(128), comment="模型名")
    prompt_chars = Column(INT, comment="prompt字符数")
    tokens = Column(INT, comment="token用量, 厂商未返回时为0")
    elapsed = Column(FLOAT, comment="耗时(秒)")
    status = Column(String(16), comment="success / failed")
    error_msg = Column(TEXT, comment="失败原因(已脱敏)")

    __tag__ = "AI调用流水"
    __fields__ = (scene, model_name, status)
    __show__ = 2
    __alias__ = dict(scene="场景", user_id="调用人", vendor_id="厂商", model_name="模型",
                     prompt_chars="prompt字符数", tokens="token", elapsed="耗时",
                     status="状态", error_msg="错误信息")

    def __init__(self, user, scene, model_name=None, user_id=None, vendor_id=None,
                 prompt_chars=0, tokens=0, elapsed=0.0, status="success", error_msg="", id=None):
        super().__init__(user, id)
        self.scene = scene
        self.user_id = user_id
        self.vendor_id = vendor_id
        self.model_name = model_name
        self.prompt_chars = prompt_chars
        self.tokens = tokens
        self.elapsed = elapsed
        self.status = status
        self.error_msg = error_msg


class PityAIAnalysis(PityBase):
    """
    分析结论 —— Bug 分析 / 日志归因 / SQL 分析 共用

    **每次分析一行, 永不覆盖**(research.md §3.8):
    覆盖式更新(只留最新)会让"同一失败反复出现但根因结论在变"这一重要信号消失 ——
    而那恰恰是最值得看的现象。
    """

    __tablename__ = "pity_ai_analysis"

    scene = Column(String(16), index=True, comment="bug / log / sql")
    title = Column(String(128), comment="标题(用例名 / 错误簇指纹 / SQL摘要)")
    project_id = Column(INT, index=True, comment="所属项目id")
    ref_type = Column(String(32), comment="result / log_cluster / sql_history / manual")
    ref_id = Column(INT, comment="关联对象id, manual时为0")
    result = Column(TEXT, comment="结构化结论JSON")
    vendor_id = Column(INT, comment="厂商id")
    model_name = Column(String(128), comment="模型名")
    tokens = Column(INT, comment="token用量")

    __tag__ = "AI分析结论"
    __fields__ = (title, scene, ref_type)
    __show__ = 2
    __alias__ = dict(title="标题", scene="场景", project_id="所属项目", ref_type="关联类型",
                     ref_id="关联id", vendor_id="厂商", model_name="模型", tokens="token")

    def __init__(self, title, user, scene, result, project_id=None, ref_type="manual",
                 ref_id=0, vendor_id=None, model_name=None, tokens=0, id=None):
        super().__init__(user, id)
        self.title = title
        self.scene = scene
        self.project_id = project_id
        self.ref_type = ref_type
        self.ref_id = ref_id
        self.result = result
        self.vendor_id = vendor_id
        self.model_name = model_name
        self.tokens = tokens

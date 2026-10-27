"""
UI 自动化子系统的六张表

- pity_ui_page            页面树(元素引用的键是「页面名」)
- pity_ui_element         元素 = 一条定位策略(元素引用的键是「页面名.元素名」)
- pity_ui_case            UI 用例专有数据(主体在既有的 pity_testcase)
- pity_ui_node            执行节点(v1 只有内置本地节点)
- pity_ui_import_log      录制导入留痕
- pity_ui_allowed_domain  SSRF 白名单(按项目, 为空 = 不可执行)

**不可重放声明(constitution 原则 I)**:
`pity_ui_case.steps`(步骤定义)完全确定 —— 同一份 steps 永远产生同一串浏览器操作序列。
但 **UI 用例的执行结果不可重放** —— 页面内容与断言成败取决于被测系统当时的状态,
不在平台可控范围内。平台自身 MUST NOT 引入任何随机源(无隐式 sleep、无随机退避、
无随机挑选匹配元素),详见 app/core/ui_executor.py 与 specs/002-ui-automation/contracts/steps.md。
"""
from sqlalchemy import BOOLEAN, Column, INT, String, TEXT, UniqueConstraint

from app.models.basic import PityBase


class PityUIPage(PityBase):
    """页面树 —— 同一项目同层级下页面名不重复"""

    __tablename__ = "pity_ui_page"

    project_id = Column(INT, index=True, nullable=False, comment="所属项目id")
    name = Column(String(64), nullable=False, comment="页面名, 元素引用的键就是它")
    url = Column(String(256), comment="页面地址")
    parent = Column(INT, comment="上级页面id, 顶级为None")
    description = Column(String(255), comment="描述")

    # parent 为 None 时 MySQL 的唯一约束对 NULL 不生效(NULL != NULL),
    # 所以顶层页面的重名由 DAO 层显式校验
    __table_args__ = (
        UniqueConstraint('project_id', 'name', 'parent', 'deleted_at'),
    )

    __tag__ = "UI页面"
    __fields__ = (name, url)
    __show__ = 2
    __alias__ = dict(name="页面名", url="页面地址", parent="上级页面",
                     project_id="所属项目", description="描述")

    def __init__(self, name, user, project_id, url=None, parent=None, description="", id=None):
        super().__init__(user, id)
        self.name = name
        self.project_id = project_id
        self.url = url
        self.parent = parent
        self.description = description


class PityUIElement(PityBase):
    """元素 = 一条定位策略 —— 同页面同策略同定位值同 name_attr 视为同一元素"""

    __tablename__ = "pity_ui_element"

    project_id = Column(INT, index=True, nullable=False, comment="所属项目id")
    page_id = Column(INT, index=True, nullable=False, comment="所属页面id")
    name = Column(String(64), nullable=False, comment="元素名, 引用键「页面名.元素名」的后半段")
    strategy = Column(String(16), nullable=False, comment="定位策略, 见 app/core/ui_executor.py 的 STRATEGIES")
    locator = Column(String(256), nullable=False, comment="定位值")
    name_attr = Column(String(64), comment="strategy=role 时的 accessible name")
    description = Column(String(255), comment="描述")
    status = Column(INT, default=1, comment="1: 启用 0: 停用")

    # name_attr 可空时 MySQL 唯一约束同样对 NULL 失效, 去重由 DAO 层显式校验
    __table_args__ = (
        UniqueConstraint('project_id', 'page_id', 'strategy', 'locator', 'name_attr', 'deleted_at'),
    )

    __tag__ = "UI元素"
    __fields__ = (name, strategy, locator)
    __show__ = 3
    __alias__ = dict(name="元素名", strategy="定位策略", locator="定位值",
                     name_attr="可访问名称", page_id="所属页面", project_id="所属项目",
                     description="描述", status="状态")

    def __init__(self, name, strategy, locator, user, project_id, page_id, name_attr=None,
                 description="", status=1, id=None):
        super().__init__(user, id)
        self.name = name
        self.strategy = strategy
        self.locator = locator
        self.project_id = project_id
        self.page_id = page_id
        self.name_attr = name_attr
        self.description = description
        self.status = status


class PityUICase(PityBase):
    """
    UI 用例专有数据

    **执行结果不可重放** —— 步骤定义完全确定, 但页面内容与断言成败取决于被测系统。
    详见模块 docstring 与 app/core/ui_executor.py 的说明。
    """

    __tablename__ = "pity_ui_case"

    case_id = Column(INT, index=True, nullable=False, comment="关联 pity_testcase.id")
    base_url = Column(String(256), nullable=False, comment="起始地址, 支持 ${变量}")
    viewport = Column(String(16), default="1280x720", comment="视口, 形如 1280x720")
    # 浏览器区域设置 —— 必须钉死: 同一个 URL 在不同 Accept-Language 下返回的内容不同,
    # 不固定 locale 就谈不上「同样的输入产出完全一致的结果」(constitution 原则 I)
    locale = Column(String(16), default="en-US", comment="浏览器区域设置, 如 en-US / zh-CN")
    browser = Column(String(16), default="chromium", comment="浏览器类型")
    timeout = Column(INT, default=30, comment="单步超时(秒)")
    steps = Column(TEXT, nullable=False, comment="步骤 DSL JSON, 见 contracts/steps.md")
    screenshot = Column(BOOLEAN, default=True, comment="失败是否自动截图")

    __table_args__ = (
        UniqueConstraint('case_id', 'deleted_at'),
    )

    __tag__ = "UI用例"
    __fields__ = (base_url, viewport, timeout)
    __show__ = 2
    __alias__ = dict(base_url="起始地址", viewport="视口", browser="浏览器",
                     timeout="单步超时", screenshot="失败截图", case_id="用例id")

    def __init__(self, case_id, base_url, steps, user, viewport="1280x720", browser="chromium",
                 timeout=30, screenshot=True, locale="en-US", id=None):
        super().__init__(user, id)
        self.case_id = case_id
        self.base_url = base_url
        self.viewport = viewport
        self.locale = locale
        self.browser = browser
        self.timeout = timeout
        self.steps = steps
        self.screenshot = screenshot


class PityUINode(PityBase):
    """执行节点 —— v1 只有内置本地节点, 分布式节点是 v2"""

    __tablename__ = "pity_ui_node"

    name = Column(String(64), nullable=False, comment="节点名")
    node_type = Column(String(16), default="local", comment="local / remote(v2预留)")
    status = Column(INT, default=1, comment="1: 在线 0: 离线")
    browser = Column(String(16), default="chromium", comment="浏览器类型")
    headless = Column(BOOLEAN, default=True, comment="无头模式")
    max_concurrency = Column(INT, default=2, comment="并发上限")
    version = Column(String(32), comment="节点版本标识")

    __tag__ = "UI执行节点"
    __fields__ = (name, node_type, status)
    __show__ = 2
    __alias__ = dict(name="节点名", node_type="节点类型", status="状态",
                     browser="浏览器", headless="无头模式",
                     max_concurrency="并发上限", version="版本")

    def __init__(self, name, user, node_type="local", status=1, browser="chromium",
                 headless=True, max_concurrency=2, version=None, id=None):
        super().__init__(user, id)
        self.name = name
        self.node_type = node_type
        self.status = status
        self.browser = browser
        self.headless = headless
        self.max_concurrency = max_concurrency
        self.version = version


class PityUIImportLog(PityBase):
    """录制导入记录 —— 留痕用, 记录产出与跳过"""

    __tablename__ = "pity_ui_import_log"

    project_id = Column(INT, index=True, comment="所属项目id")
    source = Column(String(16), default="codegen", comment="codegen / manual(预留)")
    raw_len = Column(INT, comment="原始脚本长度")
    parsed_lines = Column(INT, default=0, comment="解析成功的行数")
    skipped_lines = Column(INT, default=0, comment="被跳过的行数")
    page_count = Column(INT, default=0, comment="产出的页面数")
    element_count = Column(INT, default=0, comment="产出的元素数")
    case_count = Column(INT, default=0, comment="产出的用例数")
    batch_id = Column(INT, comment="关联的生成批次(走 001 的草稿机制时)")
    status = Column(INT, default=1, comment="1: 成功 2: 部分成功 3: 失败")
    message = Column(TEXT, comment="说明, 尤其记录哪些行没解析出来")

    __tag__ = "UI录制导入"
    __fields__ = (source, status)
    __show__ = 2
    __alias__ = dict(source="来源", project_id="所属项目", parsed_lines="解析行数",
                     skipped_lines="跳过行数", page_count="页面数", element_count="元素数",
                     case_count="用例数", status="状态")

    def __init__(self, user, project_id=None, source="codegen", raw_len=0, parsed_lines=0,
                 skipped_lines=0, page_count=0, element_count=0, case_count=0,
                 batch_id=None, status=1, message="", id=None):
        super().__init__(user, id)
        self.project_id = project_id
        self.source = source
        self.raw_len = raw_len
        self.parsed_lines = parsed_lines
        self.skipped_lines = skipped_lines
        self.page_count = page_count
        self.element_count = element_count
        self.case_count = case_count
        self.batch_id = batch_id
        self.status = status
        self.message = message


class PityUIAllowedDomain(PityBase):
    """
    SSRF 白名单(按项目)

    **语义**: 白名单为空 → 该项目的 UI 用例**不可执行**(不是"允许全部")。
    这是刻意选的失败方向 —— 宁可跑不了, 也不能让平台裸奔到内网。
    """

    __tablename__ = "pity_ui_allowed_domain"

    project_id = Column(INT, index=True, nullable=False, comment="所属项目id")
    domain = Column(String(128), nullable=False, comment="允许的裸域名, 不含协议与路径")
    env = Column(INT, comment="生效环境, None 表示所有环境")

    # env 为 None 时 MySQL 唯一约束对 NULL 失效, 去重由 DAO 层显式校验
    __table_args__ = (
        UniqueConstraint('project_id', 'domain', 'env', 'deleted_at'),
    )

    __tag__ = "UI允许域名"
    __fields__ = (domain, env)
    __show__ = 2
    __alias__ = dict(domain="域名", env="生效环境", project_id="所属项目")

    def __init__(self, domain, user, project_id, env=None, id=None):
        super().__init__(user, id)
        self.domain = domain
        self.project_id = project_id
        self.env = env

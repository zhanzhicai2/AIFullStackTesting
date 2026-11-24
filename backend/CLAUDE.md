# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 启动命令

```bash
# 一次性创建 venv(首次)
uv venv --python 3.10
source .venv/bin/activate

# 启动后端服务（主流本机方式;由 pity.py 调 uvicorn.run("main:pity")）
uv pip install -r requirements.txt    # 首次或依赖变更后
python pity.py

# 开发模式热重载（代码改动自动重启;与 python pity.py 二选一）
uvicorn main:pity --reload

# Alembic 迁移
alembic revision --autogenerate -m "描述"          # 生成数据库迁移
alembic upgrade head                              # 执行迁移
```

环境变量 `pity_env=dev`（默认）读 `conf/dev.env`，`pity_env=pro` 读 `conf/pro.env`。

**Python 环境**：用 `uv venv` 创建独立虚拟环境（`backend/.venv/`），不要用 conda，详见 [`DEV_SETUP.md`](./DEV_SETUP.md)。首个注册用户自动成为超管。

## 项目结构

```
backend/
├── main.py                 # 模块定义：路由注册 + startup 钩子 + WebSocket 端点（被 pity.py 加载）
├── pity.py                 # 启动器：uvicorn.run("main:pity", host=Config.SERVER_HOST, port=Config.SERVER_PORT)
├── config.py               # 配置类（BaseConfig + DevConfig/ProConfig）
├── proxy.py                # mitmproxy 启动入口（PROXY_ON=True 时由 main.py 调用）
├── alembic.ini             # Alembic 迁移配置
├── requirements.txt        # Python 依赖
├── conf/                   # 环境配置
│   ├── dev.env             # 开发环境（MySQL、Redis、OAuth 等）
│   └── pro.env             # 生产环境
├── pity_proxy/             # mitmproxy 录制 / Mock 服务模块（PROXY_ON / MOCK_ON 开关）
│   ├── mock.py             # PityMock：内置 Mock 服务（main.py 在 MOCK_ON=True 时启动）
│   └── record.py           # PityRecorder：HAR / mitmproxy 用例录制（PROXY_ON=True 时启动）
├── app/
│   ├── routers/            # API 路由（按模块目录组织）
│   │   ├── auth/           # 认证（注册、登录、GitHub OAuth）
│   │   ├── project/        # 项目管理
│   │   ├── testcase/       # 测试用例
│   │   ├── config/         # 配置管理
│   │   ├── online/         # 在线工具（SQL、Redis）
│   │   ├── workspace/      # 工作空间
│   │   ├── oss/            # 对象存储
│   │   ├── notification/   # 消息通知
│   │   ├── operation/      # 操作日志
│   │   ├── request/        # HTTP 请求 / Mock 录制
│   │   └── ui/             # UI 自动化（页面/元素/用例/白名单/节点，前缀 /ui）
│   ├── models/             # SQLAlchemy 数据模型（继承 PityBase）
│   ├── crud/               # DAO 层（@ModelWrapper + @connect 模式）
│   ├── schema/             # Pydantic v1 验证模型（注意不是 schemas）
│   ├── core/               # 核心业务逻辑（用例执行引擎、参数解析）
│   ├── middleware/          # 中间件（CORS、错误处理、请求日志）
│   ├── utils/              # 工具函数（JWT、Redis、通知等）
│   ├── enums/              # 枚举类型
│   ├── exception/          # 自定义异常
│   └── handler/            # 处理器
├── statics/                # 前端构建产物（生产部署）
├── templates/              # HTML 模板（测试报告）
├── logs/                   # 日志文件
└── alembic/                # 数据库迁移脚本
```

## 架构概览

应用入口 `main.py` 注册路由并启动 Redis、APScheduler 定时任务、数据库自动建表三个 startup 事件。

### 请求处理链

```
Request → CORS Middleware → Error Middleware → Router → DAO (connect装饰器管理session) → Response
```

### 数据库层

- **Model**：所有模型继承 `PityBase`（`app/models/basic.py`），自动提供 `id`、`created_at`、`updated_at`、`deleted_at`（软删除，BIGINT 时间戳）、`create_user`、`update_user`
- **DAO**：`app/crud/__init__.py` 中的 `Mapper` 基类提供通用 CRUD，子类通过 `@ModelWrapper(Model)` 装饰器绑定模型
- **Session 管理**：`@connect` 装饰器自动获取/复用 `AsyncSession`，支持事务参数 `@connect(True)`
- **缓存**：`@RedisHelper.cache("dao")` 自动缓存查询结果，`@RedisHelper.up_cache("dao")` 写操作后自动清缓存

### 路由层

- 路由按模块组织在 `app/routers/` 下，每个模块的 `__init__.py` 汇聚子路由导出 `router`
- 认证：`Depends(Permission())` 从 `Authorization` Header 解析 JWT，`Permission(role=Config.ADMIN)` 可限定角色
- 响应统一通过 `PityResponse.success()` / `PityResponse.failed()` 返回 `{code, msg, data}` 格式

### 测试用例执行引擎

`app/core/executor.py` 是核心执行器，支持 5 种构造器类型（映射在 `construct_type` 字典中）：
- **HTTP** — `HttpConstructor`：发送 HTTP 请求
- **SQL** — `SqlConstructor`：执行数据库查询
- **Redis** — `RedisConstructor`：执行 Redis 命令
- **Python 脚本** — `PythonConstructor`：执行自定义 Python
- **测试用例** — `TestcaseConstructor`：嵌套调用其他用例

参数提取通过 `app/core/paramters/` 下的解析器（JSONPath、正则、状态码、KV）实现，全局配置解析通过 `app/utils/gconfig_parser.py`（String/JSON/YAML）。

### 数据工厂（`app/core/data_factory/`）

造数工厂：**字段规则 → 批量生成 → 导出 / 写库 / 绑定用例跑数据驱动**。AI 只做「自然语言 → 字段规则」翻译，数据由确定性内核生成，同 rules + seed 可重放。

改这里前必须知道：

- **不要改 `pity_testcase_data` 的表结构** —— `bind_case` 写这张表来接入数据驱动，执行引擎的 `Executor.run_single` 会按 `(env, case_id)` 取数并把 `json_data` 注入用例变量
- **`rule.kind` 常量前后端两处同步** —— 后端 `app/core/data_factory/generator.py`、前端 `frontend/src/consts/datafactory.ts`，改一处必须同时改另一处
- **AsyncEngine 不能直接 reflection**，必须走 `conn.run_sync()` 绿桥（与 `DbConfigDao.load_table` 同款）

模块拆分、字段规则 JSON 规范（11 种 `rule.kind` 参数表）、设计取舍、回归脚本跑法、已知缺口 → 见 [`docs/data-factory-design.md`](docs/data-factory-design.md)。

### AI 工作台（Phase 1~6 已实现：US1~US4 全部落地）

四个 AI 场景（用例生成 / Bug 分析 / 日志分析 / SQL 分析）共用一层公共能力。核心约定：

- **AI 只做翻译与解读，落地由确定性内核做** —— 与数据工厂同源原则。AI 产物先进草稿态（`pity_ai_case_draft`），人工审核后才写业务表
- **用例生成有 14 条硬校验**，其中最致命的两条：断言 `actually` 引用的 `${变量}` 必须在 `out_parameters` 里存在，否则断言取不到值、**静默失败**（`Executor.my_assert` 的取值只来自 `extract_out_parameters`）；Web UI 步骤引用的元素必须存在于元素库且启用，否则**采纳时被拦下**（草稿不进用例库）
- **规则 8 / 13 的处置是「保留 + 告警 + 采纳时拦截」**，不是"丢弃字段" —— 契约表格写"丢弃"，但 spec FR-012 / FR-039 要求"采纳前拦下"，丢掉了就看不出草稿还有问题
- **模型输出不可重放** —— 同一份输入两次生成结果不同。确定性的锚点是草稿**当前 content 版本**：重复采纳同一版本结果一致；重新生成产生新草稿，旧草稿保留
- **断言类型白名单的权威定义在后端** `app/enums/AIWorkbenchEnum.py`（前端 `src/consts/config.ts` 镜像），DSL 常量在 `app/core/ai_prompts/case_gen.py` 与 `src/consts/aiWorkbench.ts` —— **改一处必须同时改另一处**
- **日志分析先聚类再解读** —— 归一化 + fingerprint 分组是纯 Python，AI 只解读 Top-N 簇；突增检测完全不需要 AI；**`/ai/log/cluster` 不产生任何模型调用记录**
- **SQL 分析禁用 `EXPLAIN ANALYZE`** —— MySQL 8.0.18+ 会真实执行查询，对 UPDATE/DELETE 直接改数据，只能用普通 `EXPLAIN`；拦截在 **SQL 解析层**（`app/utils/sql_guard.py`），不依赖模型自觉
- **UI 步骤动作白名单不在 001 里另写一份** —— 规则 11~13 直接复用 `app/core/ui_executor.py` 的 `validate_steps`（元素引用语义以 002 契约为准）
- **不引入新的 `exec()` 执行面** —— 录制脚本是静态解析，改写 SQL 只做"基本合法"检查（不会拿它执行），`Render` 仍是既有的裸 `Environment()`

公共层 `app/core/ai_service.py`（统一厂商/模型解析 + 调用埋点 + JSON 提取）、4 张新表、API 清单、前后端契约 → 见 [`docs/ai-workbench-design.md`](docs/ai-workbench-design.md)。

**已落地（T001~T057 + 横切）**：

| 位置 | 内容 |
|---|---|
| `app/enums/AIWorkbenchEnum.py` | **跨端常量的后端权威定义**（断言白名单 14 种 / 优先级 / 类别 / 测试类型 / 场景 / 草稿与批次状态） |
| `app/core/ai_service.py` | `resolve_model` / `invoke`（调用流水埋点 + 解析失败纠错重试，parser 支持 async）/ `extract_json` |
| `app/core/ai_prompts/base.py` | 外部文本标签包裹 + 注入声明 + 头尾截断（文档 20MB / 日志 10MB） |
| `app/core/ai_prompts/case_gen.py` | **14 条校验规则的正反例都在 `scripts/ai_workbench_selftest.py` 里**；DSL → 四表映射 + 采纳前两道拦截 |
| `app/core/ai_prompts/clustering.py` | 日志聚类（**纯 Python，不调模型**）：归一化 → 指纹分组 + p95 突增检测（线性插值） |
| `app/core/ai_prompts/bug.py` · `log.py` · `sql.py` | 三个场景的提示词 + evidence 子串校验 + history 判定 |
| `app/utils/sql_guard.py` | **`EXPLAIN ANALYZE` 硬拦** + 表名提取 |
| `app/models/ai_draft.py` · `app/crud/ai/` 五个 DAO · `app/schema/ai_workbench.py` | 四张新表、DAO（含采纳落库）、表单 |
| `app/utils/document_parser.py` | 文档解析（PDF/Word/MD/TXT 白名单 + 20MB 上限 + 降级纯文本） |
| `app/routers/ai/case_gen.py` · `bug.py` · `log.py` · `sql.py` · `invoke_log.py` | **13 个新端点**（case/draft/generate/document/bug/log cluster/analyze/sql analyze/slow/invoke log） |
| `scripts/ai_workbench_selftest.py` | 自测（**不依赖数据库**，184 项断言） |
| `scripts/ai_workbench_smoke.py` | DAO 冒烟（**需要数据库**，20 项断言） |
| `scripts/ai_workbench_e2e.py` | US1~US4 端到端（**需要数据库**，102 项断言，直接调路由函数 + 假模型桩） |
| `app/core/ai_client.py` | 新增 `complete_chat_with_usage()`（`complete_chat` 行为不变） |
| `app/routers/datafactory/dataset.py` · `app/routers/ai/chat.py` | 厂商/模型解析改调 `ai_service.resolve_model()`（消除两处重复） |

**改这里前必须知道**：
- **断言类型白名单的权威定义在 `app/enums/AIWorkbenchEnum.py`**，前端镜像 `src/consts/aiWorkbench.ts`（`src/consts/config.ts` 的 `ASSERT_TYPE` 引用它）—— **改一处必须同时改另一处**
- **`invoke` 的埋点失败不能影响主流程** —— 写流水异常只记日志，不抛
- **`error_msg` 不得含 API Key 或完整 prompt 正文** —— `ai_service._sanitize_error()` 负责脱敏 + 截断
- **调用失败只对瞬时错误重试**（超时/连接失败/5xx），401/403/404/405/429 不重试
- **日志归一化要覆盖中英文两种写法** —— 平台日志是中文的（`行数: 168`、`用户23登录失败`），只按英文规则归一化会把同一错误分成不同簇
- **文档解析失败必须降级为纯文本，不能直接抛** —— research §3.7 要求"不阻断整个生成任务"；降级路径要有测试
- **p95 用线性插值，不要用最近秩** —— 最近秩在样本 ≤ 20 时 p95 等于最大值，"count > p95" 永远不成立，突增一个都检不出
- **草稿的非法状态流转要拦住** —— 已采纳不能驳回、已驳回不能采纳（`status` 与 `case_id` 有不变量）
- **`/ai/log/cluster` 读平台自身日志要 ADMIN**（FR-041）—— 普通用户只能传文本或文件
- **OSS 日志文件的下载是出网请求** —— 复用 `app/utils/ui_security.py` 的 `is_blocked_ip` / `resolve_host` 兜底，不许指向内网

### Mock 配置（003-mock-config 已实现：纯静态 Mock 服务 + 规则配置台）

前端 `/mock` 菜单已从占位页变为真实页面。核心约定：

- **纯静态 Mock 服务** —— 命中规则返回配置的状态码/头/体（可带 0~5000ms 延迟），未命中 404，**不转发到真实后端、不发任何外部请求、不执行任何代码**（SSRF/执行面从机制上排除，AST 静态扫描在 `scripts/mock_selftest.py` 保证）
- **匹配全排序确定**（constitution 原则 I）—— 路径精确度（精确 > 参数化 > 通配）→ 方法具体度（具体 > ANY）→ priority → id；同一请求重复调用结果逐字段一致
- **响应变量是封闭白名单（请求回显）** —— 仅 `$request.path / $request.query.* / $request.body.* / $request.header(s).*`，由请求内容决定、可重放；**不引入随机源/时间戳**；`$randomInt` 等未知变量保存时被拒
- **变量权威正则定义在 `app/core/mock_render.py`**，schema 引用派生锚定版做保存校验 —— 单一出处
- **不碰 `app/core/render.py`**（裸 `Environment()` 非沙箱，RCE 面）—— mock 渲染器只做字典替换
- **管理接口 `Permission()`（与用例/元素同级）+ 私有项目 `read_permission`**；对外服务**无鉴权**（被测系统无法带 JWT，半公开入口 —— 勿在 mock 响应放真实凭据）
- **路由注册顺序是硬约束** —— `main.py` 里管理路由（`mock_admin_router`，带 request_info）**先注册**，对外 catch-all（`mock_service_router`，不带）**后注册**，否则 `/mock/rule/*` 被当成「app=rule」吞掉

**已落地**：

| 位置 | 内容 |
|---|---|
| `app/enums/MockEnum.py` | **跨端常量权威定义**（方法集 / 路径类型 / 延迟上限） |
| `app/core/mock_engine.py` | 匹配引擎（纯函数：derive_path_type / normalize_path / match_rule） |
| `app/core/mock_render.py` | 白名单回显变量渲染器（字典替换，零表达式） |
| `app/models/mock.py` | `pity_mock_rule` 表 |
| `app/crud/mock/MockRuleDao.py` | 规则 CRUD + 查重提示 + app 定位项目（最早创建） |
| `app/routers/mock/admin.py` · `service.py` | 7 个管理接口 + 对外 catch-all |
| `scripts/mock_selftest.py` | 自测（**不依赖数据库**，100 项断言，含 AST 零出网零执行扫描） |
| `scripts/mock_e2e.py` | 端到端（**需要数据库**，33 项断言，直接调路由函数 + 构造 Request） |

**改这里前必须知道**：
- **`app/enums/MockEnum.py` 是方法集/路径类型/延迟上限的权威定义**，前端镜像 `src/consts/mock.ts` —— **改一处必须同时改另一处**
- **`mock_render.VARIABLE_PATTERN` 是回显变量白名单的权威**，`schema/mock.py` 的 `REQUEST_VARIABLE_PATTERN` 是它的锚定版 —— 收紧白名单只改渲染器一处
- **`match_rule` 的排序键是硬契约**（path_type → method 具体度 → priority → id）—— 与 `specs/003-mock-config/data-model.md` §3 同步，别单独改
- **对外服务不得挂 `request_info`**（无鉴权入口记操作日志只会刷垃圾）；异常统一 500，不暴露内部
- **延迟上限 5000ms** 在 schema 拦；`*` 通配只能在路径末尾；body 点分路径段间非空

### UI 自动化子系统（Phase 1+2 已实现，US1~US3 未做）

Playwright 驱动的 UI 自动化。核心约定：

- **元素库是地基，先于 AI 生成做** —— 步骤引用元素而非内联 locator（Page Object 模式），页面改版只改元素库一处
- **录制在本地完成再导入** —— 用户跑 `npx playwright codegen --target python`，粘贴回平台自动建页面/元素/步骤；v1 不做 Chrome 扩展与服务端注入
- **步骤 DSL 是封闭动作白名单** —— 不允许 `evaluate` / 任意脚本执行（仓库已有两个 `exec()` 执行面，不能再开第三个）；不在白名单的动作**在加载步骤时就拒绝**
- **UI 用例复用 `pity_testcase`** —— 加 `request_type=4`（`websocket` 已被挪到 5）；结果照写 `pity_test_result`，报告链路零改造
- **浏览器出网必须设边界（SSRF）** —— 目标地址只能取自**项目级允许域名白名单**（增删需 ADMIN）；仅 http/https；**DNS 解析后**拒绝私网/环回/链路本地/保留地址；重定向**逐跳**重校验；白名单为空 = 不可执行（不是"允许全部"）
- **确定性等待** —— 引擎不得插入隐式 sleep、退避必须固定不随机、定位到多个元素必须**显式失败**而非取第一个；执行结果不可重放（取决于被测系统），需在代码与文档中显式标注
- **镜像代价 +600MB** —— `playwright install --with-deps chromium` 只能在 builder stage 装，用 build arg 控制

数据模型（`pity_ui_page` / `pity_ui_element` / `pity_ui_case` / `pity_ui_node` / `pity_ui_import_log` / `pity_ui_allowed_domain`）、步骤 DSL 规范、codegen 解析规则、SSRF 拦截清单、执行流程 → 见 [`docs/ui-automation-design.md`](docs/ui-automation-design.md)。

**步骤 DSL 的权威出处**是 [`specs/002-ui-automation/contracts/steps.md`](../specs/002-ui-automation/contracts/steps.md)（`001-ai-workbench` 的规则 11–14 引用同一份）—— 动作白名单与定位策略两端常量必须同步：后端 `app/core/ui_executor.py`、前端 `src/consts/uiTest.ts`。

**已落地（Phase 1+2，T001~T022）**：

| 位置 | 内容 |
|---|---|
| `app/models/ui_case.py` | 6 张表 Model |
| `app/crud/ui/` | 6 个 DAO（页面 / 元素 / 用例 / 节点 / 导入日志 / 允许域名） |
| `app/schema/ui_case.py` | Pydantic v1 表单 |
| `app/core/ui_executor.py` | **动作白名单 + 定位策略的权威定义**、动作分派、确定性等待、Browser 单例与并发限流、断言汇总 |
| `app/core/ui_locator.py` | 8 种策略 → Playwright Locator；**多元素显式失败** |
| `app/core/ui_recorder.py` | codegen 脚本**静态解析**（`ast`，不 eval/exec）+ 自动建页面/元素 |
| `app/utils/ui_security.py` | SSRF 六道拦截 |
| `app/routers/ui/` | 27 个端点，前缀 `/ui`（page 4 / element 5 / domain 3 / node 3 / case 6 / record 1 / execution 5） |
| `app/crud/ui/UIExecutionDao.py` | 执行中心：复用 `pity_report` / `pity_test_result`，只做 UI 用例的筛选与汇总 |
| `scripts/ui_selftest.py` | 267 项自测断言，**不依赖数据库** |
| `scripts/ui_e2e.py` | US1 + US2 + US3 的 HTTP 端到端（需要 chromium） |

**跑 UI 用例前必须装浏览器**：`pip install playwright && playwright install chromium`（只装 Python 包不装二进制会在执行时报「未安装 playwright」）。镜像里由 `INSTALL_PLAYWRIGHT=1` build arg 控制（见 `scripts/build-images.sh`）。

**改这里前必须知道**：
- **`ACTIONS` / `STRATEGIES` 只在 `app/core/ui_executor.py` 定义一次**，前端 `src/consts/uiTest.ts` 是镜像 —— 改一处必须同时改另一处
- **`value` 字段有双重语义**：有 `element` 时是动作自己的值（期望值 / 选项值），没有 `element` 时只有 `value` 语义为 `locator` 的动作才允许内联定位
- **`timeout` 单位**：`wait_timeout` 是毫秒，其余动作是秒
- **`locale` 必须钉死**：同一个 URL 在不同 `Accept-Language` 下内容不同（实测 example.com 会按语言返回多语言版本）—— 不固定 locale 就谈不上「同样的输入产出完全一致的结果」。默认 `en-US`
- **存进库的步骤是「纯 DSL」** —— 校验期注入的内部字段（`_element_id` / `_strategy` / `_locator` / `_name_attr`）要用 `strip_internal()` 剥掉再存。**执行器在执行期重新解析元素引用** —— 用例建好之后元素可能被停用，那一步要判失败
- **UI 断言写进 `pity_test_result.asserts` 用的是接口用例同构格式**（`{key: {status, msg}}`），报告页的 `getSource()` 只认这个结构；富明细走 API 响应的 `assertions[]`
- **执行中心不新建表** —— 报告与结果都在既有的 `pity_report` / `pity_test_result` 里；UI 统计只是多算一列，**口径与接口用例一致**
- **内置本地节点在平台启动时自动注册**（`app/__init__.py` 的 lifespan 第 4 步），注册失败不拖垮服务
- **执行结果不可重放** —— 步骤定义确定，但页面内容与断言成败取决于被测系统，代码与文档里都要显式标注

**四条不能动的安全约束**（安全审查时实测确认过，改代码时别把它们拆了）：

| 约束 | 在哪 | 为什么 |
|---|---|---|
| **Service Worker 必须禁用** | `new_context(service_workers="block")` | SW 的脚本与它发起的请求**绕过 `page.route`**（实测），等于给 SSRF 边界开后门 |
| **WebSocket 握手必须单独拦** | `page.route_web_socket("**/*", ...)` | 握手**也绕过 `page.route`**（实测），被测页面能用 `ws://` 连内网服务 |
| **`upload` 动作只认已登记的 OSS 文件** | `_do_upload` 里查 `pity_oss_file` | `set_input_files` 会去读**服务器本地**那个路径 —— 用户填 `/etc/passwd` 就等于把服务器文件 POST 给目标站点 |
| **用户可控的文本必须走沙箱渲染** | `Render.render_safe`（`SandboxedEnvironment`） | 未沙箱的 Jinja2 能通过 dunder 属性拿到 Python 内部对象，`${cycler.__init__.__globals__.os.popen('id').read()}` **会在服务器上执行命令** |

> 这四条都有对应的回归断言在 `backend/scripts/ui_selftest.py` 的 `test_security_boundaries()` 里 —— 别删。

### 配置（`config.py`）

`BaseConfig` 继承 pydantic `BaseSettings`，从 `.env` 文件加载。关键配置：
- MySQL/Redis 连接信息
- `REDIS_ON`：关闭 Redis 后定时任务可能重复执行
- `MOCK_ON` / `PROXY_ON`：Mock 服务器和代理开关

## 新增 API 标准流程

1. **Model** — `app/models/` 创建模型类，继承 `PityBase`
2. **DAO** — `app/crud/` 下对应子目录创建 DAO 类，用 `@ModelWrapper(YourModel)` 装饰，继承 `Mapper`
3. **Schema** — `app/schema/` 创建 Pydantic 验证模型
4. **Router** — `app/routers/` 创建路由，用 `APIRouter` 定义端点
5. **Register** — 在 `main.py` 中 `pity.include_router()` 注册

## 响应格式

```json
{"code": 0, "data": {}, "msg": "操作成功"}
```

| code | 含义 |
|------|------|
| 0 | 成功 |
| 101 | 参数错误（RequestValidationError 自动处理） |
| 110 | 业务异常 |
| 401 | 未登录（AuthException） |
| 403 | 无权限（PermissionException） |

> 成功码沿用 `0`（中文 API 常见约定，如 Java R / 阿里部分开放平台），不是 HTTP 200 的镜像。码表是业务码表，不是 HTTP 风格 —— `101` / `110` 是平台自定义编号，仅 `401` / `403` 数值上与 HTTP 重合。如果有人提议把成功码改成 `200` 来"对齐 HTTP"，请拒绝：
>
> - 前端 service / dva model 全量依赖 `code === 0` 判定，改动面大、易漏；
> - HTTP 状态码固定 200，body 再来 `code: 200` 反而要区分是哪一层；
> - 其他码未与 HTTP 对齐，"半对齐"反而引入新混乱。
>
> 任何新增业务码遵循同一张表（递增、与现有 0 / 101 / 110 同区段），不要混入 200/300/500 这类 HTTP 段。

## 日志

Loguru，按 `name` 分流到两个文件（配置集中在 `app/__init__.py` 的 `init_logging()`）：

| 文件 | 级别 | 内容 |
|------|------|------|
| `logs/pity_info.log` | DEBUG 及以上 | 访问日志、业务 info/debug/success |
| `logs/pity_error.log` | WARNING 及以上 | warning/error/exception、鉴权失败、未捕获异常 |

轮转 `20 MB` / `10 MB`，保留 30 天（`retention`）。

**日志一律走 `Log` 类**（`app/utils/logger.py`），不要裸调 `logger.xxx()`：

```python
from app.utils.logger import Log

log = Log("模块名")          # 模块级, 与 executor / dao 同款
log.info("..."); log.warning("..."); log.exception("...")
```

三条硬规矩（改日志前必读，每条都有实测依据）：

1. **不能裸 `logger.bind(name=...)`，更不能 `bind(name=None)`** —— 文件 sink 的 filter 要求 `extra.name` 等于 `pity_info` / `pity_error`，绑 `None` 或不绑就只进 stdout，容器一重建全丢（2026-11-23 一次性清掉了 26 处）。而且 `INFO_FORMAT` / `ERROR_FORMAT` 要读 `extra[filename]/[func]/[line]`，`Log` 之外绑不全会直接 KeyError。
2. **`init_logging()` 只能用 `logger.configure()`，不能先 `logger.add()` 再 `configure()`** —— configure 是替换式的，会把前面 add 的 `rotation` / `enqueue` 整个丢掉，两个文件永不轮转、无限增长。
3. **请求体 / URL 落盘前必须过 `app/utils/log_sanitize.py`** —— `request_info` 记的是 DEBUG 级别，而 AI 日志分析（`/ai/log/cluster`，ADMIN 权限）读的正是这两个文件；不脱敏等于把密码、JWT、API Key 明文存进日志。脱敏只认键名与 URL path/query，**绝不记 password / token / api_key 的值**，也不记 reset 链接里的 token。

**部署**：`ops/supervisor.conf` 的 gunicorn **必须 `-w 1`**。loguru 的 rotation 按**各进程自己的文件句柄**判断大小，两个 worker 同时触发 rename 会互相覆盖 —— 2026-11-23 实测双进程各写 1500 条只剩 1313 / 1311（**丢 12.5%**）；改用纯 append（`rotation=None`）则不丢（1500/1500）但文件无限增长。所以要么 `-w 1`（当前选择），要么 `-w 2` + 关掉 loguru rotation 改外层 logrotate。日志目录已挂卷：`ops/docker-compose.deploy.yaml` → `/home/tester/pity-data/logs/backend`、`ops/docker-compose.yaml` → `backend/logs`。

**自测**：`.venv/bin/python scripts/logging_selftest.py` —— 不依赖数据库，覆盖 sink 分流、rotation/retention 配置、脱敏正反例、401/403/101/500 四条异常路径留痕、部署配置防回归。

## 数据库迁移

项目配置了 Alembic（`alembic.ini` + `alembic/`），但启动时也会通过 `Base.metadata.create_all` 自动建表。Model 的 `__fields__`、`__tag__`、`__alias__`、`__show__` 类属性控制操作日志的展示字段和关联关系。

## 关键约定

- DAO 文件命名 `XxxDao.py`，放在 `app/crud/` 对应子目录下
- 前端 `localStorage` 中 JWT token 的 key 为 `pityToken`
- 所有 HTTP 响应 code 都在 200，业务错误通过 body 的 `code` 字段区分
- `app/crud/__init__.py` 启动时通过 `importlib` 动态导入所有 DAO 模块
- **CI 业务码 `111`（测试未通过）/ `112`（等待超时）与 `RunStatus` 六态的权威定义在 `app/enums/CiEnum.py`**，前端镜像 `src/consts/ci.ts` —— **改一处必须同时改另一处**（契约：`specs/004-ci/contracts/api.md` §0、§4）
- **跨端常量现在有前端契约测试兜底**（2026-11-24 起）：`frontend/tests/contracts/` 会**直接读本仓库的 Python 源码做解析比对** ——
  - `ci.test.ts` 解析 `app/enums/CiEnum.py` 的 `CiErrorCode` / `RunStatus`
  - `uiTest.test.ts` 解析 `app/core/ui_executor.py` 的 `ACTIONS` / `STRATEGIES`
  - ⚠️ **改后端常量的「写法」也会让前端测试变红**，不只是改值。解析器要求：class 内的常量形如 `NAME = <整数>`（**必须缩进**、不能加类型标注），`ACTIONS` 的每个动作字典字段顺序为 `fields` → `required` → `target` → `value`。要改格式的话，先同步改 `frontend/tests/contracts/` 里的解析正则。
  - 尚未覆盖契约测试的镜像常量：`app/enums/MockEnum.py`、`app/enums/AIWorkbenchEnum.py`、`app/core/data_factory/generator.py` —— 这些目前仍靠人肉同步。

## OSS 存储（`app/middleware/oss/`）

- **实现按厂商分文件**：`OssFile`（抽象基类，`files.py`）→ `aliyun.py` / `qiniu.py` / `tencent.py` / `local.py`，由 `OssClient.get_oss_client()` 按 `configuration_*.json` 的 `oss.oss_type` 分发（单例）。
- **访问域名从配置读，不硬编码**：`oss.endpoint` 存桶的访问域名（`http://<bucket>.hdslb.com` 或自定义域名）。原先硬编码在 `config.py` 的 `QINIU_URL` / `OSS_URL` 已于 2026-11-24 移除 —— 那两个域名已失效，导致「上传到七牛成功、但返回的链接打不开、后端自己下载也失败（`private_download_url` 的签名基于错误域名）」。
  - ⚠️ 生产 `configuration_pro.json` 的 `oss.endpoint` 目前填的是 `http://pity.hdslb.com`（七牛默认域名）—— **需与七牛控制台里 `pity` 桶的实际绑定域名核对**；若控制台用的是自定义域名，改配置即可，不用改代码。
- **dev 环境用本地文件存储**：`oss_type = "local"`，文件落 `backend/data/oss/`（已 gitignore），对外 URL `/oss/files/{key}`（`main.py` 挂 `StaticFiles`；nginx 的 `location ^/(...|oss|...)/` 与前端 dev proxy 的 `'/oss/'` 都会代理到后端，浏览器可直接当 `<img src>` 用）。原先 dev 配的 `gitee` 是废弃的 —— Gitee 对象存储早已下线，且不在 `OssEnum` 里，调接口直接抛「不支持的oss类型」。
- ⚠️ **改 `configuration_*.json` 后必须清 Redis 缓存才生效**：`SystemConfiguration.get_config()` 带 **24 小时** Redis 缓存（key `pity:SystemConfiguration:configuration`），改完 JSON 不清缓存会继续读旧值（本轮改 `oss_type` 时就踩到过）。
  ```bash
  redis-cli -a <密码> del pity:SystemConfiguration:configuration
  ```
- `OssFile.get_real_path()` 的语义：`base_path` 给了就用它**顶替** `pity` 前缀（所以头像的 key 是 `avatar/user_1.png` 而不是 `pity/avatar/user_1.png`）—— 各厂商实现都遵守这个约定，改动时别破坏。
- ✅ **目录缺失 / 不可写都不会让后端起不来**（实测验证）：
  - `data/oss` 或 `data/oss/pity` 不存在 → **自动创建**（`main.py` 建根目录，`LocalOss.create_file` 建子目录）。
  - 目录**不可写** → `main.py` 里「建目录 + 挂 `/oss/files` 静态路由」整段包在 `try/except` 里，失败只告警（`本地 OSS 目录不可用(...)`）。**必须这样兜**：生产走云厂商时根本不需要这个目录，而容器里 `/pity` 可能只读、进程可能以非 root 运行（无写权限）—— 一旦抛异常就是**模块级 import 失败，整个后端起不来**。真需要本地存储时（`oss_type=local`）再由上传接口报错，错误信息清晰。
- ⚠️ **Docker 部署注意**：生产 compose（`backend/ops/docker-compose.deploy.yaml`）的 backend **没有挂载 data 目录** —— local 存储若上生产，文件会落在容器可写层、**容器重建即丢**（与 logs 挂载同类问题）。要用 local 得上三步：① 宿主机 `mkdir -p /home/tester/pity-data/oss`（**别让 docker 自动建目录 —— 它建的是 root 属主，容器内非 root 进程写不进去**）② 挂载 `- /home/tester/pity-data/oss:/pity/data/oss` ③ 确认属主与容器内运行用户一致。

## 安全审查检查点

涉及下列任一面的**新功能或改动**，落地后应跑一次 `security-review` 技能。

**分工**：Claude 在功能边界**主动提示**，但**不自动执行** —— 跑不跑、什么时候跑由用户决定。（按功能节点跑比按每次 commit 跑更贴合安全审查的使用场景，所以没进 Stop hook。）

**触发条件**（命中任一即提示）：

- 新增或改动 `app/routers/` 下的接口，尤其是带写操作的
- 引入或改动数据写入通道：写库（`app/core/data_factory/writer.py`）、写 Redis、文件上传（`app/routers/oss/`）
- 改动鉴权：`Permission(role=...)` 的角色限定、`ProjectRoleDao` 的项目权限判断
- 引入新的外部输入面：用户提供的脚本 / 表达式 / 正则、文件上传解析
- 存储新的敏感数据（密码、Token、API Key）

**为什么这里需要看** —— 项目有这些既有安全面，改动容易无意间放宽边界：

| 安全面 | 位置 |
|---|---|
| `exec()` 任意代码执行 | `app/routers/online/script.py:15`、`app/core/constructor/python_constructor.py:20` |
| Jinja2 未沙箱（可执行任意表达式） | `app/core/render.py` 用的是 `Environment()`，不是 `SandboxedEnvironment` |
| 敏感数据明文存储 | `pity_database_info.password`、`pity_ai_vendor.api_key` |
| 数据写入通道 | 数据工厂 `/write-db`、在线 SQL / Redis 客户端 |
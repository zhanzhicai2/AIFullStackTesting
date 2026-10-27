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

### AI 工作台（设计稿，未实现）

四个 AI 场景（用例生成 / Bug 分析 / 日志分析 / SQL 分析）共用一层公共能力。核心约定：

- **AI 只做翻译与解读，落地由确定性内核做** —— 与数据工厂同源原则。AI 产物先进草稿态（`pity_ai_case_draft`），人工审核后才写业务表
- **用例生成有 14 条硬校验**，其中最致命的两条：断言 `actually` 引用的 `${变量}` 必须在 `out_parameters` 里存在，否则断言取不到值、**静默失败**（`Executor.my_assert` 的取值只来自 `extract_out_parameters`）；Web UI 步骤引用的元素必须存在于元素库且启用，否则**采纳时被拦下**（草稿不进用例库）
- **模型输出不可重放** —— 同一份输入两次生成结果不同。确定性的锚点是草稿**当前 content 版本**：重复采纳同一版本结果一致；重新生成产生新草稿，旧草稿保留
- **断言类型白名单的权威定义在后端** `app/enums/AIWorkbenchEnum.py`（前端 `src/consts/config.ts` 镜像），DSL 常量在 `app/core/ai_prompts/case_gen.py` 与 `src/consts/aiWorkbench.ts` —— **改一处必须同时改另一处**
- **日志分析先聚类再解读** —— 归一化 + fingerprint 分组是纯 Python，AI 只解读 Top-N 簇；突增检测完全不需要 AI
- **SQL 分析禁用 `EXPLAIN ANALYZE`** —— MySQL 8.0.18+ 会真实执行查询，对 UPDATE/DELETE 直接改数据，只能用普通 `EXPLAIN`

公共层 `app/core/ai_service.py`（统一厂商/模型解析 + 调用埋点 + JSON 提取）、4 张新表、API 清单、前后端契约 → 见 [`docs/ai-workbench-design.md`](docs/ai-workbench-design.md)。

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

使用 Loguru，通过 `logger.bind(name=Config.PITY_INFO)` / `Config.PITY_ERROR` 分流：
- `logs/pity_info.log` — DEBUG 及以上
- `logs/pity_error.log` — WARNING 及以上

## 数据库迁移

项目配置了 Alembic（`alembic.ini` + `alembic/`），但启动时也会通过 `Base.metadata.create_all` 自动建表。Model 的 `__fields__`、`__tag__`、`__alias__`、`__show__` 类属性控制操作日志的展示字段和关联关系。

## 关键约定

- DAO 文件命名 `XxxDao.py`，放在 `app/crud/` 对应子目录下
- 前端 `localStorage` 中 JWT token 的 key 为 `pityToken`
- 所有 HTTP 响应 code 都在 200，业务错误通过 body 的 `code` 字段区分
- `app/crud/__init__.py` 启动时通过 `importlib` 动态导入所有 DAO 模块

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
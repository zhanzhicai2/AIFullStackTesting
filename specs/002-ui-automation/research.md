# Phase 0 · 现状调研与技术决策

> Feature: [UI 自动化子系统](./spec.md) | Plan: [plan.md](./plan.md)
> 本文件记录「调研到什么」与「因此决定怎么做」。每一项按 Decision / Rationale / Alternatives considered 三段式给出。

---

## 1. 调研范围

1. **平台已有什么可以复用**（GATE-II 的证据）
2. **UI 自动化特有的技术选择**（浏览器怎么跑、步骤怎么表达、录制怎么导、怎么防 SSRF）
3. **既有安全面会不会被放宽**（GATE-SEC）

调研方式：直接读源码，不依赖记忆。

---

## 2. 复用清单（GATE-II 证据）

### 2.1 用例体系（白拿）

| 表 | 位置 | 复用方式 |
|---|---|---|
| `pity_testcase` | `app/models/test_case.py` | 用例主体。`request_type` 加取值 `4` 表示 web_ui —— **该字段在后端只存不判**（`app/models/test_case.py` 声明后无任何分支逻辑），加取值改面极小；`url` 是 `TEXT nullable=False`，正好存 UI 用例的 `base_url` |
| `pity_testcase_directory` | `app/models/testcase_directory.py` | 目录树。`name` 是 `String(18)`、有 `parent` |
| `pity_constructor` | `app/models/constructor.py` | 前置/后置步骤。**UI 用例的前置步骤可以复用**（如登录后清 cookie） |
| `pity_testcase_asserts` | `app/models/testcase_asserts.py` | 断言。UI 用例的内联断言汇总成同结构 |
| `pity_out_parameters` | `app/models/out_parameters.py` | 出参。UI 用例一般不用，但保留兼容（跨用例传值） |

> **不做第二套用例体系**：UI 用例与接口用例同处一个 `pity_testcase`、同一棵目录树，靠 `request_type` 区分。测试计划可以同时选中两类用例，报告统计口径统一。

### 2.2 执行引擎与结果回写

`app/core/executor.py`：

| 位置 | 现状 | 复用方式 |
|---|---|---|
| `run_single` | 取 `case_info` → 构造器 → 断言 → 出参 → HTTP 请求 → 后置 → 断言 | **在拿到 `case_info` 之后、HTTP 请求之前**按 `request_type` 分派到 UI 执行器 |
| `extract_out_parameters` | 从响应提取出参 | UI 用例一般不需要，但流程可跳过 |
| `my_assert` / `ops` | 断言求值与比对 | UI 的内联断言转成同结构后复用比对逻辑 |
| `CaseLog`（`app/utils/case_logger.py`） | `append()` 记步骤日志、`join()` 汇总 | **UI 的逐步骤日志直接用它**，格式与 API 用例一致 |

**结果落 `pity_test_result`**（`app/models/result.py`）—— 字段映射：

| 字段 | UI 用例的填法 |
|---|---|
| `status` | 0 成功 / 1 失败 / 2 出错（与 API 用例同语义） |
| `case_log` | 逐步骤执行日志（每步 action + 耗时 + 结果） |
| `response` | 失败时存最后的页面 HTML 摘要或错误栈 |
| `asserts` | UI 内联断言汇总成标准断言 JSON |
| `status_code` | 留空（UI 无 HTTP 状态码语义） |
| `url` | 实际访问的 URL |
| `cost` | 总耗时 |

> **报告链路零改造**：测试报告页 `/record/report/:id`（`frontend/src/pages/BuildHistory/ReportDetail.jsx`）**已经有 Tabs**，只需扩一个"附件"tab 展示截图。

### 2.3 报告与实时推送

- `pity_report` + `pity_test_result` → 执行中心的历史记录与报告统计
- `/ws/{user_id}`（`app/core/ws_connection_manager.py`、`main.py:107`）→ 执行中心"正在执行"的实时状态推送
- 测试计划调度（`app/utils/scheduler.py` 的 APScheduler）→ UI 用例可挂进定时任务

### 2.4 文件存储

`pity_oss_file`（`app/models/oss_file.py`）+ `app/routers/oss/oss_file.py` → 失败截图、trace 文件。**不新建文件存储机制**。

### 2.5 前端旧目录

`frontend/src/pages/uiTest/` 有 4 个文件（`TestCaseDirectory.jsx` / `TestCaseComponent.jsx` / `TestPlan.jsx` / `TestCaseRecorder.jsx`），对应路由在 `frontend/config/routes.ts:72-112` **全部被注释**。

**复用目录名与路由前缀，但重写全部内容** —— 旧代码是 JS + dva model 风格，新代码按 `frontend/CLAUDE.md` 用 TypeScript + `@umijs/plugin-model`（hooks 风格）。

### 2.6 渲染与鉴权

- `app/core/render.py` 的 `Render`（Jinja2 `${...}`）→ UI 用例的 `base_url` 与步骤里的字符串字段走同一套渲染
- `PityResponse` / `Permission()` / `PityBase` / `Mapper` / `@ModelWrapper` / `@connect` → 沿用既有模式
- loguru → 日志

### 2.7 没有的（全新）

元素库、Playwright 依赖、执行节点、录制导入器 —— 仓库里**一处都没有**。

---

## 3. 决策

### 3.1 用 Playwright Python，不是 Node

**Decision**：后端引入 `playwright` Python 包，步骤 DSL 直接映射到 Playwright 的 async API。

**Rationale**：与后端同语言 → 不需要跨语言协议、不需要第 4 个 Docker 镜像、不需要 Node 侧运行时；DSL→API 的映射是直接的函数调用而非代码生成。

**Alternatives considered**：
- *Playwright Node 独立 runner* → 要新增一个 Docker 镜像 + 一套 HTTP/队列协议；且前端是浏览器 SPA，**跑不了 Playwright**（Playwright 需要 Node 进程）。运维成本最高。否决。
- *Selenium* → 生态更老、定位器能力弱于 Playwright（缺 `get_by_role` 等语义定位器）、Python 绑定陈旧。否决。

### 3.2 浏览器跑在 API 进程内，不起独立 worker

**Decision**：Playwright async API 在 `Executor` 内直接 `await`；Browser 实例**进程内单例复用**，每个用例开独立 `Context`（cookie/storage 隔离）；`asyncio.Semaphore` 限流（默认并发 2/进程）。

**Rationale**：与后端同进程 → 无需队列、无需 worker 进程、无需进程间协议；`gunicorn -w 2` 会自动重启崩溃的 worker，浏览器崩溃只影响当前用例。

**Alternatives considered**：
- *Redis 队列 + 独立 worker 进程* → 隔离性更好（浏览器 OOM 不影响 API），但要引入队列协议、worker 生命周期管理、supervisor 第二个 program。**第一版是过度设计**，且内存问题（浏览器占用）不会因为换进程而消失。留给 v2。
- *每次用例新起 Browser* → 慢（冷启动数秒）且内存峰值高。否决。

**内存代价要记账**：chromium 单实例 ~150–300MB，`gunicorn -w 2` 各起一份 = 600MB+。信号量默认并发 2 是**每进程**的，实际全局上限 4。写进 plan.md 的 Technical Context。

### 3.3 步骤引用元素，而不是内联定位表达式

**Decision**：步骤里写 `{"action": "click", "element": "登录页.登录按钮"}`，不写 `{"action": "click", "by": "css", "value": "#login-btn"}`。内联定位仅作兜底，采纳时提示纳入元素库。

**Rationale**：这是 Page Object 模式，收益有三层：
1. **页面改版只改元素库一处**，所有引用它的用例自动受益 —— 这是本 feature 最核心的价值（spec SC-006）
2. 定位策略集中管理，换定位策略（比如从 CSS 换成语义定位）不用动用例
3. AI 生成的 UI 用例**只能引用已有元素** → 生成质量从"猜 selector"变成"编排已有元素"（见 §3.5）

**Alternatives considered**：
- *每步内联定位* → 页面改版要改 N 条用例，与"降低维护成本"的核心诉求相反。否决。
- *只允许元素引用、不允许内联* → 录制导入时某些元素无法归入元素库，会把用户卡死。允许内联作兜底 + 提示治理，是更现实的折中。

### 3.4 语义定位优先，不写死 CSS selector

**Decision**：定位策略枚举包含 `role` / `label` / `text` / `placeholder` / `testid` 这些**语义定位**，与 CSS/XPath 并列。`role` 策略额外存 accessible name。

**Rationale**：Playwright 官方推荐 `get_by_role` / `get_by_label` / `get_by_text` / `get_by_test_id`，理由是抗改版、可读。而**语义定位恰好是 AI 从自然语言里唯一能可靠推断出来的东西** —— AI 推得出"点击登录按钮"，推不出 `#login-btn`。这条决策让"AI 生成 UI 用例"从"生成即不可用"变成"生成即大致可用"。

**Alternatives considered**：
- *只支持 CSS/XPath* → AI 生成的 UI 用例几乎必然不可用，等于放弃与 001 的联动。否决。

### 3.5 元素库必须先于 AI 生成

**Decision**：工程顺序上 **元素库 → 录制导入 → UI 用例管理 → 执行**，AI 生成 UI 用例排在最后（属 001 feature）。

**Rationale**：AI 生成 UI 用例的质量**完全建立在元素库质量上** —— 没有元素库，AI 只能猜 selector，产出不可用。这是参考产品（Ntester）里容易被看漏的一层：它把元素库排在用例管理之后，但那是菜单顺序，不是依赖顺序。

**Alternatives considered**：
- *按参考产品的菜单顺序实现* → AI 生成先落地，产出一堆定位失效的用例，团队对 AI 的信任一次就耗光。否决。

### 3.6 录制通道：只做本地 Codegen 导入

**Decision**：用户在自己机器上跑 `npx playwright codegen --target python <url>`，把脚本粘贴回平台的「录制导入」页。平台解析后自动建页面/元素并产出用例草稿。

**Rationale**：这是唯一**平台侧零浏览器运维、零额外服务、零用户环境准备**的通道 —— codegen 是官方工具，输出格式稳定可解析。其余两条通道各有硬伤：
- **Chrome 扩展**：要开发 + 过商店审核 + 处理跨域注入，长期维护成本最高
- **服务端注入**：平台要起 browser server 并用 noVNC 把画面推给用户（Browserless 架构），1–2 周工作量，且要引入一个额外的实时通道

**Alternatives considered**：
- *三条通道都做* → v1 范围过大，且 Chrome 扩展的维护成本会持续到 indefinite。否决。
- *只做手工录入，不做录制* → 录制是本 feature 提效最大的环节（spec US2），砍掉等于放弃主要价值。否决。

### 3.7 录制脚本的解析与元素去重

**Decision**：解析 codegen 输出的 Python 脚本，识别 `page.goto(url)` 与 `page.<locator_method>(args).<action>(args)` 模式。无法解析的行**跳过并在导入结果中说明**，不中断整段导入。元素按 `(project_id, page_id, strategy, locator, name_attr)` 去重：已存在则复用、只追加步骤。

**Rationale**：codegen 输出可能包含自定义 JS、多行调用等无法解析的内容 —— 整段失败会让用户白录一遍。逐行跳过 + 说明是更好的体验。去重保证"多次录制同一页面"不产生元素库垃圾。

**Alternatives considered**：
- *导入失败就整段报错* → 用户白录。否决。
- *每次导入都新建元素* → 元素库很快被重复条目淹没，失去"库"的价值。否决。

### 3.8 浏览器执行的 SSRF 防护（新增安全面，必须处理）

**Decision**：UI 用例的目标地址**不得由用户自由填写**。`base_url` MUST 取自**项目/环境级配置的允许域名白名单**；步骤里的 URL 只能是相对路径，绝对 URL MUST 落在白名单内；**无论是否在白名单内**，主机解析后若指向私有网段、环回、链路本地或保留地址，一律拒绝；跟随重定向时**每一跳**重新校验。

**Rationale**：这是本 feature 引入的**全新出网面**。既有平台没有"服务器主动访问用户指定 URL"的能力，所以既有安全面（`exec()` / 未沙箱渲染 / 明文凭据 / 数据写入通道）都没覆盖它。若不设边界，用户可以让平台去访问内网服务或云厂商元数据接口（`169.254.169.254`）。

constitution 安全要求写的是"MUST NOT 在引入新的外部输入面时放宽上述边界" —— 这里不是放宽既有边界，而是**必须为新面建立边界**。

**Alternatives considered**：
- *完全开放任意 URL* → 直接引入 SSRF。否决。
- *只做白名单、不做私网拦截* → 白名单本身若被配置成内网地址或被 DNS 劫持，仍会打到内网。两层都要。否决。
- *不做重定向校验* → 首跳合法、二跳到 `169.254.169.254` 就绕过了。必须逐跳校验。否决。

### 3.9 等待策略：确定性等待，不用固定 sleep

**Decision**：等待一律用**条件等待**（等选择器可见 / 可交互 / 附加完成 / 分离）。固定 `wait_timeout` 允许但必须**显式写进步骤定义**（带毫秒数），不作为隐式默认。禁止在引擎内部插入任何隐式 sleep 或随机退避。

**Rationale**：constitution 原则 I 要求"MUST 满足:同样的输入 MUST 产出完全一致的结果"。隐式 sleep + 随机退避会让同样的步骤在不同机器上行为不同 —— 这是**平台自己引入的随机源**，必须在源头堵死。条件等待同时更快也更稳定。

**Alternatives considered**：
- *统一加一段 sleep 缓冲* → 最常见的做法，但把不确定性写进了平台，且掩盖真实问题（元素没出现时应该失败，而不是多等一会儿）。违反原则 I。否决。
- *失败后重试 N 次并随机退避* → 重试本身没问题（执行计划里可以有重试），但**退避必须固定**（如固定 1s），不得随机。随机退避是原则 I 明令禁止的"全局 random"类随机源。否决。

### 3.10 UI 断言汇总成标准断言结构

**Decision**：UI 步骤里的内联断言（`expect_text` / `expect_visible` 等）在执行时转成 `pity_testcase_asserts` 同构的 JSON，写入 `pity_test_result.asserts`，**沿用既有 `asserts` 字段**。

**Rationale**：报告页、统计口径、断言失败明细的展示逻辑全部复用。若 UI 断言另起一套结构，报告页要写两套渲染。

**Alternatives considered**：
- *UI 断言单独存一张表* → 报告统计要合并两张表，口径不一致风险高。否决。

### 3.11 失败截图，trace 留到 v2

**Decision**：用例失败时自动截图，上传 OSS，URL 写入 `case_log`，报告页"附件"tab 展示。**trace / 视频录制默认关闭**（开销大）。

**Rationale**：截图是排查失败最直接的证据，成本低（失败时才截）。Playwright 的 trace 价值更高但体积大、开启有持续开销 —— 放到 v2 作为可选项。

### 3.12 执行节点做抽象，v1 只实现本地节点

**Decision**：建 `pity_ui_node` 表记录执行节点（名称、类型、状态、浏览器、无头模式、并发上限、版本）。v1 注册一个内置节点；API 按节点 id 选择节点，v2 接远程节点时调用方不改。

**Rationale**：参考产品有分布式执行节点（CDP / Grid / Playwright WS 连接）。**v1 明确不做分布式**，但**接口形状先定好**，避免 v2 时改调用方。

### 3.13 UI 用例与接口用例共用目录树

**Decision**：UI 用例与接口用例同处 `pity_testcase_directory` 树，靠 `request_type` 区分。

**Rationale**：测试计划可以同时选两类用例；报告统计统一；用户在一个项目里管理全部测试资产。分两棵树会让"这个项目的测试都在哪"变成问题。

### 3.14 部署形态：镜像与进程

**Decision**：`backend/ops/dockerfile` 增加 `ARG INSTALL_PLAYWRIGHT=0`，值为 `1` 时在 builder stage 执行 `playwright install --with-deps chromium`。生产部署把该 ARG 设为 `1`。

**Rationale**：浏览器二进制只能在 builder stage 装（需要 root 装系统库），最终 stage 只拷贝 venv。ARG 控制让不跑 UI 的环境保持镜像轻量。

**Alternatives considered**：
- *每个环境都装* → 开发库也要 +600MB，不必要。否决。
- *用官方 Playwright 镜像做 worker* → 需要挂载代码进去、版本管理复杂，且与现有 supervisord 单镜像模型不搭。否决。

---

## 4. 未决问题

无。spec 阶段的 8 项潜在歧义已全部在 Assumptions 中定档（见 `checklists/requirements.md` 的核对表），Phase 0 无新增 NEEDS CLARIFICATION。

---

## 5. Phase 0 结论

| 项 | 结论 |
|---|---|
| 复用清单 | 15+ 项既有能力直接复用；用例体系、执行记录、报告结构、文件存储、实时推送**全部白拿** |
| 新增依赖 | 1 个（`playwright` Python 包）+ chromium 二进制；镜像代价用 ARG 控制 |
| 新增数据表 | 5 张（页面 / 元素 / UI 用例 / 执行节点 / 导入记录） |
| 新增代码目录 | `app/core/ui_*.py`、`app/crud/ui/`、`app/routers/ui/`、`app/utils/ui_security.py`、`frontend/src/pages/UiTest/` |
| 新增安全面 | **2 个**：录制脚本解析（只解析不执行）、浏览器出网（SSRF，白名单 + 私网拦截 + 逐跳校验） |
| 明确不做 | 分布式执行节点、Chrome 扩展录制、服务端注入录制、Appium 移动端 |

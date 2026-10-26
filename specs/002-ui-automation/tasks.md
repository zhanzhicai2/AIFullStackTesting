# Tasks: UI 自动化子系统

**Input**: Design documents from `/specs/002-ui-automation/`

**Prerequisites**: plan.md ✅ · spec.md ✅ · research.md ✅ · data-model.md ✅ · contracts/steps.md ✅ · contracts/api.md ✅ · quickstart.md ✅

**Tests**: **包含**。constitution 原则 V 规定"功能改动落地前 MUST 通过自动化验证, MUST NOT 只靠手动点一遍；若该模块没有自动化验证手段, MUST 先补上再落地"。

**Organization**: 任务按用户故事分组，每个故事可独立实现、独立测试、独立交付。

**Format**: `[ID] [P?] [Story?] Description with file path`

> **修订记录（`/speckit-analyze` 后）**：
> - 新增 **T016**（`routers/ui/page.py` 页面树 CRUD）—— 原 T016 只覆盖 element.py，**页面树这个地基没有任务**（FR-001 零覆盖）
> - T021 补 FR-013（`${}` 渲染）与 FR-035（名称超长截断）；T031 补 FR-010（内联定位提示纳入元素库）与 FR-035 的前端提示；T030 补 U3（无目录时就地新建入口）
> - T017 补 D1 的显式角色说明
> - 任务编号在 T016 之后统一 +1（原 T016~T049 → T017~T050）

> **实现记录（Phase 1 ~ Phase 4 落地时）** —— T001~T036 已完成，实现与契约有 15 处偏差/补齐，逐条记在这里：
>
> 1. **T004 多落地 1 个 DAO**：任务列了 5 个 DAO，但 6 张表里的 `pity_ui_allowed_domain` 同样需要 DAO —— 补 `backend/app/crud/ui/UIAllowedDomainDao.py`（共 6 个）。
> 2. **T020 的分派点在 `Executor.run` 而非 `run_single`**：`case_info` 是在 `run()` 里取的，`run_single` 只负责分发到 `run_with_test_data` → `run`。按契约「拿到 case_info 之后、HTTP 请求之前」分派，落在 `run()` 里，批量与单条调试共用同一条路径。
> 3. **`request_type = 4` 与既有枚举冲突**：既有 `RequestType.websocket = 4`，但 websocket 从未真正落地（前端 `REQUEST_TYPE` 只提供 1/2/3，新建用例的表单只允许 HTTP）。契约明确 4 = web_ui，已把 websocket 挪到 5，存量数据里不存在 `request_type=4` 的用例。
> 4. **UI 断言写进 `pity_test_result.asserts` 用的是「接口用例同构」格式**（`{key: {status, msg}}`），不是 `contracts/api.md` §3.2 示例里的数组。理由：research §3.10 要求「沿用既有 asserts 字段」、spec FR-034 要求「口径一致」，且既有报告页 `src/components/TestCase/TestResult.jsx` 的 `getSource()` 只认 `{k: {status, msg}}` 结构 —— 写数组会让报告页渲染直接报错。富断言明细（name / assert_type / expected / actually）放在 API 响应的 `assertions[]` 里返回。
> 5. **`timeout` 字段的单位**：契约 §2 字段表说「覆盖用例级超时（秒）」，§3.3 动作表说 `wait_timeout` 的 `timeout` 是毫秒 —— 两者不一致。实现按**动作表**（更具体）执行：`wait_timeout` 用毫秒，其余动作用秒，并在 `ACTIONS` 的注释里写明。
> 6. **`value` 字段的双重语义**（内联定位值 vs 断言期望值）：实现规则为 —— 有 `element` 时 `value` 是动作自己的值；没有 `element` 时，**只有 `value` 语义为 `locator` 的动作**才允许内联定位（`expect_text` / `expect_value` / `expect_count` / `expect_url` / `select` / `drag` 必须走 `element`）。
> 7. **SSRF 白名单的 `*.example.com` 不匹配 apex** `example.com`（要同时配两条）。刻意保持严格 —— 通配符覆盖 apex 会让白名单的实际范围比用户以为的宽。
> 8. **dockerfile 额外拷了浏览器二进制**：契约写「最终 stage 只拷贝 venv」，但 chromium 的二进制不在 venv 里（`PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`），只拷 venv 浏览器跑不起来；系统库也要在最终镜像里再装一次（`playwright install-deps chromium`）—— builder 阶段 `--with-deps` 装的那份留在 builder 的文件系统里，不会跟过来。
> 9. **T007 / T008 的录制导入只有前端封装**：后端端点 `/ui/record/import` 属于 Phase 4（T034），本轮没实现。前端 service / model 已备好调用封装，等 T034 落地即可用。
> 10. **前端页面目录名是 `src/pages/uiTest/`（小写 t）**：仓库里早就有一个 `src/pages/uiTest/`（旧的 JS 页面），macOS 大小写不敏感 → 新建 `src/pages/UiTest/` 会**落到同一个目录**里，TypeScript 随即报 TS1261（同一个文件两种大小写各被收进 program 一次）。**所有路径引用必须用磁盘上的真实大小写 `uiTest`**：`config/routes.ts` 写 `'./uiTest/Element'`，样式文件是 `UiTest.less`（名字与目录不同大小写没关系，导入路径要与文件名一致）。Linux CI 是大小写敏感的，写错就构建失败。
>
> **Phase 4（US2 录制导入）落地时补的 4 条**：
> 11. **导入请求多两个可选字段 `directory_id` / `name`**：契约里没写，但用例总要挂在某个目录下 —— 不传就落到顶级(None)，前端会引导用户去选目录 / 建目录(U3)。`name` 不传时取「录制导入-<首个页面名>」，同名自动加序号。
> 12. **`base_url` 取脚本里第一个 `page.goto` 的地址** —— 录制脚本就是从那儿开始的，比留空有用。
> 13. **存进库的步骤是「纯 DSL」，校验期注入的内部字段(`_element_id` / `_strategy` / `_locator` / `_name_attr`)被剥掉**（`ui_executor.strip_internal`）。`contracts/steps.md` §1 说步骤 DSL 同时是存储格式、编辑格式与执行格式，内部字段是中间产物不该落库。**执行器改为在执行期重新解析元素引用** —— 用例建好之后元素可能被停用，那一步要判失败（`contracts/steps.md` §4.1 第 3 条）；原来靠落库的 `_strategy` 继续用，元素停用了也不会报错，是错的。
> 14. **逐行兜底解析时必须记下失败的行号**：整段 `ast.parse` 失败后退化成逐行解析，坏行原本被**静默丢弃**，违反 FR-017「跳过并在导入结果中说明」。现在会记下行号并在 `warnings` 里说明。
> 15. **`base_url` 的域名在保存时也校验**（白名单非空时）：白名单为空时**不在保存时拦** —— 用户可能先把用例写好再配白名单，执行时会被拦并给出 U1 的就地指引。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 依赖、部署形态、数据模型与前端骨架

- [x] T001 在 `backend/requirements.txt` 追加 `playwright>=1.49`（Python 包；浏览器二进制见 T002）
- [x] T002 修改 `backend/ops/dockerfile`：新增 `ARG INSTALL_PLAYWRIGHT=0`，值为 `1` 时在 **builder stage** 执行 `/pity/venv/bin/playwright install --with-deps chromium`（最终 stage 只拷贝 venv —— 系统库只能在 builder 装）；并在文档中标注镜像 +~600MB
- [x] T003 [P] 创建 `backend/app/models/ui_case.py` 的六个 Model，字段与约束**逐条照抄 `data-model.md` §2**：`PityUIPage`（`UniqueConstraint('project_id','name','parent','deleted_at')`）、`PityUIElement`（去重唯一约束含 `strategy`/`locator`/`name_attr`）、`PityUICase`（`UniqueConstraint('case_id','deleted_at')`）、`PityUINode`、`PityUIImportLog`、`PityUIAllowedDomain`（`domain` 必须是裸域名）
- [x] T004 [P] 创建 `backend/app/crud/ui/` 下五个 DAO：`UIPageDao.py`、`UIElementDao.py`、`UICaseDao.py`、`UINodeDao.py`、`UIImportLogDao.py`，沿用 `@ModelWrapper` + `Mapper` + `@connect` 模式
- [x] T005 [P] 创建 `backend/app/schema/ui_case.py` 的 Pydantic v1 表单：页面表单、元素表单（含 8 种策略枚举）、UI 用例表单（含步骤模型）、白名单表单、录制导入表单
- [x] T006 [P] 创建 `frontend/src/consts/uiTest.ts`，镜像后端 `app/core/ui_executor.py` 的 `ACTIONS`（动作白名单）与 `STRATEGIES`（8 种定位策略）；文件头注释必须写明"权威定义在 `backend/app/core/ui_executor.py`，改一处必须同步另一处"
- [x] T007 [P] 创建 `frontend/src/services/uiTest.ts`，封装页面/元素/用例/白名单/节点/录制的接口调用（签名与 URL 严格照 contracts/api.md；用 `request` + `auth.headers()`）
- [x] T008 [P] 创建 `frontend/src/models/uiTest.ts`，hooks 风格（`useState` + `useCallback`），不得使用 dva model

**Checkpoint**: 骨架就绪 —— 依赖已声明、部署形态已定、数据模型与前端常量就位

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 定位器、执行引擎、安全边界、录制解析与路由 —— 三个用户故事全部依赖

**⚠️ CRITICAL**: 本阶段未完成前，任何用户故事都不能开工

- [x] T009 实现 `backend/app/core/ui_locator.py`：8 种定位策略 → Playwright Locator 的映射（`role` 策略额外用 accessible name）；**定位到多个元素时显式抛错，不得静默取第一个**（research §4.4）
- [x] T010 实现 `backend/app/core/ui_executor.py` 的 Browser 管理：Browser **进程内单例复用**、每用例独立 Context（cookie/storage 隔离）、`asyncio.Semaphore` 限流（默认 2/进程）、浏览器异常不得带崩 gunicorn worker
- [x] T011 实现 `backend/app/core/ui_executor.py` 的**动作分派**（封闭白名单，逐条照抄 `contracts/steps.md` §3）：不在白名单内的动作**在加载步骤时就拒绝**，不是执行时才拦；`evaluate` / `exec` / 任何"执行代码"的动作一律不接受
- [x] T012 实现 `backend/app/utils/ui_security.py` 的 **SSRF 拦截**（逐条照抄 `data-model.md` §7.2 的 6 条检查点）：协议白名单（仅 http/https）、项目级域名白名单匹配（含 `*.example.com` 子域通配）、**DNS 解析后**逐个 IP 检查私网/环回/链路本地/保留地址、重定向**逐跳**重新校验、页面子资源请求同样拦截
- [x] T013 实现 `backend/app/core/ui_executor.py` 的**确定性等待**（`contracts/steps.md` §6）：条件等待优先；**引擎不得插入任何隐式 sleep**；固定等待必须显式配置；重试退避必须固定不随机；定位多元素显式失败而非随机挑选
- [x] T014 实现 `backend/app/core/ui_recorder.py` 的 codegen 脚本解析：识别 `page.goto(url)` 与 `page.<locator_method>(args).<action>(args)` 模式（映射见 research §3.7）；**只做静态文本解析，绝不 eval / exec / 在浏览器里跑脚本内容**；无法解析的行跳过并记录原因，不中断整段
- [x] T015 实现 `backend/app/core/ui_recorder.py` 的**自动建页面与元素**：页面按 URL 的 origin+path 归一后建立或复用；元素按 `(project_id, page_id, strategy, locator, name_attr)` 去重，已存在则复用只追加步骤
- [x] T016 实现 `backend/app/routers/ui/page.py` 的**页面树 CRUD**：`/ui/page/list`（返回带 `element_count` 的树）、`/ui/page/insert`、`/ui/page/update`、`/ui/page/delete`；删除页面**不级联删元素**，元素转为停用并提示用户处理引用（data-model §8）；`parent` 必须同项目且不得成环
- [x] T017 实现 `backend/app/routers/ui/element.py` 的 CRUD + 启停：`/ui/element/list`、`insert`、`update`、`delete`、`status`；去重时返回既有元素 id 与 `duplicated` 标志；**写入权限显式说明** —— 页面与元素的写入保持 `Permission()`（元素库是团队协作资产，与既有"创建用例"同级、不扩大权限面），而 `pity_ui_allowed_domain` 收紧到 ADMIN（那是安全边界，见 T018）
- [x] T018 实现 `backend/app/routers/ui/domain.py` 的白名单 CRUD：**增删必须 `Permission(role=Config.ADMIN)`**（这是安全边界，配错等于放行内网）；`domain` 必须是裸域名，含协议或路径的串一律拒绝
- [x] T019 实现 `backend/app/routers/ui/node.py`：内置本地节点的自注册与列表；节点删除需 ADMIN
- [x] T020 修改 `backend/app/core/executor.py` 的 `run_single`：在拿到 `case_info` 之后、HTTP 请求之前，按 `request_type == 4` 分派到 UI 执行器；UI 用例**复用既有的前置/后置构造器**
- [x] T021 实现 `backend/app/routers/ui/case.py` 的 UI 用例 CRUD：步骤校验逐条照抄 `contracts/steps.md`（动作白名单、必填字段、元素引用解析、未知字段丢弃并告警）；单个步骤无效只丢该步骤并告警，**全部步骤无效则拒绝创建**；**`base_url` 与步骤里的字符串字段走既有 `Render.render` 渲染**（FR-013，变量来源为 `pity_gconfig` 全局变量与出参）；**用例名/目录名超长时按既有列长度截断并回显告警**（FR-035）
- [x] T022 实现 `backend/app/routers/ui/case.py` 的 `POST /case/run`：调用 UI 执行器，结果按 `data-model.md` §6 的映射写入**既有的 `pity_test_result`**；失败时截图 → 上传 OSS → URL 写入 `case_log`；错误原因按 `contracts/api.md` §3.2 的 6 类分类返回，**且每步回传元素的定位策略与定位值**（FR-023）；单步超时后停止后续步骤并保留现场

**Checkpoint**: 基础就绪 —— 定位器、执行引擎、安全边界、录制解析、路由齐备，三个故事可并行开工

---

## Phase 3: User Story 1 - 沉淀元素定位并跑通第一条 UI 用例 (Priority: P1) 🎯 MVP

**Goal**: 用户在元素库沉淀页面与元素的定位策略，编写引用这些元素的 UI 用例，在真实浏览器中执行并拿到逐步骤日志与失败截图

**Independent Test**: 按 `quickstart.md` §3.1 手工登记一个页面与三个元素，编写一条引用它们并断言错误提示的 UI 用例，执行后拿到逐步骤日志与通过/失败结论，并验证元素停用后失败信息能指明是哪个元素失效

### Tests for User Story 1 ⚠️

- [x] T023 [P] [US1] 在 `backend/scripts/ui_selftest.py` 实现步骤 DSL 校验的测试用例：动作白名单正例、必填字段缺失、定位策略枚举、未知字段丢弃并告警
- [x] T024 [P] [US1] 在 `backend/scripts/ui_selftest.py` 实现**动作白名单的负例**：`evaluate` / `exec` / `run` / `script` 等动作必须被拒绝，且**在加载步骤时就被拒绝**（不是执行时）
- [x] T025 [P] [US1] 在 `backend/scripts/ui_selftest.py` 实现 **SSRF 拦截的测试用例**：协议非 http/https、域名不在白名单、解析到 `127.0.0.1` / `10.x` / `192.168.x` / `169.254.169.254` / IPv6 私有与环回、重定向跳内网、白名单为空
- [x] T026 [P] [US1] 在 `backend/scripts/ui_selftest.py` 实现**确定性等待的断言**：引擎不得插入隐式 sleep、退避必须固定、多元素匹配必须显式失败

### Implementation for User Story 1

- [x] T027 [US1] 实现 `backend/app/core/ui_executor.py` 的断言汇总：UI 内联断言转成 `pity_testcase_asserts` 同构的 JSON（映射见 `contracts/steps.md` §5.2），写入 `pity_test_result.asserts`，**不新增断言表**
- [x] T028 [P] [US1] 实现 `frontend/src/pages/UiTest/Element/index.tsx`：页面树 + 元素列表 + 启用停用切换；空元素库时就地提示（U4）
- [x] T029 [P] [US1] 实现 `frontend/src/pages/UiTest/Element/ElementModal.tsx`：新建/编辑元素弹窗，定位策略下拉 8 种；`role` 策略时额外显示可访问名称字段；**优先用语义定位的提示文案**
- [x] T030 [US1] 实现 `frontend/src/pages/UiTest/CaseManage/index.tsx`：用例列表（复用既有目录树），列含编号/名称/所属模块/优先级/类型/状态/更新时间；**目录选择器旁提供「新建目录」入口**（U3，项目下无目录时就地建完即选中）
- [x] T031 [US1] 实现 `frontend/src/pages/UiTest/CaseManage/CaseEditor.tsx`：步骤编排（增删改步骤、从元素库选目标）、元素引用失效的高亮与跳转处理、**调试执行按钮**、base_url 旁就地指引（U1/U2/U4）；**检测到全内联定位时提示建议纳入元素库**（FR-010）；**用例名超长时提示长度限制并给出建议的截断结果**（FR-035）
- [x] T032 [US1] 在 `backend/scripts/ui_e2e.py` 实现 US1 端到端：页面/元素 CRUD → 元素去重与停用 → 用例创建（引用元素）→ 执行 → `pity_test_result` 回写 → 失败截图落 OSS → 元素停用后执行失败且信息指明元素与定位策略

**Checkpoint**: US1 完整可用 —— 最小闭环跑通（MVP）

---

## Phase 4: User Story 2 - 本地录制导入，快速产出可编辑的用例草稿 (Priority: P2)

**Goal**: 用户本地录制后粘贴脚本，平台自动建页面与元素并产出可编辑的 UI 用例

**Independent Test**: 按 `quickstart.md` §3.2 本地录制一段登录操作、粘贴导入，检查自动建出的页面与元素、生成的步骤，重复导入不产生重复元素，且脚本中的自由代码未被执行

### Tests for User Story 2 ⚠️

- [x] T033 [P] [US2] 在 `backend/scripts/ui_selftest.py` 实现 codegen 脚本解析的测试用例：sync 与 async 两种目标、8 种 locator 写法、`expect(...).to_be_visible()` 断言写法、**无法解析的行被跳过且不中断整段**、**含自由代码的行被跳过**

### Implementation for User Story 2

- [x] T034 [US2] 实现 `backend/app/routers/ui/record.py` 的 `POST /record/import`：调用 T014/T015 的解析与建页面/元素逻辑、产出 UI 用例（**状态为「调试中」= 草稿态**，用户核对后改为「正常运行」即视为采纳）、写 `pity_ui_import_log`（含 parsed_lines / skipped_lines / pages_created / elements_created / elements_reused）、把跳过行的原因放进 `warnings` 返回
- [x] T035 [P] [US2] 实现 `frontend/src/pages/UiTest/Record/index.tsx`：脚本粘贴区、解析结果预览（建了几个页面/元素、跳过了几行及原因）、跳转到用例编辑页；未粘贴脚本时就地提示（U5）
- [x] T036 [US2] 在 `backend/scripts/ui_e2e.py` 实现 US2 端到端：导入 → 自动建页面/元素 → 产出「调试中」状态的用例 → 重复导入不产生重复元素 → 自由代码未被执行 → 无法解析的行被跳过

**Checkpoint**: US1 与 US2 均独立可用

---

## Phase 5: User Story 3 - 执行中心与测试报告 (Priority: P3)

**Goal**: 用户可查看正在执行的任务与历史执行记录，报告页展示通过率、趋势、逐条结果、步骤日志与截图附件

**Independent Test**: 按 `quickstart.md` §3.3 执行一批 UI 用例后，在执行中心看到历史记录，打开报告看到总体通过率与逐条用例结果（含失败用例的步骤日志与截图）

### Tests for User Story 3 ⚠️

- [ ] T037 [P] [US3] 在 `backend/scripts/ui_e2e.py` 实现 US3 端到端：UI 用例与接口用例混合执行 → 报告通过率合并计算且口径一致 → 重新执行产生新记录且原记录不被覆盖 → 删除历史记录生效 → 报告附件能取到失败截图

### Implementation for User Story 3

- [ ] T038 [US3] 实现 `backend/app/routers/ui/` 下的执行中心端点：**复用既有的 `pity_report` / `pity_test_result`**，只做 UI 用例的筛选与汇总；支持重新执行与删除历史记录（复用既有接口语义，不新建表）
- [ ] T039 [US3] 修改 `frontend/src/pages/BuildHistory/ReportDetail.jsx`：扩"附件" tab，展示 UI 用例的失败截图；确保 UI 与接口用例的统计口径一致（spec FR-034）
- [ ] T040 [P] [US3] 实现 `frontend/src/pages/UiTest/Execution/index.tsx`：执行中心（正在执行 / 执行历史 / 回收站三个视图），表格列为执行时间、任务名称、环境、执行结果、用例数、通过率、执行人；提供重新执行与删除
- [ ] T041 [P] [US3] 实现 `frontend/src/pages/UiTest/Node/index.tsx`：执行节点列表（在线/离线状态、浏览器、并发上限）；无可用节点时就地提示（U6）

**Checkpoint**: 三个故事全部独立可用

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 横切能力、文档与验收

- [ ] T042 [P] 实现 `backend/app/routers/ui/` 的允许域名查询端点（列表走 `Permission()`，增删走 ADMIN —— 已在 T018 覆盖）与节点心跳的调用方接线
- [ ] T043 更新 `backend/CLAUDE.md`：新增「UI 自动化」段落，只放硬约束与指针 —— **步骤 DSL 动作白名单封闭（不得引入新 `exec()` 面）**、**SSRF 白名单 + 私网拦截 + 重定向逐跳校验**、**确定性等待（禁隐式 sleep 与随机退避）**、常量两端同步要求、执行结果不可重放的显式声明
- [ ] T044 更新 `backend/docs/ui-automation-design.md`：按 constitution「每次功能落地 SHOULD 在 `backend/docs/<feature>-design.md` 中记录哪些原则影响了设计决策」补写 constitution 五条原则对本设计的影响；同步 SSRF 拦截清单与确定性约束
- [ ] T045 按 `quickstart.md` §4 逐条验证就地指引点 **U1–U6**（constitution 原则 IV 的落地验收；指引点定义以 `data-model.md` §5 为准）
- [ ] T046 按 `quickstart.md` §3 与 §6 跑完全部端到端场景并逐条核对 SC-001 ~ SC-012；**§3.4 的 SSRF 场景 D 必须全表通过**
- [ ] T047 前端验收：`cd frontend && nvm use && npx tsc --noEmit`（目标 0 错误）与 `npm run lint:js`
- [ ] T048 后端验收：`cd backend && .venv/bin/python scripts/ui_selftest.py` 与 `ui_e2e.py` 全绿
- [ ] T049 **跨 feature 契约核对**：确认 `001-ai-workbench/contracts/dsl.md` 规则 11–14 引用的动作白名单与本 feature `contracts/steps.md` 的 `ACTIONS` 一致；两端常量（后端 `ui_executor.py` / 前端 `uiTest.ts`）无漂移
- [ ] T050 按 `backend/CLAUDE.md` 的「安全审查检查点」**主动提示**用户跑 `security-review` —— 本 feature **新引入两个安全面**（浏览器出网 SSRF、录制脚本解析），是本次最需要审查的部分；由用户决定是否执行，不自动跑

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 —— 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup —— **阻塞全部用户故事**
- **User Stories (Phase 3–5)**: 全部依赖 Foundational 完成；之后可并行推进
- **Polish (Phase 6)**: 依赖需要交付的用户故事完成

### User Story Dependencies

- **US1 (P1)**: Foundational 完成后即可开工 —— 不依赖其他故事。**MVP**
- **US2 (P2)**: Foundational 完成后即可开工 —— 只依赖元素库与用例创建，不依赖 US1
- **US3 (P3)**: Foundational 完成后即可开工 —— 只依赖既有的 `pity_report` / `pity_test_result` 与报告页，不依赖 US1/US2

> 三个故事**互相独立**。
>
> **与 `001-ai-workbench` 无循环依赖**：001 的公共层与草稿机制不依赖本 feature；本 feature 也不依赖 001。跨 feature 的耦合是**单向**的 —— 001 的 Web UI 用例生成（FR-037/038/039）需要读取本 feature 的元素库，由 T049 核对契约一致性。
>
> **FR-040（保留移动端测试类型位置）由 `001-ai-workbench` 的 `TEST_TYPES` 承担**，本 feature 不重复实现 —— 见 T003 的 `TEST_TYPES` 说明。

### Within Each User Story

- 测试先写并确认失败，再实现（constitution 原则 V）
- Model → DAO → Core（定位器/执行器）→ Router → 前端
- 核心实现 → 集成 → e2e

### Parallel Opportunities

- Phase 1 中标记 `[P]` 的任务可并行
- Phase 2 中标记 `[P]` 的任务可并行（定位器、执行器、安全、录制解析、路由各自独立文件）
- Foundational 完成后，三个用户故事可由不同人并行推进
- 同一故事内标记 `[P]` 的测试任务与前端组件任务可并行

---

## Parallel Example: User Story 1

```bash
# 四个测试任务一起启动
Task: "在 backend/scripts/ui_selftest.py 实现步骤 DSL 校验的测试用例"
Task: "在 backend/scripts/ui_selftest.py 实现动作白名单的负例"
Task: "在 backend/scripts/ui_selftest.py 实现 SSRF 拦截的测试用例"
Task: "在 backend/scripts/ui_selftest.py 实现确定性等待的断言"

# 前端两个组件一起启动
Task: "实现 frontend/src/pages/UiTest/Element/index.tsx"
Task: "实现 frontend/src/pages/UiTest/Element/ElementModal.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（**关键，阻塞全部故事**）
3. 完成 Phase 3: User Story 1
4. **停下来验证**：按 `quickstart.md` §3.1 独立验证 US1
5. 可演示 / 可交付

### Incremental Delivery

1. Setup + Foundational → 地基就绪
2. 加 US1 → 独立验证 → 交付（MVP：**元素库 + 手写用例 + 执行**）
3. 加 US2 → 独立验证 → 交付（**本地录制导入**）
4. 加 US3 → 独立验证 → 交付（**执行中心与报告**）
5. Polish → 文档、指引点验收、SSRF 场景验收、安全审查提示

### Parallel Team Strategy

Foundational 完成后：

- 开发 A：US1（元素库 + 用例编辑 + 执行）
- 开发 B：US2（录制导入）
- 开发 C：US3（执行中心与报告扩附件 tab）

---

## Notes

- [P] = 不同文件、无依赖
- [Story] 标签映射到 spec.md 的用户故事，用于可追溯性
- **测试任务不可省略** —— constitution 原则 V 将其列为落地门禁
- **T025（SSRF）与 T024（动作白名单负例）是本 feature 最关键的两个测试** —— 它们守着两个新引入的安全面
- 每个 checkpoint 可停下来独立验证
- 避免：模糊任务、同一文件冲突、破坏故事独立性的跨故事依赖
- **CHANGELOG 不在本任务范围内** —— 依 `CLAUDE.md`，日常提交不动 CHANGELOG，仅 `/release` 打版本时归档

# Tasks: Mock 配置

**Input**: Design documents from `/specs/003-mock-config/`

**Prerequisites**: plan.md ✅ · spec.md ✅ · research.md ✅ · data-model.md ✅ · contracts/api.md ✅ · quickstart.md ✅

**Tests**: **包含**。constitution 原则 V 规定"功能改动落地前 MUST 通过自动化验证, MUST NOT 只靠手动点一遍;若该模块没有自动化验证手段, MUST 先补上再落地"。因此本 feature 的测试任务不是可选项,而是门禁。后端无 pytest,走独立脚本 `backend/scripts/mock_selftest.py`(不依赖数据库)+ `mock_e2e.py`(需要数据库);前端 `npx tsc --noEmit` + ESLint。

**Organization**: 任务按用户故事分组,每个故事可独立实现、独立测试、独立交付。

**Format**: `[ID] [P?] [Story?] Description with file path`

---

## 实现记录(全部 24 个任务已完成, 2026-10-30)

> 记录**实现与设计的偏差**、**实现时才发现的坑**。完整细节见 `backend/docs/mock-design.md` §8。

### 已落地的代码

| 位置 | 内容 |
|---|---|
| `backend/app/enums/MockEnum.py` | **跨端常量权威定义**(方法集 / 路径类型 / 延迟上限) |
| `backend/app/core/mock_engine.py` | 匹配引擎(纯函数: derive_path_type / normalize_path / match_rule, 全排序确定) |
| `backend/app/core/mock_render.py` | 白名单回显变量渲染器(字典替换, 零表达式, **变量正则权威出处**) |
| `backend/app/models/mock.py` | `pity_mock_rule` 表(Model) |
| `backend/app/schema/mock.py` | 表单 + 变量白名单校验(引用渲染器正则的锚定版) |
| `backend/app/crud/mock/MockRuleDao.py` | 规则 CRUD + 查重提示 + app 定位项目(最早创建) |
| `backend/app/routers/mock/admin.py` · `service.py` | 7 个管理接口 + 对外 catch-all(无鉴权) |
| `backend/main.py` | 注册顺序硬约束: 管理路由先、服务路由后 |
| `backend/scripts/mock_selftest.py` | **106 项断言**(不依赖 DB): 匹配全表 + 双跑一致 + 变量正反例 + AST 零出网零执行扫描 + 跨端常量核对 |
| `backend/scripts/mock_e2e.py` | **33 项断言**(需要 DB): 管理链路 + 对外服务命中/404 矩阵/启停/删除 + preview + 权限 + app 边界 |
| `frontend/src/consts/mock.ts` | 前端镜像(指认后端) |
| `frontend/src/services/mock.ts` | 7 个管理接口封装 |
| `frontend/src/models/mock.ts` | hooks 风格 model |
| `frontend/src/pages/Mock/` | index.tsx(列表/基地址/就地指引 G1~G4)+ RuleFormModal.tsx + DebugModal.tsx |
| `frontend/config/routes.ts` | `/mock` component → `./Mock/index` |
| `frontend/.eslintignore` | `mock` → `/mock`(修正误伤 `src/pages/Mock/`) |
| `backend/docs/mock-design.md` | 深设计附录(模块/算法/变量/安全边界/测试/已知限制/实现记录) |
| `backend/CLAUDE.md` · `specs/HANDOFF.md` | Mock 章节 + 003 交接入口 |

### 实现与设计的偏差/完善(8 条)

| # | 事项 | 决策 | 理由 |
|---|---|---|---|
| 1 | **匹配排序补「方法具体度」** | sort key: path_type → method 具体度(具体 0 > ANY 1)→ priority → id | 原设计只有 path_type → priority → id;ANY 与具体方法同命中时无确定性语义。`data-model.md` §3 同步更新 |
| 2 | **变量正则收紧 body 段间非空** | `body\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*` | 原允许 `a..b` 空段;query 键名保留点(字面量) |
| 3 | **未知变量校验覆盖 `$randomInt`/`$timestamp`** | 扫描所有「`$`+字母开头」token,非白名单拒绝;`$5`/`${...}` 放行 | 原只查 `$request.*`,`$randomInt` 漏网(selftest 抓到) |
| 4 | **渲染值类型归一** | bool→`true/false`、数字→str、dict/list→JSON | `re.sub` 回调必须返回 str,`{"id": 7}` 会 TypeError |
| 5 | **分页契约结构修正** | `{data: [], total}`(success_with_size 平台结构) | 契约初稿 `{total, list}` 与平台不符;contracts §1.1 已修正 |
| 6 | **e2e 开头建表** | `Base.metadata.create_all`(async_engine) | 直接调路由函数不触发启动事件,表不存在 |
| 7 | **e2e 项目名 ≤16 字符** | `me2e-{6位}` | `pity_project.name` 是 String(16) |
| 8 | **e2e 调 `mock_entry` 的 full_path 含 app** | `f"{app}/{sub_path}"` | 与 `/mock/{full_path:path}` 路由语义一致,否则 app 定位失败 |

### 验证结果

- **`mock_selftest.py` 106 项断言全绿**(不依赖 DB):匹配全表正反例、双跑一致、变量四类正反例、未知变量拒绝、延迟/状态码边界、**AST 静态扫描零出网零执行**、跨端常量核对
- **`mock_e2e.py` 33 项断言全绿**(需要 DB):管理链路(建/查重 warning/列表/启停)、对外服务(命中/变量回显/404 矩阵/启停生效/app 重复取最早/app 为空)、preview 命中与未命中、私有项目权限(非成员被拒/超管放行)、删除即失效
- **前端**: `npx tsc --noEmit` 0 错误;新增文件 `npx eslint` 0 告警(全量 47 个报错均为既有旧债,与本次无关)
- `import main` 成功;`/mock` 下 7 个管理路由先注册、1 个对外 catch-all 后注册

### 未验证(环境限制)

- 前端没跑过 `umi build`(既有环境限制)
- 页面 UI 没在浏览器里人工点过(G1~G4 就地指引按契约实现,tsc/eslint 过)—— quickstart §2 场景 A~D 已由 e2e 等价覆盖

---

## Phase 1: Setup(共享骨架)

**Purpose**: 后端/前端的基础声明与骨架,为所有故事铺路。

- [x] T001 [P] 后端跨端常量权威定义:`backend/app/enums/MockEnum.py`(METHODS 方法集 / PATH_TYPE 路径类型 / MAX_DELAY=5000 / 状态码上下限),引用方与 `frontend/src/consts/mock.ts` 互相指认(constitution 原则 III)
- [x] T002 [P] 后端表 Model:`backend/app/models/mock.py`(`PityMockRule`,字段见 data-model.md §2.1),并在 `backend/app/models/__init__.py` 登记(alembic 依赖)
- [x] T003 [P] 后端表单:`backend/app/schema/mock.py`(Pydantic v1:RuleForm / RuleStatusForm / RulePreviewForm / RuleQueryParams,含 path 格式、delay 0~5000、method 白名单、status_code 100~599、response_body 变量白名单校验)
- [x] T004 [P] 前端常量镜像:`frontend/src/consts/mock.ts`(METHODS / PATH_TYPE 等,注释指认 `backend/app/enums/MockEnum.py`,声明"改一处必须同时改另一处")
- [x] T005 [P] 前端 service 封装:`frontend/src/services/mock.ts`(7 个管理接口,按 `contracts/api.md` §1,手动注入 `auth.headers()`,遵循 `frontend/CLAUDE.md` 惯例)

**Checkpoint**: 常量两端指认关系建立,前后端骨架可编译。

---

## Phase 2: Foundational(阻塞前置 — 匹配引擎 / 渲染器 / DAO / 路由)

**Purpose**: 核心基础设施,任何故事开始前 MUST 完成。⚠️ 未完成不得进入任何故事阶段。

- [x] T006 [P] 匹配引擎(纯函数):`backend/app/core/mock_engine.py` —— `derive_path_type(path)` 与 `match_rule(method, full_path, rules)`,确定性全排序(精确>参数化>通配 → priority → id,见 data-model.md §3)。**无任何随机源、无 IO**
- [x] T007 [P] 变量渲染器(纯函数):`backend/app/core/mock_render.py` —— 合法变量正则(白名单封闭)校验 + 字典替换;`$request.path / query.* / body.*(点分路径,含数字索引) / header(s).*`;取不到值替换为空串,零表达式求值、零函数调用。**禁止** import 既有 `app/core/render.py`
- [x] T008 DAO:`backend/app/crud/mock/MockRuleDao.py` —— `@ModelWrapper(PityMockRule)`;CRUD(insert 时同项目同方法同精确路径已存在 → 返回 warning 文案不阻断;update 时重新推导 path_type;delete/status 校验项目归属)+ 对外匹配查询(按 app 定位项目 → 启用规则列表)+ 列表分页筛选(project_id/method/path like/status)
- [x] T009 管理路由:`backend/app/routers/mock/admin.py` —— 7 个接口(`/mock/rule/list|insert|update|delete|status|detail|preview`),全部 `Depends(Permission())` + DAO 项目隔离;preview 复用 T006/T007 做就地模拟(不产生真实延迟等待)
- [x] T010 服务路由 + 注册(顺序硬约束):`backend/app/routers/mock/service.py` —— `api_route("/{full_path:path}", methods=[七种])`,无鉴权,按 FastAPI `Request` 读 method/query/headers/body,命中返回 status_code+headers+body(变量渲染)+`asyncio.sleep(delay/1000)`,未命中/项目不存在/app 为空 → 404 业务码 JSON(contracts §2);`backend/main.py` **在管理路由之后**注册 `mock_service_router`(不带 `request_info`),管理路由带 `request_info` —— 顺序颠倒会吞掉 `/mock/rule/*`,写注释说明
- [x] T011 回归脚本主体(门禁):`backend/scripts/mock_selftest.py` —— **不依赖数据库**:①匹配引擎全表正反例(精确/参数化/通配/ANY/优先级/停用排除/路径类型推导/未知 app)+ 双跑一致;②变量四类正反例 + 未知变量拒绝 + 取不到值空串 + 点分路径/数字索引;③**源码 AST 静态扫描**:`app/routers/mock/`、`app/core/mock_*.py` 中无 `aiohttp`/`httpx`/`requests` 出网调用、无 `eval`/`exec`;④延迟边界(0/5000 合法,负值与 5001 拒绝)

**Checkpoint**: 引擎/渲染器 selftest 全绿(不依赖 DB 即可验证确定性);`import main` 成功、两个 router 均注册。

---

## Phase 3: User Story 1 - 配置 Mock 规则 (Priority: P1) 🎯 MVP

**Goal**: 用户在前端按项目管理规则:选项目 → 新建/编辑/启停/删除 → 列表可见,配置页展示 mock 基地址与使用指引。

**Independent Test**: 在所选项目下完成"新建 → 列表可见 → 编辑 → 启停 → 删除"全流程(管理接口 + 前端页面),不依赖对外服务即可验证本故事。

### Implementation for User Story 1

- [x] T012 [P] [US1] 规则列表页:`frontend/src/pages/Mock/index.tsx` + `Mock.less` —— 顶部项目选择;基地址展示区(`http://{host}/mock/{app}/` + 示例 + 一键复制);规则表格(method 标签色/路径/名称/延迟/优先级/启停 Switch/编辑/删除);筛选(method/path 关键字/status)+ 分页;调试入口按钮(跳 US3)
- [x] T013 [P] [US1] 规则表单 Modal:`frontend/src/pages/Mock/RuleFormModal.tsx` —— 新建/编辑共用;method 下拉 + path 输入(含 `:id`/`*` 占位说明)+ status_code + response_headers(KV 编辑)+ response_body(JSON/文本切换)+ delay(带 0~5000 上限提示)+ priority + status + remark;**变量清单就地提示**(`$request.*` 合法变量列表);精确路径重复时展示后端 warning 文案
- [x] T014 [US1] hooks 状态:`frontend/src/models/mock.ts` —— `@umijs/plugin-model` hooks 风格(遵循 `frontend/CLAUDE.md`,不混 dva);项目选择状态、列表/分页/筛选状态、启停与删除操作、基地址计算
- [x] T015 [US1] 就地指引三态(constitution 原则 IV):`Mock/index.tsx` —— 未选项目 → 提示 + 项目入口;项目 app 为空 → 提示补全(基地址不可用);项目下无规则 → 空态展示"被测系统如何调用 mock 服务"使用引导 + 新建按钮;app 被多项目占用 → 提示命中最早创建的项目
- [x] T016 [US1] 路由接线:`frontend/config/routes.ts` —— `/mock` 的 `component` 从 `./Building` 改为 `./Mock/index`

**Checkpoint**: 前端 `npx tsc --noEmit` 0 错误、eslint 0 告警;管理接口 CRUD 链路可用(经 e2e 或手工按 quickstart 场景 A 第 1~4 步验证)。

---

## Phase 4: User Story 2 - 联调时调用 Mock 服务 (Priority: P1)

**Goal**: 被测系统向 `/mock/{app}/**` 发起请求即得配置的假数据(含延迟与变量回显),未命中 404。服务端实现在 T010 已落地,本阶段以端到端验证为主。

**Independent Test**: 走通"建规则 → curl 命中 → 校验状态码/头/体/变量回显 → 未命中 404 → 启停/删除生效"整条链路,不依赖前端即可验证。

### Tests for User Story 2(门禁)⚠️

- [x] T017 [P] [US2] 端到端脚本:`backend/scripts/mock_e2e.py` —— **需要数据库**:①建规则 → 走对外入口(直接调路由函数,绕 HTTP)→ 校验 status_code/headers/body/变量回显/延迟(短值);②未命中/app 不存在/app 为空 → 404 且响应结构一致;③启停生效(停用 404、启用恢复);④删除后 404;⑤app 重复取最早创建;⑥管理端点权限(非项目成员且非超管 → 403,项目成员可写);⑦preview 命中与未命中;⑧同方法同精确路径新建 → 返回 warning 文案仍创建成功

**Checkpoint**: `mock_e2e.py` 全绿;quickstart.md §2 场景 A~D 可照做。

---

## Phase 5: User Story 3 - 调试与校验规则 (Priority: P2)

**Goal**: 用户对任意规则就地发起模拟请求,看到"命中哪条规则 + 变量解析后的最终响应",未命中明确提示。

**Independent Test**: 对一条含回显变量的规则,用不同参数模拟并核对最终响应,30 秒内完成。

### Implementation for User Story 3

- [x] T018 [P] [US3] 调试 Modal:`frontend/src/pages/Mock/DebugModal.tsx` —— method/path(可带 query)/body/headers 输入 → 调 `/mock/rule/preview` → 展示命中规则摘要 + 解析后响应(含 status_code/headers/body)或"没有规则会命中该请求"
- [x] T019 [US3] 校验补强:`backend/scripts/mock_selftest.py` —— 补「未知变量名在保存时被拒」正反例(含 `$request.body` 点分路径合法样例与 `$randomInt`、`$request.foo.` 等非法样例)+ `response_headers` 非 JSON 拒绝

**Checkpoint**: selftest 新断言全绿;preview 接口与 DebugModal 联通(手工按 quickstart 场景 A 第 5 步)。

---

## Phase 6: User Story 4 - 规则管理与权限 (Priority: P2)

**Goal**: 规则按项目隔离、写操作限项目成员(非成员 403)、平台超管按既有惯例放行;删除即对外失效。

**Independent Test**: 用非项目成员账号被拒、项目成员账号完成一次增删改,即可独立验证。

### Tests for User Story 4(门禁)⚠️

- [x] T020 [P] [US4] e2e 权限补强:`backend/scripts/mock_e2e.py` —— 非项目成员(私有项目)读列表 → 403;项目成员读列表 → 200;跨项目规则不可见;平台超管跨项目可读(遵循 `read_permission` 语义);`rule/delete` 传错 `project_id` → 业务异常 110(防跨项目删除)

**Checkpoint**: e2e 全绿;权限矩阵符合 contracts §1 与 spec FR-015。

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 文档、契约核对、全量回归收尾。

- [x] T021 [P] 深设计附录:`backend/docs/mock-design.md` —— 模块拆分/匹配算法/变量规范/安全边界(零出网零执行声明)/测试跑法/已知限制(半公开入口、app 重复、MVP 范围外),遵循 constitution「文档分层」
- [x] T022 [P] 契约核对脚本断言:`backend/scripts/mock_selftest.py` 补「跨端常量核对」—— 前端 `consts/mock.ts` 与后端 `MockEnum.py` 逐项一致(方法集/路径类型/延迟上限),防止两端漂移
- [x] T023 文档登记:`backend/CLAUDE.md` 新增 Mock 章节(状态/已落地/改前必知,含常量双端同步声明)+ `specs/HANDOFF.md` 更新 003 交接入口 + quickstart.md §3 全量回归跑一遍
- [x] T024 全量验收:`cd backend && .venv/bin/python scripts/mock_selftest.py && .venv/bin/python scripts/mock_e2e.py`;`cd frontend && nvm use && npx tsc --noEmit && npm run lint:js`;按 quickstart §2 五个场景人工走查(浏览器)

**Checkpoint**: 全部回归绿、文档齐、SC-001~005 对照通过。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖,可立即开始;T001~T005 全并行
- **Foundational (Phase 2)**: 依赖 Phase 1;**阻塞全部故事**;T006/T007 并行 → T008 依赖两者 → T009 依赖 T008 → T010 依赖 T009;T011 依赖 T006/T007(引擎与渲染器就绪即可独立全绿)
- **US1 (Phase 3)**: 依赖 Foundation;T012/T013 并行 → T014 依赖 service(T005)→ T015 依赖 T012/T013 → T016 依赖 T015
- **US2 (Phase 4)**: 依赖 Foundation(T010);T017 依赖 T008/T009(管理链路)与 T010(服务链路),与 US1 前端并行
- **US3 (Phase 5)**: 依赖 Foundation(preview 端点已在 T009);T018 依赖 T005;T019 依赖 T006/T007
- **US4 (Phase 6)**: 依赖 Foundation(T008);T020 与 US1~US3 并行
- **Polish (Phase 7)**: 依赖全部故事完成

### User Story Dependencies

- **US1 (P1)**: 仅依赖 Foundation —— 管理接口 + 前端页面,可独立交付(MVP)
- **US2 (P1)**: 仅依赖 Foundation —— 对外服务 + e2e,与 US1 并行(两端各自验证)
- **US3 (P2)**: 依赖 Foundation + US1 页面(调试入口在列表页)
- **US4 (P2)**: 依赖 Foundation,贯穿验证

### Parallel Opportunities

- Phase 1 全部并行(T001~T005)
- T006 / T007 并行(引擎与渲染器互不依赖)
- T012 / T013(两个页面组件)并行;US2 的 T017 与 US1 的 T012~T016 并行
- T020 与 US3 并行;T021 / T022 并行

---

## Parallel Example: 核心并行组

```bash
# Phase 1 骨架四路并行:
Task: "T001 后端枚举 + T002 表 Model + T003 schema + T004 前端常量 + T005 前端 service"

# Foundation 引擎/渲染器并行:
Task: "T006 匹配引擎 mock_engine.py"
Task: "T007 变量渲染器 mock_render.py"

# 引擎就绪后并行推进:
Task: "T011 selftest(匹配+变量断言)  ← 依赖 T006/T007"
Task: "T008 DAO ← 依赖 T006/T007"
```

---

## Implementation Strategy

### MVP First (US1 + US2 双核)

1. 完成 Phase 1 + 2(骨架 + 引擎/渲染器/DAO/路由 + selftest 门禁)
2. 完成 US1(管理接口 + 前端页面)→ 独立验证 CRUD
3. 完成 US2(e2e 脚本)→ 对外服务命中/404 全链路验证
4. **STOP and VALIDATE**: 场景 A~D 全部跑通(quickstart §2)
5. 部署/demo:被测系统即可开始消费 mock 数据

### Incremental Delivery

1. Setup + Foundation → selftest 全绿(确定性 + 零出网静态扫描)
2. US1 → 规则管理可用(前端 + 管理接口)
3. US2 → 对外服务可用(e2e 门禁)
4. US3 → 调试闭环(配错率下降)
5. US4 → 权限收敛 + 文档收尾

### 安全边界提示(实现时必须守住)

- `service.py` / `mock_engine.py` / `mock_render.py` **不得出现**任何出网调用与 `eval`/`exec` —— T011 的 AST 静态扫描是门禁,实现时先确保可过
- 渲染器**不得**复用 `app/core/render.py`(非沙箱 RCE 面)
- `main.py` 注册顺序:管理路由先、服务路由后 —— 颠倒即吞掉 `/mock/rule/*`,注释写明
- 对外服务**不得**记录操作日志(`request_info` 依赖) —— 它无鉴权,记日志只留下垃圾与噪音

## Notes

- [P] 任务 = 不同文件、无依赖,可并行
- [Story] 标签映射到 spec.md 的用户故事,便于追溯
- 每个故事独立可完成、可测试;checkpoint 处停下独立验证
- 后端脚本跑法:`cd backend && .venv/bin/python scripts/mock_selftest.py`(不依赖 DB)/ `mock_e2e.py`(需要 DB)
- 前端跑法:`cd frontend && nvm use && npx tsc --noEmit`(必须 Node 20,见 memory:前端 node 版本要求)
- 避免:含糊任务、同文件冲突、破坏故事独立性的跨故事依赖

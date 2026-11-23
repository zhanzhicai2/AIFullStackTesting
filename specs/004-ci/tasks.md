# Tasks: 持续集成（外部 CI 对接）

**Input**: Design documents from `/specs/004-ci/`

**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/api.md](./contracts/api.md) · [quickstart.md](./quickstart.md)

**Tests**: **包含测试任务** —— spec FR-033 与 constitution GATE-V 明确要求「MUST 通过自动化回归验证，MUST NOT 只靠手动点一遍」，故按既有项目模式生成 `ci_selftest.py`（无 DB）与 `ci_e2e.py`（有 DB）相关任务。

**Organization**: 按用户故事分组，每个故事可独立实现与验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 归属用户故事（US1~US4，对应 spec.md）
- 每条任务带**精确文件路径**；表字段约束引自 `data-model.md`，不留到实现期临场发挥

## 关键约束（实现时不可偏离，来自 plan.md / research.md）

1. **等待语义用 `asyncio.wait(tasks, timeout=)`，禁止 `asyncio.wait_for`** —— 后者超时会 `cancel()`，违反 FR-011（research D3）
2. **凭据只存 `sha256(明文)`，明文仅签发响应出现一次**（FR-002/008，research D1）
3. **`Executor.run_test_plan` 的 `raise_on_error` 默认 `False`** —— 既有 cron 与 `/plan/execute` 路径行为一字不变（research D4）
4. **`Permission()` 一行不改** —— 新增独立 `CIPermission()`（research D2）
5. **一期零出网** —— `callback_url` 只存不发（决定 Q5，research D9）
6. **`111` 测试未通过 / `112` 等待超时 / `3` 与 `5` 语义分离**（contracts §0、§3.2）

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 跨端常量的单一权威出处（GATE-III）

- [X] T001 [P] Create `backend/app/enums/CiEnum.py` —— 权威定义 `CI_NOT_PASSED=111`、`CI_WAIT_TIMEOUT=112`、`RunStatus` 六态（0 PENDING / 1 RUNNING / 2 SUCCESS / 3 FAILED / 4 TIMEOUT / 5 ERROR）、`TOKEN_PREFIX="pity_ci_"`、`TOKEN_DEFAULT_EXPIRE_DAYS=365`、`WAIT_TIMEOUT_DEFAULT_SEC=300`、`WAIT_TIMEOUT_MAX_SEC=1800`；文件头注释指认 `specs/004-ci/contracts/api.md`
- [X] T002 [P] Create `frontend/src/consts/ci.ts` —— 镜像 T001 全部常量 + 六态的前端文案与颜色映射（`3` 红·未通过 / `5` 灰·执行失败），文件头注释指认 `backend/app/enums/CiEnum.py` 为权威出处（GATE-III）
- [X] T003 [P] 在 `backend/CLAUDE.md` 与 `frontend/CLAUDE.md` 各补一条硬约定：「CI 业务码 `111`/`112` 与 `RunStatus` 六态的权威定义在 `backend/app/enums/CiEnum.py`，前端镜像 `src/consts/ci.ts`，**改一处 MUST 同步改另一处**」

**Checkpoint**: 两端常量就位且互相指认

---

## Phase 2: Foundational（阻塞性前置）

**Purpose**: 所有用户故事共同依赖的底座

**⚠️ CRITICAL**: 本阶段未完成前，任何用户故事都不得开工

- [X] T004 Create `backend/app/models/ci.py` —— 两张表 `PityCiIntegration`（`project_id` index、`name` VARCHAR(32)、`token_hash` CHAR(64) **unique**、`token_prefix` VARCHAR(12) index、`plan_id` 可空 index、`callback_url` VARCHAR(255) 可空、`enabled` BOOLEAN 默认 1、`expires_at` 可空、`last_used_at` 可空；唯一约束 `project_id+name+deleted_at`）与 `PityCiRun`（`integration_id`/`project_id`/`plan_id`/`env`/`external_build_id` VARCHAR(64)/`external_url` VARCHAR(255)/`status` SMALLINT 默认 0/`report_ids` TEXT/四计数 INT/`pass_rate` SMALLINT 默认 0/`error_msg` VARCHAR(500)/`started_at`/`finished_at`/`cost` VARCHAR(8)/`waited` BOOLEAN 默认 0；复合索引 `(project_id, created_at)`），均继承 `PityBase`，约束逐条照 `data-model.md` §2.1/§2.2
- [X] T005 [P] Create `backend/app/schema/ci.py` —— Pydantic **v1** 表单：集成 CRUD（`name` ≤32、`plan_id` 归属校验、`callback_url` ≤255、`expires_at` 可空）与触发请求（`plan_id`/`env`/`wait` 默认 false/`timeout_sec` 默认 300 上限 1800 下限 1/`external_build_id` ≤64/`external_url` ≤255），校验失败走 `101`
- [X] T006 [P] Implement `CIPermission()` in `backend/app/routers/__init__.py` —— 读 `token` header，按 `contracts/api.md` §1.3 七步校验链（前缀 → `sha256` 等值查 `token_hash` → `deleted_at=0` → `enabled` → `expires_at` → 项目作用域 → 更新 `last_used_at`），四种拒绝分别返回 `401 "CI 凭据无效"` / `401 "CI 凭据已停用"` / `401 "CI 凭据已过期"` / `403 "无权触发该项目的测试计划"`；**返回结构与 `Permission()` 完全一致**，`Permission()` 本体一行不改
- [X] T007 Modify `backend/app/core/executor.py` 的 `run_test_plan` —— 签名改为 `run_test_plan(plan_id, executor=0, *, raise_on_error=False)`；成功时 `return report_dict`（含各环境 `plan_result` 与 `report_id`）；`raise_on_error=True` 时异常上抛、否则保持既有「`log.exception` 后返回」语义 —— **既有两个调用方（`testplan.py:75` 的 `create_task`、`scheduler.py` 的 cron）行为必须一字不变**
- [X] T008 Modify `backend/app/__init__.py` 的 `lifespan` —— 在第 3 步 `create_table()` 之后加**第 5 步**：`UPDATE pity_ci_run SET status=5, error_msg='平台重启导致执行中断', finished_at=now() WHERE status IN (0,1) AND deleted_at=0`；失败只 `log.exception` 不抛（同「注册内置 UI 执行节点」处理，不拖垮启动）
- [X] T009 [P] Create `backend/scripts/ci_selftest.py` 骨架 —— 参照 `mock_selftest.py` 的 `check()` 打印格式，含**源码静态扫描**四条断言：①无明文凭据落库 ②一期零出网（源码无 `aiohttp`/`httpx`/`requests`）③无 `exec`/`eval` ④等待用 `asyncio.wait` 而非 `wait_for`

**Checkpoint**: 底座就位 —— 用户故事可并行开工

---

## Phase 3: User Story 1 - 签发并管理接入凭据 (Priority: P1) 🎯 MVP

**Goal**: 项目管理员能在 `/ci` 页面签发长期凭据（明文仅一次）、绑定默认计划、启停删除，列表只显示前缀

**Independent Test**: 在一个项目下走「新建集成 → 拿到凭据 → 列表只见前缀 → 停用 → 用停用凭据调用被 401」完整一遍

### Tests for User Story 1

> 先写测试并确认失败，再实现（GATE-V）

- [X] T010 [US1] Extend `backend/scripts/ci_selftest.py` —— 凭据校验链正反例：`pity_ci_` 前缀缺失 / 摘要不匹配 / `deleted_at≠0` / `enabled=0` / `expires_at` 已过 / 跨项目 → 断言六种 `code`+`msg` 各不相同且**不回显任何凭据内容**（对应 `contracts/api.md` §1.3）

### Implementation for User Story 1

- [X] T011 Create `backend/app/crud/ci/CiIntegrationDao.py` —— `@ModelWrapper(PityCiIntegration)`；签发（`secrets.token_hex(16)` + `sha256`，**注释显式标注 token 不可重放（安全属性，非缺陷）**，对应 constitution 原则 I 豁免条款）、按 `token_hash` 等值校验、停用/启用、更新 `last_used_at`、列表按 `project_id` 隔离
- [X] T012 Create `backend/app/routers/ci/integration.py` —— `APIRouter(prefix="/ci")`，五个端点 `GET /integration/list`、`POST /integration/insert`（**明文仅此一次返回**）、`POST /integration/update`（**不接受任何凭据字段**）、`GET /integration/switch`、`GET /integration/delete`（逻辑删除），全部 `Depends(Permission(Config.MANAGER))`，`insert` 校验 `plan_id` 归属 `project_id` 否则 `110`
- [X] T013 Create `backend/app/routers/ci/__init__.py` 汇总导出 `router`，并在 `backend/main.py` 注册 `pity.include_router(ci_router, dependencies=[Depends(request_info)])`（**须在既有管理路由之后、不与 mock catch-all 顺序冲突**）
- [X] T014 [P] Create `frontend/src/services/ci.ts` —— 封装 `contracts/api.md` 全部 8 个端点，请求头走 `auth.headers()` 注入 `token`，响应类型按契约 `data` 结构定义（`RunStatus` 从 `@/consts/ci` 取）
- [X] T015 [P] Create `frontend/src/models/ci.ts` —— **hooks 风格**（`@umijs/plugin-model`，不混 dva），状态：`projectId` / 集成分页 / `loading` / 一次性明文 `justIssuedToken`（签发后置入、关闭即清空），切换项目即重拉
- [X] T016 Create `frontend/src/pages/ci/index.tsx` + `frontend/src/pages/ci/index.less` —— 三 tab 容器（集成配置 / 接入示例 / 触发历史），顶部项目选择器；**G1 未选项目时就地提示 + 项目入口，不渲染任何空表格**（FR-029）
- [X] T017 Create `frontend/src/pages/ci/IntegrationPanel.tsx` —— 集成列表（列：名称、`token_prefix`、绑定计划、启用开关、有效期、最后使用时间）+ 签发弹窗（**明文一次性展示 + 复制按钮，关闭后不可再取**）+ 停用/删除；**G2 无集成配置**与 **G3 无测试计划**就地指引，两者并列时按「先计划、后凭据」排序（`data-model.md` §7）
- [X] T018 Modify `frontend/config/routes.ts` 第 301~305 行 —— `/ci` 的 `component: './Building'` → `'./ci'`，并给该路由加 `authority: ['admin', 'superAdmin']`（FR-028）
- [X] T019 [P] Run `backend/scripts/ci_selftest.py` —— 无 DB 部分全绿；同时跑 `npx tsc --noEmit` 确认 0 错误

**Checkpoint**: US1 独立可验 —— 凭据全生命周期 + 页面可见

---

## Phase 4: User Story 2 - 流水线触发测试并据此阻断 (Priority: P1)

**Goal**: 外部系统凭凭据触发测试计划，拿到 `0`/`111`/`112`/`401`/`403` 等可区分结论并阻断构建

**Independent Test**: 用一份真实 `curl` 触发含失败用例的计划 → `code=111`；触发全通过的计划 → `code=0`；两者单次返回即可判定

### Tests for User Story 2

- [X] T020 [US2] Create `backend/scripts/ci_e2e.py` —— 需 DB。链路：签发凭据 → `POST /ci/run`（`wait=true`）→ 断言 `code`/`data.status`/`report_ids`/`report_url` → `GET /ci/run/{id}` 断言字段齐全 → 历史可查（参照 `mock_e2e.py` 的 `check()` 格式）
- [X] T021 [US2] Extend `backend/scripts/ci_selftest.py` —— 业务码映射断言（`0`/`101`/`110`/`111`/`112`/`401`/`403` 七档齐全）、`RunStatus` 六态齐全且 **`3`（测试未通过）与 `5`（执行失败）不混淆**、`run_test_plan` 源码断言（有 `return report_dict`、有 `raise_on_error` 且默认 `False`）
- [X] T022 [US2] Extend `backend/scripts/ci_e2e.py` —— 拒绝类六条：停用 → `401 已停用`、过期 → `401 已过期`、随机串 → `401 无效`、跨项目 → `403`、计划不存在 → `110`、重复触发 → `110`；断言**均不回显凭据**
- [X] T023 [US2] Extend `backend/scripts/ci_e2e.py` —— 超时场景：长用例 + `timeout_sec=5` → `code=112`、`data.wait_timeout=true`、随后轮询落到 `2` 或 `3`，**证明执行未被中断**（FR-011）
- [X] T024 [US2] Extend `backend/scripts/ci_e2e.py` —— 重启恢复：手工把一条记录改 `status=1` → 重启 → 断言收敛为 `status=5` 且 `error_msg='平台重启导致执行中断'`（FR-031）
- [X] T025 [US2] Extend `backend/scripts/ci_e2e.py` —— 并发防重：并发对同一 `plan_id` 发两次触发，断言**只成功一次**、另一次 `110`（SC-010）

### Implementation for User Story 2

- [X] T026 Create `backend/app/crud/ci/CiRunDao.py` —— `@ModelWrapper(PityCiRun)`；建记录（`status=0`）、置 `1 running`、回填（计数/`pass_rate`/`report_ids`/`cost`/`finished_at`/终态）、防重查询 `WHERE plan_id=? AND status IN (0,1) AND deleted_at=0`、按 `id` 查
- [X] T027 Create `backend/app/core/ci_runner.py` —— 编排：防重判定（`plan.state` + `CiRunDao` 双层，`research D7`）→ 建记录 → 置 running → **`task = asyncio.ensure_future(...)` 后 `await asyncio.wait({task}, timeout=timeout_sec)`**（**禁止 `asyncio.wait_for`**，超时与 handler 被取消都不中断执行）→ 回填；超时的 `task` 存入模块级强引用集合防 GC；`raise_on_error=True` 把异常转 `status=5`
- [X] T028 Create `backend/app/routers/ci/run.py` —— `POST /ci/run`（`wait` 默认 false、`timeout_sec` 默认 300 上限 1800；通过 `0`/`111`/`112`/`110` 返回，`data` 结构照 `contracts/api.md` §3.1）与 `GET /ci/run/{id}`（§3.2 同构），全部 `Depends(CIPermission())`
- [X] T029 Modify `backend/main.py` —— 若 T013 未覆盖则补注册 `run.py` 的路由（同一 `ci_router` 汇总）
- [X] T030 [P] Run `backend/scripts/ci_selftest.py` + `backend/scripts/ci_e2e.py` —— 两脚本全绿

**Checkpoint**: US2 独立可验 —— 一条 `curl` 就能阻断流水线

---

## Phase 5: User Story 3 - 追溯触发历史与结果 (Priority: P2)

**Goal**: 在 `/ci` 历史 tab 按项目/时间翻页查看每次触发，外部构建号可跳、报告入口可进既有报告页

**Independent Test**: 连续触发两次不同结果的执行，在历史中按项目筛选并核对字段与跳转

### Tests for User Story 3

- [X] T031 [US3] Extend `backend/scripts/ci_e2e.py` —— 历史字段完整率 100%（每次触发都有记录与报告入口，SC-005）、分页不重不漏、**项目隔离**（A 项目凭据查不到 B 项目记录）
- [X] T032 [US3] Extend `backend/scripts/ci_e2e.py` —— 造 1000 条记录后分页查询计时 **< 1 秒**（SC-009）
- [X] T033 [US3] Extend `backend/scripts/ci_selftest.py` —— `RunStatus` → 前端文案/颜色映射一致性断言（`3` 红·未通过、`5` 灰·执行失败，读 `frontend/src/consts/ci.ts` 比对）

### Implementation for User Story 3

- [X] T034 [US3] Extend `backend/app/crud/ci/CiRunDao.py` —— 分页查询 `WHERE project_id=? AND created_at BETWEEN ? AND ? [AND plan_id=?] [AND status=?] ORDER BY created_at DESC LIMIT/OFFSET`，用复合索引 `(project_id, created_at)`
- [X] T035 [US3] Extend `backend/app/routers/ci/run.py` —— `GET /ci/run/list`（`project_id` 必填否则 `101`；`page`/`size`/`plan_id`/`status`/`start_time`/`end_time`；`PityResponse.success_with_size`，`total` 在顶层，**响应不含 `token_hash`**）
- [X] T036 [P] [US3] Create `frontend/src/pages/ci/RunHistoryPanel.tsx` —— ProTable：时间、计划、`external_build_id`（超链 `external_url`）、结果（用 `@/consts/ci` 的六态色）、耗时、报告入口（`Config.SERVER_REPORT + report_id`）、`error_msg` 展开
- [X] T037 [US3] Extend `frontend/src/services/ci.ts` 与 `frontend/src/models/ci.ts` —— 历史分页查询 + 筛选状态 + 项目切换即重拉
- [X] T038 [US3] Extend `frontend/src/pages/ci/index.tsx` —— 挂载 `RunHistoryPanel`，**G4 无触发记录时展示接入示例 + 「如何触发第一次」三步说明**，而不是空白

**Checkpoint**: US1+US2+US3 全部独立可验

---

## Phase 6: User Story 4 - 一键复制接入示例 (Priority: P2)

**Goal**: 选中集成配置后直接看到可粘贴的 Jenkinsfile 与 GitHub Actions 片段，地址与计划名自动填、凭据恒占位符、一键复制

**Independent Test**: 复制片段粘进空白流水线文件，核对占位符与结构完整，全程不看文档

### Tests for User Story 4

- [X] T039 [US4] Extend `backend/scripts/ci_selftest.py` —— 片段断言：①含 `YOUR_PITY_CI_TOKEN` 占位符 ②**不含** `pity_ci_` + 32 位 hex 的真实凭据形态 ③两段流水线语法关键字齐全（`httpRequest`/`customHeaders`、`curl`/`-H "token:`）④`plan_id` 为当前配置真实值

### Implementation for User Story 4

- [X] T040 [P] [US4] Create `frontend/src/pages/ci/SnippetsPanel.tsx` —— Jenkinsfile 与 GitHub Actions 两段片段；`PITY_URL` 与 `plan_id`/`plan_name` 自动填当前配置真实值，**`PITY_CI_TOKEN` 恒为占位符并提示去集成配置复制**（D10）；一键复制 + 成功反馈；未选集成时就地提示先创建（G2）
- [X] T041 [US4] Extend `frontend/src/services/ci.ts` —— 片段渲染所需数据（当前集成配置 + 项目下测试计划列表）；无计划时给 G3 入口
- [X] T042 [US4] Extend `frontend/src/pages/ci/index.tsx` —— 挂载 `SnippetsPanel`，与 US3 的 `RunHistoryPanel` 同容器共存

**Checkpoint**: 四个用户故事全部独立可验

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 文档、全量回归、安全审查提示

- [X] T043 [P] Create `backend/docs/ci-design.md` —— 深设计附录（constitution「文档分层」指定落点）：D1~D10 决策摘要、状态机、脱敏表、已知限制
- [X] T044 [P] Update `specs/HANDOFF.md` —— 增加 `004-ci` 段落（状态、入口文件、权威顺序指针）
- [X] T045 [P] Update `specs/004-ci/proposal.md` T01~T09 —— 回填实际完成状态与偏差说明
- [X] T046 Run `cd backend && .venv/bin/python scripts/ci_selftest.py` —— 全绿（无 DB）
- [X] T047 Run `cd backend && .venv/bin/python scripts/ci_e2e.py` —— 全绿（需 DB）
- [X] T048 Run `cd backend && .venv/bin/python -c "import main"` —— 导入无误（验收口径见 `specs/004-ci/quickstart.md` §2）
- [X] T049 Run `cd frontend && npx tsc --noEmit && npm run lint` —— tsc **0 错误**、eslint 0 告警（验收口径见 `frontend/CLAUDE.md`「TypeScript 检查」）
- [ ] T050 Run `specs/004-ci/quickstart.md` §3 场景 A~G 人工验证 —— 逐条对照 §4 的 SC-001~SC-012
- [ ] T051 **提示用户决定是否执行 `security-review`** —— 触发条件见 `backend/CLAUDE.md`「安全审查检查点」，本特性四条全命中（新增 8 个路由接口 / 新增鉴权判断 / 新增外部输入面 / 新增敏感数据存储）；按 constitution 由**人决定**，不自动执行；**建议在 T029（US2 实现完成）后、T046（全量回归）前跑一次**

---

## Dependencies & Execution Order

### Phase Dependencies

| Phase | 依赖 | 阻塞 |
|---|---|---|
| 1 Setup (T001~T003) | 无 | 全部 |
| 2 Foundational (T004~T009) | Phase 1 | **全部用户故事** |
| 3 US1 (T010~T019) | Phase 2 | US3（历史需要集成配置作上下文） |
| 4 US2 (T020~T030) | Phase 2（**不依赖 US1**：`CIPermission` 与 `ci_runner` 只需模型与 DAO） | US3（历史需要 `pity_ci_run` 数据） |
| 5 US3 (T031~T038) | Phase 2 + US2（需已有触发数据） | US4（同容器挂载） |
| 6 US4 (T039~T042) | Phase 1 + US1（需集成配置数据） | Phase 7 |
| 7 Polish (T043~T051) | 全部 | — |

### User Story Dependencies

- **US1 (P1)**: Phase 2 后即可开工，不依赖其他故事 —— **MVP**
- **US2 (P1)**: Phase 2 后即可开工，不依赖 US1（测试可用 DAO 直接造凭据）
- **US3 (P2)**: 依赖 US2 产生 `pity_ci_run` 数据
- **US4 (P2)**: 依赖 US1 产生集成配置；与 US3 同容器但不同文件

### Within Each User Story

测试先写并确认失败 → 模型/DAO → 服务编排 → 端点 → 前端 → 该故事回归全绿再进下一阶段

### Parallel Opportunities

- Phase 1 三条 `[P]` 全并行（不同文件）
- Phase 2 中 T005 / T006 / T009 与 T004 并行（不同文件）
- US1 中 T014 / T015 并行，T019 与实现并行
- US2 中 T026 与 T027 需顺序（`ci_runner` 依赖 `CiRunDao`），但 T020~T025 的测试编写可与实现并行
- US3 中 T036 与 T034/T035 并行（前端 vs 后端）
- US4 中 T040 与 T041 并行
- Phase 7 中 T043 / T044 / T045 三份文档全并行

---

## Parallel Example: User Story 1

```bash
# 三条 Setup 一起起:
Task: "Create backend/app/enums/CiEnum.py"
Task: "Create frontend/src/consts/ci.ts"
Task: "Update backend/CLAUDE.md + frontend/CLAUDE.md 同步约定"

# US1 两条前端一起起:
Task: "Create frontend/src/services/ci.ts"
Task: "Create frontend/src/models/ci.ts"
```

---

## Implementation Strategy

### MVP First（US1 + US2 合起来才构成 MVP）

> **注意**：本特性的价值闭环是「签发凭据（US1）+ 触发并判定（US2）」—— 只做 US1 得到的是一个凭据管理台，**没有可消费的触发能力**；只做 US2 则没有凭据可签。两者合起来才是 `proposal.md` §5.1 定义的「让一条 Jenkinsfile 真的能跑通」。

1. 完成 Phase 1 Setup + Phase 2 Foundational（**CRITICAL，阻塞全部**）
2. 完成 Phase 3 US1 + Phase 4 US2
3. **STOP and VALIDATE**：跑 `quickstart.md` 场景 A/B/E + 三步回归命令
4. 此时已可交付 —— 一条真实 `curl` 能阻断流水线

### Incremental Delivery

1. Setup + Foundational → 底座就绪
2. **US1 + US2 → 场景 A/B/E 全绿 → 可交付（MVP）**
3. US3 → 历史可查 → 增量 1
4. US4 → 接入示例一键复制 → 增量 2（SC-001/SC-012 达成）
5. Phase 7 → 全量回归 + 文档 → 收尾

---

## Notes

- `[P]` = 不同文件、无未完成依赖
- `[Story]` 标签用于追溯到 spec 的用户故事
- 每个用户故事应可独立完成与验证；US1/US2 是最小可交付组合
- **禁止**：把 `asyncio.wait_for` 用进 `ci_runner`（违反 FR-011）、把明文 token 写进任何列或日志、改 `Permission()` 本体、改 `pity_report` 表结构
- 提交按任务或逻辑组走 Conventional Commits；在任意 Checkpoint 停下独立验证

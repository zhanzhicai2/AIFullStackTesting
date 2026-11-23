# 持续集成（CI）特性计划书

**状态**：**已确认（2026-11-23）** —— §9 五项决定全部通过，Spec Kit 流程已启动，`spec.md` / `plan.md` / `tasks.md` / `contracts/` 陆续产出
**日期**：2026-11-23 · **分支**：`main`
**定位**：外部 CI 对接 —— 让 Jenkins / GitHub Actions / GitLab CI 能非交互式触发平台的测试计划，并按通过/失败阻断构建

---

## 0. 一句话

`/ci` 菜单目前是占位页。本特性给平台开一条**机器可调用的测试执行通道**：外部 CI 拿一个长期有效的 Token 调 `POST /ci/run`，平台跑完测试计划后回传通过率与报告链接，CI 据此 `exit 1` 阻断流水线；平台侧留触发记录，并在 `/ci` 页面上完成 Token 签发、接入示例复制与历史查询。

**不是**「平台自己监听 Git webhook 编排流水线」—— 那是内建流水线，工作量与安全面完全另一档，列为二期备选（§5.2），本计划书不展开。

---

## 1. 现状（实测，2026-11-23）

### 1.1 功能侧：零实现

| 层 | 实测结果 |
|---|---|
| 前端路由 | `frontend/config/routes.ts:301` → `component: './Building'`，占位页文案「努力建设中...」（`src/pages/Building.jsx`）。全站仅 `/ci`、`/precise` 两处占位 |
| 前端页面 | `frontend/src/pages/ci/` **不存在**；`src/services/`、`src/models/` 下无任何 ci 文件 |
| 后端路由 | `backend/app/routers/` 下**无 `ci` 模块**，`main.py` 的 16 条 `include_router` 里没有 CI |
| 规格 | `specs/` 只有 `001-ai-workbench` / `002-ui-automation` / `003-mock-config`，**无 004**；`specs/HANDOFF.md` 全文未提 CI |
| 历史 | `git log --grep=持续集成`（`--all`）为空，从未动过 |
| 文档 | 全仓库 grep「持续集成」只命中 `frontend/CLAUDE.md:100` 路由表一行；Obsidian vault 里 `DEPLOY_AND_CI.md` 讲的是**本平台自己的部署流水线**，与本特性无关 |

### 1.2 可复用的地基（这些已经有，不用重造）

| 能力 | 位置 | 说明 |
|---|---|---|
| 触发测试计划 | `app/routers/testcase/testplan.py:73` `GET /testcase/plan/execute` | 已能按 `plan_id` 触发 |
| 执行主体 | `app/core/executor.py:545` `Executor.run_test_plan()` | 内部 `await asyncio.gather(...)`，**会等全部环境跑完**才继续 |
| 报告模型 | `app/models/report.py` `pity_report` | 有 `status`(0 pending / 1 running / 2 stopped / 3 finished)、`success_count` / `failed_count` / `error_count` / `skipped_count`、`plan_id`、`cost` |
| 通过/未通过判定 | `app/core/executor.py:619` | `run_multiple` 已算出 `report_dict[env]["plan_result"]` = `"通过"` / `"未通过"`，并**返回 `report_id`** |
| 通知 | `app/core/executor.py:510` `Executor.notice()` | 邮件 + 钉钉 + 站内信，通道已在 `app/core/msg/` |
| 定时调度 | `app/utils/scheduler.py` | APScheduler + cron，`Scheduler.add_test_plan` |
| 通过率字段 | `app/models/test_plan.py:28` `pass_rate`（默认 80） | **只写不读** —— 全仓库除 model/schema 外无人引用，注释里「低于阈值自动通知」并未实现 |
| 出网地址校验 | `app/utils/ui_security.py` `check_url` / `resolve_host` / `is_blocked_ip` / `domain_allowed` | 既有 SSRF 工具，二期回调直接复用 |

### 1.3 五个真实缺口（这才是工作量所在）

1. **没有机器凭据** —— `app/routers/__init__.py:19` `Permission()` 只认 `token` header 里的 JWT（登录签发、有有效期、绑用户）。CI 里存一个会过期的用户 JWT，既是坏味道也是权限越界。
2. **触发是 fire-and-forget** —— `testplan.py:75` 用 `asyncio.create_task(...)`，立刻返回「开始执行，请耐心等待」。**调用方拿不到 `report_id`，也不知道何时结束**。
3. **执行结果被丢弃** —— `Executor.run_test_plan()` 末尾 `return` 后无返回值（`executor.py:545-576`）。`run_multiple` 已经把 `report_id` 和 `plan_result` 算好了，却在上一层被丢掉。
4. **异常被吞** —— `executor.py:574-576` `except Exception: log.exception(...)` 后正常返回 `None`。**CI 无法区分「测试跑挂了」和「压根没跑起来」**（计划不存在、DB 断连、cron 非法……全是一个 `None`）。
5. **没有触发记录维度** —— `pity_report` 有 `plan_id` / `executor`，但没有「来源是外部 CI」「外部构建号 / 流水线 URL」这两个字段，事后无法回答「上次这个 commit 跑了什么、结果如何」。

---

## 2. 目标与非目标

### 2.1 目标（MVP，一期）

- G1 外部系统能用**长期有效、可吊销**的 Token 调平台 API 触发测试计划，全程无需浏览器登录
- G2 触发后能拿到**明确的通过/失败结论**（含通过率、各状态用例数、报告链接）
- G3 CI 脚本能用**一个 HTTP 响应**判断阻断与否，无需额外解析逻辑
- G4 每次触发留下可查的**记录**（谁触发、跑了哪个计划、外部构建号、结果、报告 id）
- G5 `/ci` 页面落地：Token 签发/吊销、接入示例一键复制、触发历史查询

### 2.2 非目标（明确不做，避免范围膨胀）

- ❌ 平台监听 Git webhook、自己拉代码编排流水线（§5.2 二期备选）
- ❌ 精准测试（`/precise` 占位，另一个特性）
- ❌ 改动既有 `/testcase/plan/execute` 的行为（**它保持 fire-and-forget 不变**，CI 走新端点）
- ❌ 改动 `pity_report` / `pity_test_result` 表结构（报告链路零改造，同 003、002 的先例）
- ❌ 代码质量门禁、覆盖率统计、制品归档（与平台定位无关）

---

## 3. 方案

### 3.1 机器凭据：项目级 CI 集成 Token

**新表 `pity_ci_integration`**（继承 `PityBase`，走既有 model → schema → DAO → router 四段式）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | INT | 所属项目，**Token 只能作用于本项目**（越权边界） |
| `name` | VARCHAR(32) | 集成名，如「Jenkins-main」「GH-Actions-prod」 |
| `token_hash` | VARCHAR(64) | **只存 hash，绝不存明文**（见 §7.1） |
| `token_prefix` | VARCHAR(12) | 明文前 8~12 位，用于列表辨识 |
| `plan_id` | INT, nullable | 绑定的默认计划；为空则调用方必须显式传 `plan_id` |
| `callback_url` | VARCHAR(255), nullable | 二期回调地址（一期只存不发） |
| `enabled` | BOOLEAN | 停用即吊销，不删记录 |
| `expires_at` | TIMESTAMP, nullable | 为空 = 永不过期；建议默认 1 年 |
| `last_used_at` | TIMESTAMP | 最后调用时间 |

**Token 格式**：`pity_ci_` + 32 位随机十六进制（`secrets.token_hex(16)`）。明文**只在创建响应里返回一次**，之后只显示 `token_prefix`。

**鉴权：新增 `CIPermission()` 依赖**（`app/routers/__init__.py` 或 `app/routers/ci/` 内）：

- 读 `token` header（**与 `Permission()` 同名 header**，CI 示例写起来一致；`Permission()` 一行不改）
- 按 `pity_ci_` 前缀区分：无前缀 → 走原 JWT 语义；有前缀 → 按 CI Token 校验
- 校验链：查 hash → 判 `enabled` → 判 `expires_at` → 判 `project_id` 作用域
- **返回结构与 `Permission()` 完全一致**（`user_info` 字典，取 `create_user` 作为执行人），这样既有 DAO 权限判断、`PityResponse.model_to_dict(user, "password")` 全部可复用

### 3.2 同步执行语义（核心改造）

**改 `Executor.run_test_plan()` 的返回值**（`app/core/executor.py:545`）：

```
现状:  成功 → return None   |   失败 → log.exception 后 return None
改后:  成功 → return {"report_dict": {...}, "report_id": [...], "plan": plan.name}
        失败 → raise（由调用方决定是转业务码还是记日志）
```

> **兼容性**：现有两个调用方（`/plan/execute` 的 `create_task`、`Scheduler.add_test_plan` 的 cron job）都忽略返回值，改成有返回值零影响。异常从「吞掉」改成「抛出」会改变 `/plan/execute` 的行为 —— 因此**异常上抛只在新参数 `raise_on_error=True` 时生效**，默认 `False` 保持既有语义。CI 端点显式传 `True`。

**新端点**（`app/routers/ci/`，前缀 `/ci`，挂 `Depends(request_info)` 记操作日志）：

| 端点 | 鉴权 | 说明 |
|---|---|---|
| `POST /ci/run` | `CIPermission()` | 触发。body: `{plan_id?, env?, external_build_id?, external_url?, wait?, timeout_sec?}` |
| `GET /ci/run/list` | `CIPermission()` | 触发记录分页查询（按项目过滤） |
| `GET /ci/run/{id}` | `CIPermission()` | 单次结果查询（轮询用） |
| `POST /ci/integration/insert` | `Permission(Config.MANAGER)` | 签发 Token（**明文只在此返回一次**） |
| `GET /ci/integration/list` · `/update` · `/delete` | `Permission(Config.MANAGER)` | 管理 |

**两种等待模式**（都要，MVP 内）：

- **`wait=true`**：`await Executor.run_test_plan(..., raise_on_error=True)` → 跑完才返回。简单场景一步到位，Jenkins `sh curl` 直接用。
  - 必须有 `timeout_sec`（默认 300s，上限 1800s），超时走 `asyncio.wait_for`；超时返回业务码「执行超时」，**后台任务继续跑**，CI 可转轮询拿最终结果。
- **`wait=false`**（推荐默认）：立即返回 `run_id` + `code=0`，CI 轮询 `GET /ci/run/{id}` 直到 `status=finished`。**长耗时执行不占 HTTP 连接**，对部署形态更友好（见 §7.3）。

**业务响应码**（遵循 `CLAUDE.md` 响应协议：HTTP 恒 200，判定看 body `code`）：

| code | 含义 | CI 侧动作 |
|---|---|---|
| `0` | 成功且测试**通过** | 继续流水线 |
| `111`（新增） | 触发成功但测试**未通过** | `exit 1` 阻断 |
| `110` | 业务异常（计划不存在 / 未启用 / 并发冲突） | 阻断并打印 `msg` |
| `101` | 参数错误 | 阻断（CI 脚本配错了） |
| `401` | Token 无效 / 过期 / 已吊销 | 阻断 |
| `403` | Token 越权（跨项目） | 阻断 |

> `111` 是**紧邻 110 递增**的新码，落在 `0 / 101 / 110` 同区段，不碰 `200/300/500` HTTP 段 —— 符合 `CLAUDE.md`「新增业务码遵循同一张表」的硬约束。**前端 `code === 0` 判定不受影响**（111 只出现在 CI 端点）。

### 3.3 触发记录

**新表 `pity_ci_run`**（继承 `PityBase`）：

| 字段 | 说明 |
|---|---|
| `integration_id` | 触发用的 Token |
| `plan_id` · `project_id` · `env` | 跑了什么 |
| `external_build_id` · `external_url` | **CI 传入**：`$BUILD_NUMBER`、Job URL —— 事后可反查 |
| `status` | 0 pending / 1 running / 2 success / 3 failed / 4 timeout / 5 error |
| `report_ids` | TEXT，本次产生的 `pity_report.id` 列表（多环境多条） |
| `success_count` · `failed_count` · `error_count` · `skipped_count` · `pass_rate` | 汇总 |
| `cost` · `started_at` · `finished_at` | 耗时 |
| `error_msg` | `status=5` 时的失败原因（脱敏，走 `log_sanitize`） |

`wait=false` 模式下 `POST /ci/run` 立刻写一条 `status=0`，执行完成后回填 —— 这是 `GET /ci/run/{id}` 轮询的数据源。

### 3.4 前端 `/ci` 页面

- `frontend/src/pages/ci/` —— **新文件必须 TypeScript + hooks 风格**（`@umijs/plugin-model`），配 `src/services/ci.ts` + `src/models/ci.ts`（对齐 `mock.ts` / `uiTest.ts` 的最新写法，不碰老 dva model）
- 路由 `frontend/config/routes.ts:301` 把 `component: './Building'` 换成 `'./ci'`；菜单 `authority` 由「已登录」收紧为 `['admin','superAdmin']`（涉及凭据）
- 三个 tab：
  1. **集成配置** —— 项目选择、Token 签发（弹窗一次性展示明文 + 复制）、绑定计划、回调地址、启用/停用、最后调用时间
  2. **接入示例** —— **Jenkinsfile 片段**与 **GitHub Actions YAML 片段**，变量自动填充（平台地址、Token 占位、计划名），一键复制。这是采纳率的关键，不是附属功能
  3. **触发历史** —— ProTable，列：时间、项目、计划、外部构建号（超链到 `external_url`）、结果（通过/未通过/超时）、报告链接（复用 `Config.SERVER_REPORT` + `report_id` → `/#/record/report/{id}`）

---

## 4. 复用 vs 新增

| | 内容 |
|---|---|
| **复用（一行不改）** | `pity_report` 表、`pity_test_result`、`Executor.run_multiple`、`Executor.notice`、`PityResponse`、`PityRouter` 四段式、`request_info` 操作日志、`@ModelWrapper` DAO、`Log` 类、`ui_security` 出网校验（二期）、既有报告页 |
| **小改（2 处）** | `Executor.run_test_plan()` 加返回值与 `raise_on_error` 参数；`routes.ts:301` 指向真实页面 |
| **新增** | 2 张表（`pity_ci_integration` / `pity_ci_run`）、`app/routers/ci/`（约 8 端点）、`CIPermission()`、`app/crud/ci/` 2 个 DAO、`app/schema/ci.py`、`app/core/ci_runner.py`（触发编排）、前端 `pages/ci/` + service + model、`scripts/ci_selftest.py` + `scripts/ci_e2e.py` |

---

## 5. 分期

### 5.1 一期 MVP —— 让一条 Jenkinsfile 真的能跑通

| # | 任务 | 产出 |
|---|---|---|
| T01 | `pity_ci_integration` model + schema + DAO + 签发/吊销路由 | Token 全生命周期 |
| T02 | `CIPermission()` 鉴权依赖（hash 校验、启用态、过期、项目作用域） | 机器凭据通道 |
| T03 | `Executor.run_test_plan()` 返回值改造 + `raise_on_error` | 结果不再丢弃 |
| T04 | `pity_ci_run` 表 + 写入/回填逻辑 | 触发记录 |
| T05 | `POST /ci/run`（`wait` 两态 + 超时）+ `GET /ci/run/{id}` + `/list` | 触发与查询 |
| T06 | 业务码 `111` 接入 `PityResponse` | CI 可单响应判定 |
| T07 | `scripts/ci_selftest.py`（**无 DB**：Token 格式/校验链、业务码映射、权限边界、`run_test_plan` 返回结构静态断言） | 回归基线 |
| T08 | `/ci` 页面三 tab + `services/ci.ts` + `models/ci.ts` + 路由切换 | 可用界面 |
| T09 | `scripts/ci_e2e.py`（**需 DB**：签发 → 触发 → 轮询 → 断言记录） | 端到端 |

**验收（一期全绿才算完）**：
```
cd backend
.venv/bin/python scripts/ci_selftest.py      # 无 DB，全绿
.venv/bin/python scripts/ci_e2e.py           # 需 DB，全绿
.venv/bin/python -c "import main"            # 导入无误
cd ../frontend && npx tsc --noEmit           # 0 错误
```
**人工验收**：一段真实 Jenkinsfile / GitHub Actions 调通，失败用例能让流水线红。

### 5.2 二期（不展开，仅列清单）

- 回调 webhook（结果 POST 回 CI）—— **SSRF 边界与内网 Jenkins 的矛盾必须先决策，见 §7.2**
- 多计划批量触发、参数化变量注入
- 通过率门禁：`pity_test_plan.pass_rate` **目前只写不读**，接上它就能做「通过率 < 80 则 `code=111`」
- 与 `/precise` 精准测试的挂接
- 内建流水线（Git webhook → 编排）—— 需求确认后再评估

---

## 6. 工作量估算

按 003-mock-config（1 表 / 2 路由 / 107 断言自测 / 33 断言 e2e）与 002-ui-automation（6 表 / 27 端点 / 267 断言）的实测规模类比：

| 项 | 一期 |
|---|---|
| 后端新文件 | 约 10 个（model / schema / 2 DAO / ci_runner / 4~8 路由 / CIPermission） |
| 新表 | 2（`pity_ci_integration`、`pity_ci_run`），**无 alembic 强依赖**（启动时 `create_all` 自动建表） |
| 改动既有文件 | **2**（`executor.py` 返回值、`routes.ts:301`） |
| 前端新文件 | 约 6（页面 3~4 个组件 + service + model），全 TS hooks 风格 |
| 回归断言 | 自测约 60~80 项，e2e 约 30~40 项 |
| 新依赖 | **零**（`secrets` / `hashlib` 均为标准库） |

---

## 7. 风险与必须先拍板的点

### 7.1 Token 绝不能明文入库 —— 别复制既有坏味道

`CLAUDE.md` 安全审查章节已经把「敏感数据明文存储（`pity_database_info.password`、`pity_ai_vendor.api_key`）」列为既有安全面。**新表直接存明文等于再添一处**。必须存 `sha256(token + 盐)`，明文只在签发响应出现一次，列表只回 `token_prefix`。

### 7.2 回调 URL 的 SSRF：内网 Jenkins 是真实矛盾

`app/utils/ui_security.py` 的 `is_blocked_ip` / `resolve_host` 会拒绝私网/环回/链路本地地址。但**现实里 Jenkins、GitLab CI 大概率就在内网** —— 一期全量套用这个校验，二期回调功能会直接不可用；不套用则是新开一个出网 SSRF 面。

**必须先决策**（建议）：回调地址**仅限管理员配置** + **显式白名单机制**（按项目登记允许回调的 host，而非全局放开），既复用 `resolve_host` 做 DNS 解析，又允许受控内网目标。**这条不定，二期不要开工。**

### 7.3 长耗时执行与 `gunicorn -w 1`

`CLAUDE.md` 记录：`ops/supervisor.conf` 必须 `-w 1`（loguru rotation 双进程会丢 12.5% 日志）。所以**不能靠加 worker 解决长请求堆积**。

`wait=true` 在 asyncio 下是 `await` 不阻塞事件循环，但跑一个 10 分钟的 UI 用例计划会持续产生 DB 写与 HTTP 出网，CI 客户端中途断连时任务行为需要明确定义。

**建议**：`wait=false` + 轮询为**文档推荐姿势**，`wait=true` 保留为便捷选项并强制 `timeout_sec`，且超时后任务继续在后台完成。

### 7.4 其余风险

| 风险 | 处置 |
|---|---|
| `run_test_plan` 吞异常 → CI 拿不到失败原因 | `raise_on_error=True` 仅对 CI 端点生效，cron 路径语义不变 |
| 并发重复触发同一计划 | 触发时检查 `pity_test_plan.state`（0/1），运行中返回 `110`；`pity_ci_run` 同 `plan_id` 且 `status in (0,1)` 视为冲突 |
| Token 越权跑别的项目用例 | `CIPermission` 强制注入 `project_id`，`plan_id` 必须属于该项目，否则 `403` |
| 新业务码破坏前端 `code === 0` 约定 | `111` 只在 `/ci/*` 返回，前端不消费；遵循同区段递增 |
| 改 `run_test_plan` 影响既有调用方 | 两个调用方均忽略返回值；异常上抛用参数开关隔离 |

---

## 8. 下一步

1. 你确认本计划书（尤其 §7.2 回调 SSRF 的取向、§3.2 业务码 `111` 是否接受）
2. 走 `/speckit-specify` 出 `specs/004-ci/spec.md`（FR / SC 需求编号 + 验收场景）
3. `/speckit-plan` → `plan.md`（constitution 门禁）+ `research.md` + `data-model.md`
4. `/speckit-tasks` → `tasks.md`（带 ID、文件路径、依赖顺序）
5. `contracts/` 定死 Token 鉴权头、`POST /ci/run` 请求/响应结构、业务码表 —— **这是前后端唯一契约，先于实现**
6. 实现一期 T01~T09，`ci_selftest.py` + `ci_e2e.py` 全绿后，更新 `specs/HANDOFF.md`

---

## 9. 已拍板的决定（2026-11-23，全部按建议通过）

| # | 问题 | **决定** |
|---|---|---|
| Q1 | 回调地址允不允许内网？（§7.2） | **允许**，但走「项目级 host 白名单 + 仅管理员配置」，不做全局放开。一期只存 `callback_url` 不发送 |
| Q2 | 新业务码用 `111` 还是别的？（§3.2） | **`111`**，紧邻 `110` 递增，落在 `0 / 101 / 110` 同区段，不碰 HTTP 段 |
| Q3 | `wait` 默认值？ | **`false`（轮询）** 为默认与文档主推；`true` 作便捷选项，强制 `timeout_sec` |
| Q4 | Token 有效期默认？ | **1 年**，可留空设为永不过期，页面强提示 |
| Q5 | 一期要不要回调 webhook？ | **不要**。一期只做「触发 + 判定 + 记录」闭环，回调整体放二期 |

> 以上 5 条是 `spec.md` 的输入约束。写需求时不得偏离 —— 如需推翻，先回来改本表再改 spec。

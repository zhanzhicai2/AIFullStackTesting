# Implementation Plan: 持续集成（外部 CI 对接）

**Branch**: `004-ci` | **Date**: 2026-11-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-ci/spec.md`

> **分支说明**：本仓库未安装 Spec Kit 的 git 扩展（`.specify/extensions.yml` 不存在，`before_plan` 钩子不存在），特性目录名与 git 分支名相互独立。当前在 `main` 分支上，`specs/004-ci/` 是目录标识而非分支标识。

## Summary

把前端路由表里已存在但指向占位页的 `/ci` 菜单做成**平台对外的测试执行通道**：外部流水线（Jenkins / GitHub Actions / GitLab CI）携带**项目级接入凭据**触发平台的测试计划，平台跑完给出「通过 / 未通过」的明确结论供调用方阻断构建，并留下可追溯的触发记录；平台侧在 `/ci` 页面完成凭据签发、接入示例一键复制与历史查询。

**上游输入**：`specs/004-ci/proposal.md`（已确认，§9 五项决定为本计划的硬约束：Q1 回调允许内网但一期不发、Q2 业务码取 `111`、Q3 默认不等待、Q4 凭据默认 1 年、Q5 一期无回调）。

**技术路径**：新增 2 张表（`pity_ci_integration` 凭据、`pity_ci_run` 触发记录）+ 1 个鉴权依赖 `CIPermission()` + 1 个编排器 `app/core/ci_runner.py` + 1 组路由 `app/routers/ci/`；**对既有代码只改 2 处** —— `Executor.run_test_plan()` 补返回值与 `raise_on_error` 开关、`routes.ts:301` 指向真实页面。复用 `pity_report` / `pity_test_result` / `Executor.run_multiple` / `PityResponse` / `Permission()` 模式 / `Log` / hooks 前端范式，**报告链路零改造、既有计划执行入口行为不变**。回归走 `ci_selftest.py`（无 DB）+ `ci_e2e.py`（有 DB）。

## Technical Context

**Language/Version**: Python 3.10.22（后端，FastAPI + SQLAlchemy 1.4 同步 ORM 风格 + AsyncSession）/ TypeScript 5.9.2（前端，UmiJS v4 + Ant Design v5 + Ant Design Pro Components）

**Primary Dependencies**: 既有 `fastapi==0.115.6` / `sqlalchemy==1.4.47` / `pydantic~=1.10.13` / `aiomysql` / `loguru>=0.7.2,<0.8.0` / `apscheduler`；凭据生成与摘要用标准库 `secrets` + `hashlib` —— **不新增任何第三方依赖**

**Storage**: MySQL 8.0（`app/models/ci.py` 新增 2 张表，经 SQLAlchemy + `aiomysql`）；无需 Redis / 对象存储。凭据**只存 `sha256(明文)` 等值摘要 + 可辨识前缀**，绝不存明文（见 §Constitution GATE-SEC）

**Testing**: 后端无 pytest 框架 —— 沿用既有模式走独立回归脚本 `backend/scripts/ci_selftest.py`（不依赖数据库：凭据摘要校验链、业务码映射、权限边界、`run_test_plan` 返回结构的源码静态断言）与 `ci_e2e.py`（需要数据库：签发 → 触发 → 轮询 → 记录断言）；前端用 `npx tsc --noEmit` + ESLint 验收（见 `frontend/CLAUDE.md`）

**Target Platform**: Linux server（后端，**单进程** supervisord + gunicorn `-w 1`）/ 现代浏览器（前端）

**Project Type**: web-service（monorepo：`backend/` + `frontend/`）

**Performance Goals**: 触发接口本身毫秒级返回（不等待语义下）；等待语义下执行结束后 5 秒内可读到结论（SC-003）；触发历史分页在单项目 1000 条内 1 秒返回（SC-009）

**Constraints**:
- **单进程部署是硬约束** —— `ops/supervisor.conf` 必须 gunicorn `-w 1`（loguru rotation 双进程会丢 12.5% 日志，`backend/CLAUDE.md` 实测记录）。**不得依赖增加进程数消化长耗时等待**，等待连接必须是纯 `await` 不阻塞事件循环
- **等待超时不得取消执行** —— `asyncio.wait_for` 超时会 `cancel()` 任务，与 FR-011（超时后执行继续完成）冲突，必须用 `asyncio.wait(..., timeout=)` 这类不取消的等待
- **既有计划执行入口行为不变** —— `/testcase/plan/execute` 与 APScheduler cron 路径保持 fire-and-forget 语义
- **不改造 `pity_report` / `pity_test_result` 表结构**（同 002/003 先例，报告链路零改造）
- **不新增出网调用**（一期无回调 webhook）；凭据与外部构建号落日志前必须过脱敏

**Scale/Scope**: 单项目集成配置条数按常规（个位数到数十条）；触发记录按时间累积，需分页；一次触发产生 1~N 条 `pity_report`（N = 计划配置的环境数）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

对照 `.specify/memory/constitution.md`（v1.0.0，2026-10-23）逐条核验：

| 门禁 | 依据 | 结论 | 说明 |
|---|---|---|---|
| **GATE-I 确定性优先**（NON-NEGOTIABLE） | 原则 I | ✅ PASS（附显式标注） | 本特性**不涉及数据生成的可重放性** —— 没有预览/落地二义、没有 seed 数据。唯一的随机源是**凭据生成**（`secrets.token_hex`，CSPRNG），它是安全材料，**必须**不可预测；用可重放随机生成凭据等于制造漏洞。按原则 I 自带的豁免条款「若确实无法重放……MUST 在代码注释与设计文档中**显式标注**该字段不可重放」，在 `CiIntegrationDao` 生成处与 `data-model.md` 显式标注 `token` **不可重放（安全属性，非缺陷）**。除此之外执行结果本身受被测系统影响不可重放，与既有接口/UI 自动化同源，已在 spec Assumptions 声明 |
| **GATE-II 复用平台既有机制** | 原则 II | ✅ PASS | 复用 `Executor.run_test_plan` / `run_multiple`（**不自造第二套执行**）、`pity_report` + `TestReportDao`（不新建报告）、`PityBase`、`PityResponse`、`Permission()` 的返回结构与角色常量、`@ModelWrapper` DAO 四段式、`Log` 类、`request_info` 操作日志、既有报告页 `/#/record/report/{id}`、前端 hooks model/service 范式。**不新建**：执行引擎、报告表、鉴权体系、响应协议、前端状态管理 |
| **GATE-III 跨端契约单一出处** | 原则 III | ✅ PASS | 跨端共享的**业务结果码**（`111` 测试未通过）与**执行状态枚举**（进行中/成功/失败/超时/执行失败）：后端 `backend/app/enums/CiEnum.py` 为**权威定义**，前端 `frontend/src/consts/ci.ts` 镜像并注释指认；`backend/CLAUDE.md` 与 `frontend/CLAUDE.md` 各补一条同步要求。请求/响应结构单一出处为 `contracts/api.md` |
| **GATE-IV 交互自成闭环** | 原则 IV | ✅ PASS | 四态就地指引：①未选项目 → 提示选择 + 项目入口；②项目下无集成配置 → 就地「新建集成」入口；③项目下无测试计划 → 就地「新建测试计划」入口；④无触发记录 → 展示接入示例而非空白。全部在 `/ci` 页面内闭环。见 `data-model.md` §5 |
| **GATE-V 落地前必须过回归** | 原则 V | ✅ PASS | `ci_selftest.py`（无 DB：摘要校验链正反例、业务码映射、越权/过期/停用/无效四类拒绝、`run_test_plan` 返回结构、**源码静态扫描：无明文凭据落库、无新增出网调用**）+ `ci_e2e.py`（有 DB：签发 → 触发 → 轮询 → 记录 → 报告入口完整链路）。无自动化验证不得落地 |
| **GATE-SEC 安全要求** | 安全要求 | ✅ PASS（**本特性核心检查点**） | ①**新增外部输入面**：凭据明文、外部构建号、外部地址 —— 三者均不进 `exec`/模板/SQL 拼接，构建号与地址按字符串字段存储并过 `log_sanitize` 脱敏后落日志；②**新增写入通道**（集成配置 CRUD）按平台惯例用 `Permission(Config.MANAGER)` 收紧角色，DAO 按 `project_id` 隔离；③**不新增出网面**：一期零出网（回调只存不发），源码静态扫描断言无 `aiohttp`/`httpx`/`requests` 调用；④**凭据不存明文**（存 `sha256` 等值摘要），**不新增**既有「敏感数据明文存储」坏味道；⑤**不新增执行面**，无 `exec()`/`eval` |

**Gate 结论**：六项门禁全部通过。GATE-I 的唯一随机源是凭据生成，走原则 I 自带的「无法重放则显式标注」条款并要求在代码注释与 `data-model.md` 双处标注；**GATE-SEC 是本特性最核心的检查点**（凭据摘要、四类拒绝、零出网、零执行）。

> ⚠️ **安全审查提示**（constitution「安全审查触发条件」）：本特性**新增 8 个 `app/routers/` 接口**、**新增鉴权判断 `CIPermission()`**、**新增外部输入面**、**新增敏感数据存储（凭据摘要）** —— 四条触发条件全命中。按 constitution 由**人决定是否执行** `security-review`，不自动跑。建议在一期 T01~T06 落地后、T08 前跑一次。

## Project Structure

### Documentation (this feature)

```text
specs/004-ci/
├── proposal.md           # 计划书(已确认):现状实测、方案、分期、风险、§9 五项决定
├── spec.md               # WHAT/WHY:4 个用户故事、33 条功能需求、12 条成功标准
├── plan.md               # 本文件(HOW)
├── research.md           # Phase 0:技术决策 D1~D10 + 否决备选
├── data-model.md         # Phase 1:表结构、状态流转、就地指引、脱敏规则
├── quickstart.md         # Phase 1:端到端验证指南
├── checklists/
│   └── requirements.md   # 规格质量自检(16/16 通过)
├── contracts/
│   └── api.md            # 凭据/触发/历史的唯一前后端契约 + 业务码表
└── tasks.md              # Phase 2(/speckit-tasks 产出)
```

深设计附录（constitution「文档分层」指定落点）：

```text
backend/docs/ci-design.md
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── enums/
│   │   └── CiEnum.py                 # 【新增】跨端常量权威定义:业务码 111 / 执行状态 / 默认有效期
│   ├── models/
│   │   └── ci.py                     # 【新增】pity_ci_integration + pity_ci_run 两张表
│   ├── crud/ci/
│   │   ├── CiIntegrationDao.py       # 【新增】凭据签发/校验/停用/最后使用时间(摘要比对)
│   │   └── CiRunDao.py               # 【新增】触发记录写入/回填/分页查询/启动时终态恢复
│   ├── core/
│   │   └── ci_runner.py              # 【新增】触发编排:防重 → 建记录 → 执行 → 回填;超时不取消
│   ├── schema/
│   │   └── ci.py                     # 【新增】Pydantic v1 表单(集成配置 + 触发请求)
│   └── routers/ci/
│       ├── __init__.py               # 【新增】CI Router 汇总
│       ├── integration.py            # 【新增】凭据管理(list/insert/update/delete),Permission(MANAGER)
│       └── run.py                    # 【新增】触发 + 结果查询,CIPermission
├── routers/__init__.py               # 【修改】新增 CIPermission 依赖(读 token header,结构对齐 Permission)
├── core/executor.py                  # 【修改】run_test_plan 补返回值 + raise_on_error 开关(默认 False 保既有语义)
├── app/__init__.py                   # 【修改】lifespan 增加第 5 步:把残留 running/pending 的 ci_run 置为终态
├── main.py                           # 【修改】注册 ci_router(带 request_info)
└── scripts/
    ├── ci_selftest.py                # 【新增】不依赖 DB:摘要校验链 + 业务码 + 权限边界 + 源码静态扫描
    └── ci_e2e.py                     # 【新增】依赖 DB:签发 → 触发 → 轮询 → 记录 → 报告入口

frontend/
├── config/routes.ts                  # 【修改】/ci component './Building' → './ci',authority 收紧为 admin/superAdmin
├── src/consts/ci.ts                  # 【新增】CiEnum 镜像(指认后端权威出处)
├── src/services/ci.ts                # 【新增】8 个接口封装
├── src/models/ci.ts                  # 【新增】hooks 风格 model
└── src/pages/ci/
    ├── index.tsx                     # 【新增】三 tab 容器:集成配置 / 接入示例 / 触发历史
    ├── index.less                    # 【新增】
    ├── IntegrationPanel.tsx          # 【新增】凭据列表 + 签发弹窗(明文仅此一次) + 停用/删除
    ├── SnippetsPanel.tsx             # 【新增】Jenkinsfile / GitHub Actions 片段 + 一键复制
    └── RunHistoryPanel.tsx           # 【新增】触发历史 ProTable(外部构建号跳转 + 报告入口)
```

**Structure Decision**: 单一 monorepo（backend + frontend 平行目录），与 001/002/003 完全同构；CI 相关代码全部落 `backend/app/{enums,models,crud/ci,core,schema,routers/ci}` 与 `frontend/src/{consts,services,models,pages/ci}`。编排逻辑放 `app/core/ci_runner.py`（纯流程控制，便于无 DB 单测），鉴权依赖放 `app/routers/__init__.py`（与 `Permission` 同处，便于对照与复用返回结构），路由按「凭据管理 / 触发查询」拆两个文件（权限等级不同：前者 `MANAGER`、后者 `CIPermission`）。

## Phase 0 & Phase 1 产出清单

| 产物 | 状态 | 要点 |
|---|---|---|
| `research.md` | ✅ | D1~D10 决策 + 否决备选，0 条 NEEDS CLARIFICATION |
| `data-model.md` | ✅ | 2 张表 / 状态机 / 脱敏规则 / 四态就地指引 / 查询路径 |
| `contracts/api.md` | ✅ | 8 个接口 + 业务码表（`0/101/110/111/112/401/403`）+ 凭据格式 + 接入示例 |
| `quickstart.md` | ✅ | 环境准备 / 回归三步 / A~G 七个端到端场景 / SC 对照表 |
| `backend/docs/ci-design.md` | ⬜ 实现后 | 深设计附录（constitution 指定落点） |

> **契约层的一处扩展（需你知悉）**：`proposal.md` §9 的 Q2 只批准了业务码 `111`。契约另加了 **`112` 等待超时** —— 因为 FR-011 要求「超时」与「业务异常」可区分，否则 CI 脚本无法决定「再轮询一次」还是「放弃」。两者都在同区段递增。**若不同意**，可改用 `code=0 + data.wait_timeout=true`，但 CI 一行判据 `[ "$code" = "0" ]` 会失效（详见 `contracts/api.md` §0 注释）。

## Post-Design Re-check

Phase 1 完成后复核：

| 门禁 | 复核结论 |
|---|---|
| **GATE-I 确定性优先** | ✅ 本特性不涉及数据生成可重放性；唯一随机源是凭据生成（CSPRNG），按原则 I 豁免条款在 `CiIntegrationDao` 注释与 `data-model.md` §1 **双处显式标注不可重放（安全属性）**。通过判定（`total>0 且 fail=error=0`）是纯函数，无随机 |
| **GATE-II 复用既有机制** | ✅ 复用 `Executor.run_test_plan`/`run_multiple`（只补 return 与 `raise_on_error` 开关，不造第二套执行）、`pity_report`/`TestReportDao`（零改造）、`pity_test_plan.state`（防重）、`PityBase`/`PityResponse`/`Permission()` 返回结构/`@ModelWrapper`/`Log`/`request_info`/既有报告页/hooks model。**新建仅**：`CIPermission`（8 个接口的鉴权，`Permission()` 一行不改）、`CiEnum`（跨端常量权威）、`ci_runner`（流程编排） |
| **GATE-III 跨端契约单一出处** | ✅ `CiEnum.py` 权威 + `consts/ci.ts` 镜像指认（`contracts/api.md` §4 列出全部共享常量）；接口契约单一出处 `contracts/api.md`；`RunStatus` 六态在契约 §3.2 定义，`3`/`5` 语义分离 |
| **GATE-IV 交互自成闭环** | ✅ G1 未选项目 / G2 无集成 / G3 无计划 / G4 无记录 **四态**就地指引，G2+G3 并列时按「先计划、后凭据」排序（`data-model.md` §7）。G3 是硬前置 —— 没有计划即使签了凭据也无从触发 |
| **GATE-V 落地前必须过回归** | ✅ `ci_selftest.py`（无 DB，含**源码静态扫描**：无明文落库、零出网、无 exec、等待用 `asyncio.wait` 而非 `wait_for`）+ `ci_e2e.py`（有 DB：签发→触发→轮询→记录→报告 + 拒绝类 + 并发防重 + 重启恢复）。命令见 `quickstart.md` §2 |
| **GATE-SEC 安全要求** | ✅ **重点复核通过**：①凭据存 `sha256` 等值摘要，明文仅签发响应一次（`data-model.md` §5 脱敏表覆盖落库/落日志/界面三列）；②新增写入通道（集成 CRUD）用 `Permission(Config.MANAGER)`，DAO 按 `project_id` 隔离，触发端点用 `CIPermission` 强制项目作用域 → 403；③**一期零出网**（`callback_url` 只存不发，静态扫描断言）；④零执行面（无 `exec`/`eval`）；⑤外部输入面（`external_build_id`/`external_url`/`error_msg`）为纯字符串存储 + 过 `log_sanitize`，不进 SQL 拼接与模板 |

**Post-Design 结论**：六项门禁全部通过，无违规需豁免（Complexity Tracking 保持为空）。

> ⚠️ **安全审查仍待执行**（constitution 触发条件四条全命中：新增 8 个路由接口、新增鉴权判断、新增外部输入面、新增敏感数据存储）。按 constitution 由**人决定**是否跑 `security-review`，不自动执行。**建议在一期 T01~T06 落地后、T08 前跑一次**。

## Complexity Tracking

> 无 Constitution 违规需豁免 —— 六项门禁全部 PASS（GATE-I 的凭据随机源走原则 I 自带的「无法重放则显式标注」条款，非违规）。

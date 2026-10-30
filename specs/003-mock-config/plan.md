# Implementation Plan: Mock 配置

**Branch**: `003-mock-config` | **Date**: 2026-10-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-mock-config/spec.md`

> **分支说明**:本仓库未安装 Spec Kit 的 git 扩展(`.specify/integration.json` 的 `installed_integrations` 只有 `claude`),`before_specify` 的建分支 hook 不存在,特性目录名与 git 分支名相互独立。当前在 `main` 分支上,`specs/003-mock-config/` 是目录标识而非分支标识。

## Summary

把前端路由表里已存在但指向占位页的 `/mock` 菜单做成完整的 **Mock 配置功能**:平台内置**纯静态 Mock 服务**(`GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS /mock/{项目app}/**`),规则命中即返回配置的状态码/响应头/响应体(可带 0~5000ms 模拟延迟),未命中返回 404 业务码;**不转发到真实后端、不发任何外部请求,从机制上排除 SSRF**。

用户在前端「Mock 配置」页按项目管理规则(增删改查、启停、筛选、就地调试),配置页展示 mock 基地址与调用示例供被测系统使用。响应体支持**请求回显变量**(`$request.path` / `$request.query.*` / `$request.body.*` / `$request.header.*`,封闭白名单),全部由请求内容决定 → 满足确定性优先(constitution 原则 I)。

复用:`pity_project.app` 作为基地址项目标识、`Permission()` 鉴权、`@ModelWrapper` DAO 模式、`PityResponse`、hooks 风格前端 model/service。**不新建平行体系**。

技术路径:后端新增 1 张表 `pity_mock_rule` + 1 个纯函数匹配引擎 + 2 个 `APIRouter`(管理/服务,注意注册顺序)+ 1 个白名单变量渲染器;前端把 `/mock` 菜单指向真实页面,新增 service / model / 常量镜像;回归走 `mock_selftest.py`(无 DB)+ `mock_e2e.py`(有 DB)。

## Technical Context

**Language/Version**: Python 3.10(后端,FastAPI + SQLAlchemy 1.4 同步 ORM 风格 + AsyncSession)/ TypeScript 5.9.2(前端,UmiJS v4 + Ant Design v5)

**Primary Dependencies**: 既有 `fastapi==0.115.6` / `sqlalchemy==1.4.47` / `pydantic~=1.10.13` / `aiohttp` / `loguru`;mock 服务直接用 FastAPI `Request` 原生对象读取请求,**不新增第三方依赖**(不引入 httpx/starlette 之外的东西)

**Storage**: MySQL 8.0(`app/models/mock.py` 新增 1 张表,经 SQLAlchemy + `aiomysql`);无需 Redis / 对象存储

**Testing**: 后端无 pytest 框架 —— 沿用既有模式,走独立回归脚本 `backend/scripts/mock_selftest.py`(不依赖数据库,匹配引擎 + 源码静态扫描)与 `mock_e2e.py`(需要数据库,管理链路 + 对外服务);前端用 `npx tsc --noEmit` + ESLint 验收(见 `frontend/CLAUDE.md`)

**Target Platform**: Linux server(后端,单容器 supervisord + gunicorn)/ 现代浏览器(前端)

**Project Type**: web-service(monorepo:`backend/` + `frontend/`)

**Performance Goals**: 对外 mock 服务响应延迟 ≤ 50ms(不含配置的模拟延迟);规则列表分页查询秒级返回

**Constraints**: 不新增执行面(无 `exec()` / 无出网调用 —— 回归脚本静态扫描保证);不触碰既有 `app/core/render.py`(非沙箱,变量渲染用独立小实现);mock 服务路由必须**后于管理路由注册**(否则 catch-all 吞掉 `/mock/rule/*`);不新增第三方依赖;`Project.app` 字段复用不改动

**Scale/Scope**: 单项目规则量按常规(≤ 数百条),不设专门限流;规则命中不做统计日志(MVP 范围外)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

对照 `.specify/memory/constitution.md`(v1.0.0, 2026-10-23)逐条核验:

| 门禁 | 依据 | 结论 | 说明 |
|---|---|---|---|
| **GATE-I 确定性优先**(NON-NEGOTIABLE) | 原则 I | ✅ PASS | 匹配引擎全排序确定(精确>参数化>通配 → priority → id,无随机);响应变量仅"请求回显"四类,由请求内容决定,同一请求两次调用响应逐字段一致 —— 回归脚本以"双跑一致"为断言。不引入 `$timestamp`/`$randomInt` 等任何随机源 |
| **GATE-II 复用平台既有机制** | 原则 II | ✅ PASS | 复用 `pity_project.app`(基地址标识)、`Permission()`(鉴权)、`ProjectRoleDao.read_permission`(私有项目读检查)、`PityBase`(审计字段)、`PityResponse`(响应协议)、`@ModelWrapper` DAO 模式、前端 hooks model/service。**不新建**:HTTP 客户端(用 FastAPI Request)、鉴权体系、响应协议、前端状态管理范式 |
| **GATE-III 跨端契约单一出处** | 原则 III | ✅ PASS | 请求方法集与路径类型:后端 `app/enums/MockEnum.py` 为**权威定义**,前端 `frontend/src/consts/mock.ts` 镜像并指认;`backend/CLAUDE.md` 声明"MUST 同步修改两处"。响应协议、接口路径写死于 `contracts/api.md`(唯一契约) |
| **GATE-IV 交互自成闭环** | 原则 IV | ✅ PASS | 三态就地指引:①未选项目 → 提示选择 + 项目入口;②项目 app 为空 → 提示补全(否则规则不可达);③项目下无规则 → 展示"被测系统如何调用 mock 服务"的使用引导。全部在当前页面内闭环,不依赖视野外配置。见 `data-model.md` §4 |
| **GATE-V 落地前必须过回归** | 原则 V | ✅ PASS | `backend/scripts/mock_selftest.py`(不依赖 DB:匹配全表正反例 + 双跑一致 + 变量四类正反例 + 未知变量拒绝 + **源码 AST 静态扫描:无出网调用、无 eval/exec**)+ `mock_e2e.py`(依赖 DB:管理链路 + 对外服务命中/404/启停/删除/权限/app 边界)。无自动化验证手段不得落地 |
| **GATE-SEC 安全要求** | 安全要求 | ✅ PASS | ①**不新增执行面**:无 `exec()`/`eval`,变量渲染是"查字典替换"无表达式求值;②**不新增出网面**:mock 服务命中只读库返回静态内容、未命中即 404,源码中不存在 `aiohttp`/`httpx`/`requests` 调用;③新增写入通道(规则管理)按平台惯例用 `Permission()`(与用例/元素同级,2 号元素 DAO 同款),DAO 层按项目隔离;④对外服务无鉴权属设计取舍(spec Assumptions 已声明半公开),剩余风险仅"知晓 app 可读取配置的假数据",使用说明标注"勿放真实凭据" |

**Gate 结论**:六项门禁全部通过。GATE-I 靠"回显变量 + 全排序匹配"天然满足;GATE-SEC 是本特性最核心的检查点(纯静态、零出网、零执行)。

**Post-Design Re-check**(Phase 1 后重跑):见本文档末尾 §Post-Design Re-check。

## Project Structure

### Documentation (this feature)

```text
specs/003-mock-config/
├── spec.md              # WHAT/WHY:4 个用户故事、20 条功能需求、成功标准
├── plan.md              # 本文件(HOW)
├── research.md          # Phase 0:现状调研与技术决策(D1~D10 + 否决备选)
├── data-model.md        # Phase 1:表结构、匹配算法、变量规范、状态流转
├── quickstart.md        # Phase 1:端到端验证指南
├── contracts/
│   └── api.md           # 管理接口 + 对外 mock 接口的唯一契约
└── tasks.md             # Phase 2(/speckit-tasks 产出)
```

深设计附录(constitution「文档分层」指定落点):

```text
backend/docs/mock-design.md
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── enums/
│   │   └── MockEnum.py              # 【新增】跨端常量权威定义:请求方法集 / 路径类型 / 延迟上限
│   ├── models/
│   │   └── mock.py                  # 【新增】pity_mock_rule 表 Model
│   ├── crud/mock/
│   │   └── MockRuleDao.py           # 【新增】规则 CRUD + 查重提示 + 对外匹配查询
│   ├── core/
│   │   └── mock_engine.py           # 【新增】纯函数匹配引擎(精确/参数化/通配/优先级/确定性排序)
│   │   └── mock_render.py           # 【新增】白名单回显变量渲染器(字典替换,零表达式)
│   ├── schema/
│   │   └── mock.py                  # 【新增】Pydantic v1 表单
│   └── routers/mock/
│       ├── admin.py                 # 【新增】管理接口(rule/list insert update delete status detail preview)
│       └── service.py               # 【新增】对外 catch-all 服务入口(无鉴权)
├── main.py                          # 【修改】注册两个 router(管理先、服务后 — 硬约束)
└── scripts/
    ├── mock_selftest.py             # 【新增】不依赖 DB:匹配全表 + 变量正反例 + 源码静态扫描
    └── mock_e2e.py                  # 【新增】依赖 DB:管理链路 + 对外服务命中/404/权限/边界

frontend/
├── config/routes.ts                 # 【修改】/mock component → ./Mock/index
├── src/consts/mock.ts               # 【新增】MockEnum 的前端镜像(指认后端)
├── src/services/mock.ts             # 【新增】7 个管理接口封装
├── src/models/mock.ts               # 【新增】hooks 风格 model
└── src/pages/Mock/
    ├── index.tsx                    # 【新增】规则列表 + 项目选择 + 基地址展示 + 就地指引
    ├── Mock.less                    # 【新增】
    ├── RuleFormModal.tsx            # 【新增】新建/编辑规则(含变量清单就地提示)
    └── DebugModal.tsx               # 【新增】调试:模拟请求 → 命中规则 + 解析后响应
```

**Structure Decision**: 单一 monorepo(backend + frontend 平行目录),与 001/002 完全同构;mock 相关代码全部落 `backend/app/*/mock*` 与 `frontend/src/{pages/Mock,services/mock,models/mock,consts/mock}`。匹配引擎与渲染器放 `app/core/`(纯函数、可无 DB 单测),DAO 放 `app/crud/mock/`,路由分管理/服务两个文件(安全边界清晰)。

## Phase 0 & Phase 1 产出清单

| 产物 | 状态 | 要点 |
|---|---|---|
| `research.md` | ✅ | D1~D10 决策 + 6 项否决备选 |
| `data-model.md` | ⬜ Phase 1 | 表结构 / 匹配算法 / 变量规范 / 状态流转 / 就地指引 |
| `contracts/api.md` | ⬜ Phase 1 | 7 个管理接口 + 对外 catch-all 的完整契约 |
| `quickstart.md` | ⬜ Phase 1 | 环境准备 / 端到端场景 / 回归命令 |
| `backend/docs/mock-design.md` | ⬜ Phase 1 | 深设计附录(实现后更新状态) |

## Post-Design Re-check

Phase 1 完成后复核:

| 门禁 | 复核结论 |
|---|---|
| **GATE-I 确定性优先** | ✅ 匹配引擎全排序确定(§data-model 3),变量仅请求回显(§data-model 4),双跑一致断言已入 selftest |
| **GATE-II 复用既有机制** | ✅ 复用 `pity_project.app` / `Permission()` / `ProjectRoleDao` / `PityBase` / `PityResponse` / hooks model;未新建任何平行体系 |
| **GATE-III 跨端契约单一出处** | ✅ `MockEnum.py` 权威 + `consts/mock.ts` 镜像指认;接口契约单一出处 `contracts/api.md` |
| **GATE-IV 交互自成闭环** | ✅ G1~G4 四态就地指引全部在当前页内闭环(§data-model 5) |
| **GATE-V 落地前必须过回归** | ✅ selftest(无 DB)+ e2e(有 DB)双脚本为门禁,quickstart §3 给出命令 |
| **GATE-SEC 安全要求** | ✅ **重点复核通过**:①管理接口 `Permission()` 与用例同级、DAO 项目隔离;②对外服务零出网(命中只读库、未命中 404,AST 扫描保证无 aiohttp/httpx/requests);③零执行(无 eval/exec,渲染器为字典替换,不碰非沙箱 `render.py`);④`response_headers`/`response_body` 为字符串字段,无对象存储/凭据新增 |

**Gate 结论**:六项门禁全部通过,无遗留 violation。

## Complexity Tracking

无 constitution 违规需要 justify —— 六项门禁全部通过,本特性刻意选择最小面(纯静态、零出网、零执行、单表、两 router)。

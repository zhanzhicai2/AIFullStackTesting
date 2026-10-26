# Implementation Plan: UI 自动化子系统

**Branch**: `main` | **Date**: 2026-10-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-ui-automation/spec.md`

> **分支说明**：本仓库未安装 Spec Kit 的 git 扩展，`before_specify` 的建分支 hook 不存在，特性目录名与 git 分支名相互独立。当前在 `main` 分支上。
>
> **关联 feature**：[`001-ai-workbench`](../001-ai-workbench/) —— 本 feature 的元素库是它的 Web UI 用例生成的前置；它的 `contracts/dsl.md` 规则 11–14 指向本 feature 的 `contracts/steps.md`。
>
> **依赖方向（无环）**：001 的公共层与草稿机制**不依赖**本 feature；本 feature 的元素库与执行链路**也不依赖** 001。唯一的跨 feature 耦合是**单向**的 —— 001 的 Web UI 用例生成需要读取本 feature 的元素库。两者另共用同一份步骤 DSL 契约（`contracts/steps.md`）。
>
> **本 feature 的"草稿"不落 `pity_ai_case_draft`**：录制导入产出的用例直接进正式用例库但保持「调试中」状态（`pity_testcase.status = 1`），用户核对后改为「正常运行」即视为采纳。若改用 001 的草稿表会形成 001↔002 循环依赖。

## Summary

在 Pity 上建一套 **Playwright 驱动的 UI 自动化能力**：**元素库**沉淀定位策略 → **本地录制**导入用例 → **执行节点**跑起来 → **执行中心与测试报告**看结果。

核心结构决策：**步骤引用元素库里的元素，而不是内联定位表达式**（Page Object 模式）。这让"页面改版"从一个要改 N 条用例的问题，变成一个要改 1 处元素的问题 —— 也让 AI 生成的 UI 用例有可靠的落地基础。

UI 用例**复用既有的用例库、目录树、执行记录与报告结构**（`pity_testcase` 加 `request_type = 4`），不新建平行体系。录制在用户本地完成（`npx playwright codegen`）后导入，平台侧零浏览器运维。

技术路径：Playwright Python，后端进程内 async 执行，Browser 实例进程内单例复用 + 信号量限流。

## Technical Context

**Language/Version**: Python 3.10（后端，FastAPI + SQLAlchemy 1.4）/ TypeScript 5.9.2（前端，UmiJS v4 + Ant Design v5）

**Primary Dependencies**: 既有 `fastapi==0.115.6` / `sqlalchemy==1.4.47` / `aiohttp` / `Jinja2` / `loguru` / `oss2`；**新增** `playwright>=1.49`（Python 包）+ chromium 浏览器二进制（`playwright install --with-deps chromium`）

**Storage**: MySQL 8.0（`app/models/*`）+ 对象存储（失败截图 / trace，走既有 `pity_oss_file`）+ 平台日志

**Testing**: 后端无 pytest 框架 —— 沿用数据工厂模式，走独立回归脚本 `backend/scripts/ui_selftest.py`（解析器/DSL 校验，不需要浏览器）与 `ui_e2e.py`（需要本地 chromium 与一个测试页面）

**Target Platform**: Linux server（后端，单容器 supervisord + gunicorn -w 2）/ 真实浏览器（chromium）

**Project Type**: web-service（monorepo：`backend/` + `frontend/`）

**Performance Goals**: 单条 UI 用例执行 ≤ 60s（含浏览器冷启动摊销）；元素库增删改查 ≤ 200ms；录制导入解析 ≤ 5s/千行脚本

**Constraints**:
- **后端镜像 +~600MB**（chromium 与其系统库），用 build arg 控制
- **内存 +600MB**（gunicorn `-w 2` 每进程一个 Browser），信号量默认并发 2/进程
- **动作集合封闭** —— 不允许 `evaluate` / 任意脚本执行（仓库已有两个 `exec()` 执行面）
- **不引入分布式执行节点、浏览器扩展录制、服务端注入录制**

**Scale/Scope**: 单机单节点；全局并发上限 4（2 进程 × 每进程 2）；单条用例步骤数 ≤ 100；元素库单项目 ≤ 5000 元素

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

对照 `.specify/memory/constitution.md`（v1.0.0, 2026-10-23）逐条核验：

| 门禁 | 依据 | 结论 | 说明 |
|---|---|---|---|
| **GATE-I 确定性优先**（NON-NEGOTIABLE） | 原则 I | ✅ PASS（需缓解 + 显式标注） | **UI 执行天然含时序不确定性**，必须把确定性边界划清楚：<br>①**确定的是步骤定义** —— 同一份 steps DSL 永远产生同一串浏览器操作；<br>②**不确定的是执行结果** —— 被测系统在变，页面渲染有动画与网络延迟，这**不在平台可控范围**，不纳入原则 I 的约束面；<br>③**平台自身 MUST NOT 引入随机源** —— 只用确定性等待（等选择器可见/可交互），不用固定 `sleep`；确需固定等待的必须显式配置且写进步骤定义；重试退避策略固定不随机；chromium 不引入随机源；<br>④**执行结果不可重放**这一点 MUST 在设计文档与代码注释中**显式标注**（与"AI 生成用例不可重放"同类，constitution 原则 I 的要求） |
| **GATE-II 复用平台既有机制** | 原则 II | ✅ PASS | **复用**：`pity_testcase`（加 `request_type = 4`）、`pity_testcase_directory`、`pity_constructor`、`pity_testcase_asserts`、`pity_test_result`（结果回写）、`pity_report`、`/record/report/:id`（报告页已有 Tabs）、`/ws/{user_id}`（实时推送）、`pity_oss_file`（截图）、`Render`（`${}` 渲染）、`CaseLog`（步骤日志）、`PityResponse`、`Permission()`、loguru、`Executor.run_single`（执行骨架）。**不新建**：用例编号体系、目录树、报告结构、鉴权、文件存储 |
| **GATE-III 跨端契约单一出处** | 原则 III | ✅ PASS | 步骤 DSL 的**动作白名单**与**定位策略枚举**：后端 `backend/app/core/ui_executor.py` 的 `ACTIONS` / `STRATEGIES` + 前端 `frontend/src/consts/uiTest.ts`，互相指认并在 `backend/CLAUDE.md` 声明同步要求。`001-ai-workbench` 的规则 11–14 引用本 feature 的 `contracts/steps.md` —— **单一契约文档，两端共用** |
| **GATE-IV 交互自成闭环** | 原则 IV | ✅ PASS | 前置依赖逐项就地指引：①目标站点地址未配置 → 用例编辑器就地提示在全局变量里配 `${ui_base_url}` 并给跳转；②项目下无目录 → 就地新建目录；③元素库为空 → 用例编辑器提示先沉淀元素；④录制导入页未粘贴脚本 → 就地提示；⑤项目未配置允许域名（SSRF 白名单）→ 就地提示去配置 |
| **GATE-V 落地前必须过回归** | 原则 V | ✅ PASS | `backend/scripts/ui_selftest.py`（解析器 / DSL 校验 / 定位器映射 / **动作白名单负例**）+ `ui_e2e.py`（元素库 CRUD → 录制导入 → 草稿采纳 → 用例入库 → 执行 → 结果回写 → 失败截图落 OSS） |
| **GATE-SEC 安全要求** | 安全要求 | ✅ PASS（**新增两个必须处理的面**） | **不新增 `exec()` 执行面** —— 动作集合封闭，`evaluate` / `exec` / 任意脚本一律不接受；**录制脚本导入是新的外部输入面** —— 只解析有限已知结构、不执行其中任何内容、解析不了就跳过并说明；**浏览器执行是新的出网面（SSRF）** —— 见下方专门说明；**新增写入通道的角色收紧** —— `pity_ui_allowed_domain` 收紧到 ADMIN（安全边界），而页面/元素/用例保持 `Permission()`（团队协作资产，与既有"创建用例"同级、不扩大权限面，理由见 `contracts/api.md` §1.2） |

### GATE-SEC 专门说明：浏览器执行引入新的出网面（SSRF）

UI 用例会让平台**驱动真实浏览器访问目标站点**。而目标地址来自用例（用户可写）—— 这是一条**新的出网通道**，若不设边界，用户可以让平台去访问内网地址，包括云厂商的元数据接口（`169.254.169.254`）与环回地址。

**这不是既有安全面的重提，是本次新引入的面**，必须显式处理：

| 边界 | 决策 |
|---|---|
| **目标来源** | `base_url` MUST 来自**项目/环境级配置的允许域名白名单**，不得由用户自由填写 |
| **相对 vs 绝对** | 步骤里的 URL 只能是**相对路径**；绝对 URL MUST 落在白名单内 |
| **地址拦截** | 即便在白名单内，仍 MUST 拒绝解析到私有网段、环回、链路本地、保留地址的主机（含 DNS 解析后的结果） |
| **重定向** | 跟随重定向时 MUST 对**每一跳**重新校验 |
| **配置缺失** | 白名单为空时，UI 用例**不可执行**，界面就地提示去配置（对应 GATE-IV 的第 5 条指引点） |

> 详细决策与拦截清单见 `research.md` §3.8。

**Gate 结论**：六项门禁全部通过。GATE-I 需缓解措施与显式标注，GATE-SEC 新增一个必须处理的 SSRF 面。

**Post-Design Re-check**（Phase 1 后重跑）：见本文档末尾 §Post-Design Re-check。

## Project Structure

### Documentation (this feature)

```text
specs/002-ui-automation/
├── spec.md              # WHAT/WHY：用户场景、42 条功能需求、成功标准
├── plan.md              # 本文件（HOW）
├── research.md          # Phase 0：现状调研与技术决策
├── data-model.md        # Phase 1：数据模型与状态流转
├── quickstart.md        # Phase 1：端到端验证指南
├── contracts/
│   ├── steps.md         # 步骤 DSL 规范（前后端唯一契约；001 的规则 11-14 引用此文件）
│   └── api.md           # HTTP 接口契约
└── tasks.md             # Phase 2（/speckit-tasks 产出）
```

深设计附录（constitution「文档分层」指定落点）：

```text
backend/docs/ui-automation-design.md
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── core/
│   │   ├── ui_executor.py            # 【新增】步骤 DSL 引擎 + Browser 单例 + 信号量
│   │   ├── ui_locator.py             # 【新增】定位策略 → Playwright Locator
│   │   ├── ui_recorder.py            # 【新增】本地录制脚本 → 页面/元素/步骤 解析
│   │   └── executor.py               # 【修改】run_single 按 request_type 分派
│   ├── models/
│   │   └── ui_case.py                # 【新增】5 张表
│   ├── crud/ui/
│   │   ├── UIPageDao.py              # 【新增】
│   │   ├── UIElementDao.py           # 【新增】
│   │   ├── UICaseDao.py              # 【新增】
│   │   ├── UINodeDao.py              # 【新增】
│   │   └── UIImportLogDao.py         # 【新增】
│   ├── routers/ui/
│   │   ├── page.py                   # 【新增】页面树 CRUD
│   │   ├── element.py                # 【新增】元素库 CRUD
│   │   ├── case.py                   # 【新增】UI 用例 CRUD + 执行
│   │   ├── record.py                 # 【新增】录制导入
│   │   └── node.py                   # 【新增】执行节点
│   ├── schema/
│   │   └── ui_case.py                # 【新增】Pydantic 表单
│   └── utils/
│       └── ui_security.py            # 【新增】SSRF 防护：域名白名单 + 私网拦截
└── scripts/
    ├── ui_selftest.py                 # 【新增】回归：解析器/DSL 校验
    └── ui_e2e.py                      # 【新增】回归：端到端

frontend/
└── src/
    ├── pages/UiTest/
    │   ├── CaseManage/
    │   │   ├── index.tsx              # 【新增】用例列表（分组树 + 表格）
    │   │   └── CaseEditor.tsx         # 【新增】步骤编排 + 元素引用 + 调试
    │   ├── Element/
    │   │   ├── index.tsx              # 【新增】元素库
    │   │   └── ElementModal.tsx       # 【新增】定位策略弹窗
    │   ├── Record/index.tsx           # 【新增】录制导入
    │   ├── Node/index.tsx             # 【新增】执行节点
    │   └── Execution/index.tsx        # 【新增】执行中心
    ├── consts/
    │   └── uiTest.ts                  # 【新增】步骤 DSL 常量（镜像后端）
    ├── services/
    │   └── uiTest.ts                  # 【新增】
    └── models/
        └── uiTest.ts                  # 【新增】hooks 风格 model
```

**Structure Decision**：沿用 monorepo 既有分层。**复用 `frontend/src/pages/uiTest/` 这个已被注释的旧目录**（`config/routes.ts:72-112` 的路由全被注释），但**重写内容** —— 旧代码是 JS + dva model 风格，新代码按 `frontend/CLAUDE.md` 用 TS + hooks。

后端新增 `app/crud/ui/` 与 `app/routers/ui/` 两个平级目录，与既有的 `app/crud/data_factory/`、`app/routers/datafactory/` 形态一致。

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| **新增 `playwright` 依赖 + chromium 二进制**（镜像 +~600MB，内存 +600MB） | UI 自动化必须有真实浏览器；这是本 feature 的存在前提 | 放弃 UI 自动化、只做接口测试 —— 但这正是需求本身。且 chromium 可用 build arg 控制，不部署 UI 的环境可跳过 |
| **浏览器执行引入新的出网面（SSRF）** | 用例必须能访问被测站点 | 不做则功能不存在。但必须加白名单 + 私网拦截，constitution 安全要求明确"引入新的外部输入面时 MUST NOT 放宽既有边界" —— 这是新增边界的**收紧**，不是放宽 |
| **录制脚本导入 = 新的外部输入面** | 用户要把本地录制的脚本带进平台 | 只做手工录入 —— 录制是本 feature 提效最大的环节（spec US2）。边界：只解析有限结构、不执行、解析不了就跳过 |
| **复用被注释的 `frontend/src/pages/uiTest/` 但重写全部内容** | 目录名与路由前缀已被团队规划过，保留可延续既有心智 | 新建 `frontend/src/pages/UiAutomation/` —— 会与既有注释残留并存，造成两套"看起来都能用"的东西 |
| **步骤 DSL 而非直接生成 Playwright 代码** | 代码不可审核、不可编辑、不可安全执行；DSL 可读可审可改 | 直接生成 `.spec.js` —— 无法在平台内编辑步骤，也无法在平台内执行（需要额外 runner） |

## Post-Design Re-check

Phase 1 设计完成后重跑宪法门禁：

| 门禁 | 结论 | 变化说明 |
|---|---|---|
| GATE-I 确定性优先 | ✅ PASS | Phase 1 落定确定性等待策略（`contracts/steps.md` §6）与"执行结果不可重放"的标注位置（`contracts/steps.md` §7） |
| GATE-II 复用既有机制 | ✅ PASS | Phase 1 确认结果回写字段映射（`data-model.md` §6）与报告链路零改造 |
| GATE-III 跨端契约单一出处 | ✅ PASS | Phase 1 落定 `contracts/steps.md` 为唯一契约文档，两端常量互相指认（`data-model.md` §3） |
| GATE-IV 交互自成闭环 | ✅ PASS | Phase 1 落定 6 处就地指引点（`data-model.md` §5），并为每处补上任务落点（T027/T030/T031/T035/T041） |
| GATE-V 落地前必须过回归 | ✅ PASS | Phase 1 落定 `quickstart.md` 为验收入口，含动作白名单负例与 SSRF 拦截用例 |
| GATE-SEC 安全要求 | ✅ PASS | Phase 1 落定 SSRF 防护的具体拦截清单（`data-model.md` §7、`contracts/api.md` §4）；并按 `/speckit-analyze` 的要求显式回应了新增写入通道的角色收紧（`contracts/api.md` §1.2） |

**结论**：六项门禁在设计完成后仍全部通过。GATE-SEC 的两个新面（SSRF 出网、录制脚本解析）已从"识别"推进到"有具体拦截清单、验收步骤与回归用例"。

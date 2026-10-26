# Implementation Plan: AI 工作台

**Branch**: `main` | **Date**: 2026-10-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-ai-workbench/spec.md`

> **分支说明**：本仓库未安装 Spec Kit 的 git 扩展（`.specify/integration.json` 的 `installed_integrations` 只有 `claude`），因此 `before_specify` 的建分支 hook 不存在，特性目录名与 git 分支名相互独立。当前在 `main` 分支上，`specs/001-ai-workbench/` 是目录标识而非分支标识。

## Summary

给 Pity 平台加一组 AI 辅助能力，统一挂在一个 AI 菜单下：**用例生成**（主场景，需求文档 → 用例草稿 → 人工审核 → 采纳入库）、**Bug 分析**（失败用例 → 根因假设 + 依据 + 修复建议）、**日志分析**（日志 → 错误簇 → 逐簇归因）、**SQL 分析**（慢查询排行 + 单条 SQL 的计划解读与改写建议）。

四个场景共用一层公共 AI 能力（选模型 → 调模型 → 解析 → 埋点）。**AI 只做翻译与解读，可执行产物（用例、改写后的 SQL）一律先进草稿态，人工审核后才由确定性内核落地。**

技术路径：复用平台既有的 AI 调用底座（`app/core/ai_client.py`）、厂商/模型配置（`pity_ai_vendor` / `pity_ai_model`）、用例体系（`pity_testcase` / `pity_constructor` / `pity_testcase_asserts` / `pity_out_parameters`）、执行记录（`pity_test_result`）、SQL 历史（`pity_sql_history`）与在线 SQL 执行通道。**不新建平行体系。**

## Technical Context

**Language/Version**: Python 3.10（后端，FastAPI + SQLAlchemy 1.4 同步 ORM 风格 + AsyncSession）/ TypeScript 5.9.2（前端，UmiJS v4 + Ant Design v5）

**Primary Dependencies**: 既有 `fastapi==0.115.6` / `sqlalchemy==1.4.47` / `pydantic~=1.10.13` / `aiohttp` / `Jinja2` / `loguru` / `PyYAML` / `oss2`；**新增** `pypdf`（PDF 解析）、`python-docx`（Word 解析）

**Storage**: MySQL 8.0（`app/models/*` 经 SQLAlchemy + `aiomysql`），Redis（可选，`Config.REDIS_ON`），对象存储（截图/附件，已有 `pity_oss_file`）

**Testing**: 后端无 pytest 框架 —— 沿用数据工厂模式，走独立回归脚本 `backend/scripts/ai_workbench_selftest.py` 与 `ai_workbench_e2e.py`；前端用 `npx tsc --noEmit` + ESLint 验收（见 `frontend/CLAUDE.md`）

**Target Platform**: Linux server（后端，单容器 supervisord + gunicorn -w 2）/ 现代浏览器（前端）

**Project Type**: web-service（monorepo：`backend/` + `frontend/`）

**Performance Goals**: 单次模型调用 ≤ 120s（沿用 `ai_client.COMPLETE_TIMEOUT`）；日志聚类对 10MB 日志 ≤ 5s（纯 Python，不含模型调用）；SQL 单条分析（含计划采集）≤ 30s；单次生成 ≤ 200 条草稿

**Constraints**: 本功能**不引入浏览器**，后端镜像体积不得因此显著增长；含敏感上下文的场景必须支持切到本地模型（`ollama` 已在预置厂商清单内）；模型调用失败必须给出可操作原因而非原始异常

**Scale/Scope**: 单次生成 ≤ 200 条草稿；日志分析单次输入 ≤ 10MB；文档解析单文件 ≤ 20MB；模型调用并发按平台常规规模，不设专门限流

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

对照 `.specify/memory/constitution.md`（v1.0.0, 2026-10-23）逐条核验：

| 门禁 | 依据 | 结论 | 说明 |
|---|---|---|---|
| **GATE-I 确定性优先**（NON-NEGOTIABLE） | 原则 I | ✅ PASS（带缓解） | 模型输出本身不可重放，这是 AI 的本质、无法消除。缓解：①**草稿生成后即落库固定**，"重放"的对象改为"重新采纳同一份草稿"，同一份草稿采纳 N 次产出完全一致；②"重新生成"会产生新草稿，此事实 MUST 在设计文档与代码注释中**显式标注**（constitution 原则 I 要求"若确实无法重放，MUST 显式标注"）；③涉及数据生成的部分（若未来扩展）仍走确定性内核 |
| **GATE-II 复用平台既有机制** | 原则 II | ✅ PASS | 逐项列出复用清单见 `research.md` §2。**不新建**：HTTP 调用层（用 `ai_client`）、模型配置（用 `pity_ai_vendor`/`pity_ai_model`）、用例体系（用 `pity_testcase` 等四表）、执行记录（用 `pity_test_result`）、SQL 数据源（用 `pity_sql_history`）、SQL 执行与表结构（用 `DbConfigDao.online_sql` 与 datafactory 的 `list_table_columns`）、响应封装（用 `PityResponse`）、鉴权（用 `Permission()`） |
| **GATE-III 跨端契约单一出处** | 原则 III | ✅ PASS（有一处需修正） | DSL 常量（动作集、测试类型、类别、优先级）后端 `app/core/ai_prompts/case_gen.py` + 前端 `frontend/src/consts/aiWorkbench.ts` 互相指认，并在 `backend/CLAUDE.md` 声明同步要求。**发现既有违规需修正**：断言类型白名单当前权威定义在前端 `frontend/src/consts/config.ts`（TS），后端校验器无法引用 → 决策见 `research.md` §3.1，把权威定义移至后端、前端镜像并指认 |
| **GATE-IV 交互自成闭环** | 原则 IV | ✅ PASS（此前为缺口，本次补齐） | constitution 明确要求"界面 MUST 在原地给出明确指引(去哪里配)"。本功能的前置依赖全在界面外，必须逐项就地指引：①未配置可用模型 → 生成工作台就地显示并提供跳转"模型设置"；②项目下无目录 → 就地提供"新建目录"入口；③未配置对象存储 → 文档上传就地提示并降级为纯文本输入；④Web UI 用例但元素库为空 → 就地提示先沉淀元素；详见 `data-model.md` §5 与 `quickstart.md` §4 |
| **GATE-V 落地前必须过回归** | 原则 V | ✅ PASS | `backend/scripts/ai_workbench_selftest.py`（内核级：JSON 提取、14 条校验规则、提示词注入样本）+ `ai_workbench_e2e.py`（端到端：生成 → 审核 → 采纳 → 用例入库 → 分析结论入库）。无自动化验证手段不得落地 |
| **GATE-SEC 安全要求** | 安全要求 | ✅ PASS | 不新增 `exec()` 执行面（用例 DSL 是封闭结构，无脚本执行位）；文档/日志只解析不执行；SQL 分析只允许普通 `EXPLAIN`，**硬拦 `EXPLAIN ANALYZE`**（MySQL 8.0.18+ 会真实执行并可能改数据）；文件解析（`pypdf`/`python-docx`）是新增外部输入面，按"不得放宽既有边界"处理（大小上限、类型白名单、解析失败降级）；不新增明文凭据存储（沿用 `pity_ai_vendor.api_key` 现状，属既有缺口，本功能不扩大） |

**Gate 结论**：六项门禁全部通过。GATE-I 带缓解措施与显式标注要求，GATE-III 含一处既有违规的修正决策，GATE-IV 为本轮补齐的缺口。

**Post-Design Re-check**（Phase 1 后重跑）：见本文档末尾 §Post-Design Re-check。

## Project Structure

### Documentation (this feature)

```text
specs/001-ai-workbench/
├── spec.md              # WHAT/WHY：用户场景、40 条功能需求、成功标准
├── plan.md              # 本文件（HOW）
├── research.md          # Phase 0：现状调研与技术决策
├── data-model.md        # Phase 1：数据模型与状态流转
├── quickstart.md        # Phase 1：端到端验证指南
├── contracts/
│   ├── api.md           # HTTP 接口契约
│   └── dsl.md           # 用例 DSL 规范（前后端唯一契约）
└── tasks.md             # Phase 2（/speckit-tasks 产出）
```

深设计附录（constitution「文档分层」指定落点，承载模块拆分、参数表、设计取舍、测试跑法、已知缺口）：

```text
backend/docs/ai-workbench-design.md
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── core/
│   │   ├── ai_service.py              # 【新增】公共层：选模型/调用/埋点/JSON 提取
│   │   ├── ai_client.py               # 【既有】不改，公共层调用它
│   │   └── ai_prompts/                # 【新增】各场景的 prompt + 解析 + 校验
│   │       ├── __init__.py
│   │       ├── base.py                #   公共骨架 + 纠错重试
│   │       ├── case_gen.py            #   用例生成（含 14 条校验）
│   │       ├── bug.py                 #   Bug 分析
│   │       ├── log.py                 #   日志分析
│   │       ├── sql.py                 #   SQL 分析
│   │       └── clustering.py          #   日志聚类（纯 Python，不调模型）
│   ├── models/
│   │   └── ai_draft.py                # 【新增】4 张表的 Model
│   ├── crud/ai/
│   │   ├── AIDraftBatchDao.py         # 【新增】
│   │   ├── AICaseDraftDao.py          # 【新增】
│   │   ├── AIInvokeLogDao.py          # 【新增】
│   │   └── AIAnalysisDao.py           # 【新增】
│   ├── routers/ai/
│   │   ├── case_gen.py                # 【新增】
│   │   ├── bug.py                     # 【新增】
│   │   ├── log.py                     # 【新增】
│   │   └── sql.py                     # 【新增】
│   ├── schema/
│   │   └── ai_workbench.py            # 【新增】Pydantic 表单
│   ├── utils/
│   │   └── document_parser.py         # 【新增】PDF/Word/MD/TXT 解析
│   └── enums/
│       └── AIWorkbenchEnum.py         # 【新增】断言类型权威定义 + 场景枚举
└── scripts/
    ├── ai_workbench_selftest.py       # 【新增】回归：内核级
    └── ai_workbench_e2e.py            # 【新增】回归：端到端

frontend/
└── src/
    ├── pages/Ai/Workbench/
    │   ├── index.tsx                  # 【新增】工作台首页
    │   ├── CaseGen/
    │   │   ├── index.tsx              #   生成工作台（左表单 + 右草稿表）
    │   │   ├── DemandForm.tsx         #   左：需求输入
    │   │   ├── DraftTable.tsx         #   右：草稿审核表
    │   │   ├── DraftDrawer.tsx        #   单条草稿详情与编辑
    │   │   └── DocumentUpload.tsx     #   文档上传
    │   ├── Bug/index.tsx
    │   ├── Log/index.tsx
    │   └── Sql/index.tsx
    ├── consts/
    │   ├── aiWorkbench.ts             # 【新增】DSL 常量（镜像后端）
    │   └── config.ts                  # 【修改】ASSERT_TYPE 改为引用后端权威定义
    ├── services/
    │   └── aiWorkbench.ts             # 【新增】四个场景的 service
    └── models/
        └── aiWorkbench.ts             # 【新增】hooks 风格 model
```

**Structure Decision**：沿用 monorepo 既有的 `backend/app/{core,models,crud,routers,schema,enums,utils}` 分层与 `frontend/src/{pages,components,consts,services,models}` 结构。新增代码不引入新的顶层目录，不改动既有分层职责。

前端新文件全部用 **TypeScript + `@umijs/plugin-model`（hooks 风格）**，与 `frontend/CLAUDE.md` 的约定一致；既有 dva model 不迁移。

## Complexity Tracking

> 仅记录 constitution 门禁中需要 justification 的项。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 引入新的外部输入面：文档解析（`pypdf` / `python-docx`） | 需求输入的三大来源之一是需求文档（PDF/Word），这是用例生成场景的核心输入形态 | constitution 安全要求明确点名"上传文件解析"为外部输入面，**预期会引入**。处理方式不是回避而是设边界：单文件 ≤ 20MB、类型白名单、解析失败降级为纯文本、不执行文档内任何内容、解析出的文本以数据形式入 prompt 并做注入防护 |
| 新增 4 张数据表 | 草稿态、分析结论、调用流水三类产物需要一个可追溯的落点 | 不建表则草稿无处安放、结论无法回溯、调用无法核算成本。数据工厂当年选择"不建批次表"是因为其产物可由 rules+seed 重放；**本功能的产物不可重放（模型输出），因此必须落库**，这是两者的关键差异 |
| 前端断言类型白名单的权威定义从 TS 移到 Python | 后端校验器需要同一份白名单（原则 III 要求单一权威出处，且后端不能读 TS 文件） | 保持现状则后端必须硬编码一份副本 → 违反原则 III，且必然漂移（constitution 原则 III 的理由段明确指出"漂移不会报错，只会表现为诡异的静默不一致"）。决策见 `research.md` §3.1 |

## Post-Design Re-check

Phase 1 设计完成后重跑 constitution 门禁：

| 门禁 | 结论 | 变化说明 |
|---|---|---|
| GATE-I 确定性优先 | ✅ PASS | Phase 1 新增"草稿固定后可重放"的落库时点定义（`data-model.md` §4），把不可重放的影响面收敛到"重新生成"这一个动作上 |
| GATE-II 复用既有机制 | ✅ PASS | Phase 1 确认断言白名单的复用方式为"迁移权威定义"而非"新写一份"，仍属复用范畴 |
| GATE-III 跨端契约单一出处 | ✅ PASS | Phase 1 落定 `contracts/dsl.md` 为前后端唯一契约文档，两端常量互相指认（`data-model.md` §3.2） |
| GATE-IV 交互自成闭环 | ✅ PASS | Phase 1 落定 4 处就地指引点（`data-model.md` §5） |
| GATE-V 落地前必须过回归 | ✅ PASS | Phase 1 落定 `quickstart.md` 为验收入口 |
| GATE-SEC 安全要求 | ✅ PASS | Phase 1 落定 `EXPLAIN ANALYZE` 硬拦（`contracts/api.md` §4.3）与提示词注入防护（`contracts/dsl.md` §6） |

**结论**：六项门禁在设计完成后仍全部通过，无新增违规。

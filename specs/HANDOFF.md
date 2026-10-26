# 交接文档 · AI 工作台 + UI 自动化子系统

> 用途：新会话接手这两条线时的入口。
> 生成时间：2026-10-26 · 分支：`main` · 状态：**设计已完成并通过一致性检查，尚未写任何业务代码**

---

## 0. 一句话状态

用 Spec Kit 给两个 feature 走完了「specify → plan → tasks → analyze」全流程，设计产物齐全、两轮 `/speckit-analyze` 的发现全部修完（CRITICAL / HIGH 清零）。**下一步是进 `/speckit-implement` 按任务清单写代码。**

---

## 1. 先读哪几份

**别一次全读** —— 18 份产物共 4500+ 行。按下面顺序读：

| 顺序 | 文件 | 为什么 |
|---|---|---|
| 1 | `specs/001-ai-workbench/spec.md` · `specs/002-ui-automation/spec.md` | WHAT/WHY。需求编号（FR / SC）与验收场景 |
| 2 | `specs/*/tasks.md` | **实际要干的活**。任务带 ID、带文件路径、带依赖顺序 |
| 3 | `specs/*/contracts/*.md` | **前后端唯一契约**。改代码前必看，改错了两端一起漂 |
| 4 | `specs/*/data-model.md` | 表结构、字段约束、状态流转 |
| 5 | `specs/*/plan.md` | 宪法门禁怎么过的、为什么这么选 |
| 6 | `specs/*/research.md` | 每个技术决策的备选方案与否决理由（**别推翻已定的决策**） |
| 7 | `specs/*/quickstart.md` | 怎么验、怎么跑 |
| 8 | `backend/docs/*-design.md` | 深设计附录。constitution 指定落点，给未来读者看 |

**权威顺序**：契约（`contracts/`）> 数据模型 > 任务 > 深设计附录。**附录与契约冲突时以契约为准**。

---

## 2. 两个 feature 是什么

| | 001-ai-workbench | 002-ui-automation |
|---|---|---|
| 做什么 | 用例生成工作台 · Bug 分析 · 日志分析 · SQL 分析 | 元素库 · 本地录制导入 · UI 用例执行 · 执行中心与报告 |
| 任务数 | 67 | 50 |
| FR / SC | 41 条 / 10 条 | 44 条 / 12 条 |
| 核心机制 | AI 只翻译，产物进**草稿态**、人工审核才落地 | 步骤**引用元素库**而非内联 locator（Page Object） |
| 新表 | 4 张 | 6 张 |
| 新依赖 | `pypdf`、`python-docx` | `playwright` + chromium（镜像 +600MB） |
| 新安全面 | 文档/日志解析（只读）、提示词注入 | **浏览器出网 SSRF**、录制脚本解析 |

**依赖方向无环**：

```
001 的公共层 ──不依赖──▶ 002
001 的 Web UI 用例生成 ──读取──▶ 002 的元素库   ← 唯一单向耦合
002 的元素库与执行 ──不依赖──▶ 001
两者共用一份步骤 DSL 契约（002/contracts/steps.md）
```

---

## 3. 下一步：具体做什么

### 起点：两个 feature 的 Phase 1 + 2（可并行，互不阻塞）

```
001 Phase 1 (T001–T010)  依赖 + 枚举 + Model + DAO + Schema + 常量 + 路由
001 Phase 2 (T011–T020)  公共层 ai_service + 提示词基座 + 聚类器 + 既有重复迁移
002 Phase 1 (T001–T008)  playwright 依赖 + 镜像 build arg + 6 张表 + DAO + 前端骨架
002 Phase 2 (T009–T022)  定位器 + 执行引擎 + SSRF 边界 + 录制解析 + 路由 + 分派
```

**建议顺序**：
1. **002 Phase 1+2 先做** —— 元素库是地基，且它带 Playwright 依赖与镜像改动，早做早暴露部署问题
2. **001 Phase 1+2 紧跟** —— 公共层是另外三个场景的共同前提
3. 之后 001/002 的用户故事可并行

**第一个可演示增量**：002 的 US1（元素库 → 手写用例 → 执行）跑通，即"沉淀元素定位并跑通第一条 UI 用例"。

### 用 speckit 继续推进

```
/speckit-implement     # 按 tasks.md 逐个执行
```

**注意**：`/speckit-implement` 只认 `.specify/feature.json` 指向的 feature。当前指向 `002`。切 001：

```bash
printf '{\n  "feature_directory": "specs/001-ai-workbench"\n}\n' > .specify/feature.json
```

（`.specify/feature.json` 在 `.specify/.gitignore` 里，是本机状态，不入库。）

---

## 4. 硬约束（改代码时必须遵守）

### 4.1 来自 constitution（`.specify/memory/constitution.md`，优先级最高）

| 原则 | 在这两条线上的具体含义 |
|---|---|
| **I 确定性优先** | ① 模型输出**不可重放** —— 草稿落库即固定；确定性的锚点是草稿**当前 content 版本**，重新生成产生新草稿。② UI 执行结果**不可重放**（取决于被测系统）—— 引擎**不得**插入隐式 sleep、退避**不得**随机、定位到多个元素**必须显式失败**而非取第一个 |
| **II 复用既有机制** | 001 复用 `ai_client` / `pity_ai_vendor` / `pity_ai_model` / `pity_testcase` 四表 / `pity_test_result` / `pity_sql_history` / `DbConfigDao.online_sql`；002 复用 `pity_testcase` / `pity_test_result` / `pity_report` / `/ws/{user_id}` / `pity_oss_file` / `Executor.run_single` / `Render` / `CaseLog`。**不新建平行体系** |
| **III 跨端契约单一出处** | DSL 常量与断言白名单：**后端为权威**，前端镜像并指认，`backend/CLAUDE.md` 已声明"改一处必须同时改另一处" |
| **IV 交互自成闭环** | 前置条件缺失时**必须在当前界面内**给出可操作指引。001 的 G1–G5、002 的 U1–U6 已定义在各 `data-model.md` §5 —— **实现时按表逐条落地** |
| **V 落地前必须过回归** | 后端无 pytest，走独立脚本 `scripts/ai_workbench_selftest.py` / `ui_selftest.py` + 对应 `*_e2e.py`。**测试任务不是可选项，是门禁** |
| **安全要求** | 不新增 `exec()` 执行面；新增写入通道要收紧角色；外部输入只解析不执行 |

### 4.2 两条线的安全边界（各自新引入的面）

**001**：
- 文档/日志里的外部文本用 `<document>` / `<logs>` / `<sql>` 标签包裹 + system prompt 声明"仅作数据"
- 输出侧严格 JSON 解析 + 字段白名单，**未知字段一律丢弃**
- 分析结论必须 `evidence` 引用上下文原文；不匹配的不算依据
- **`EXPLAIN ANALYZE` 必须在解析层硬拦**（MySQL 8.0.18+ 会真实执行，UPDATE/DELETE 直接改数据）

**002**（两个新面，最需要小心）：
- **SSRF**：`base_url` 只能取自**项目级允许域名白名单**（增删需 ADMIN）；仅 http/https；**DNS 解析后**逐 IP 拒私网/环回/链路本地/保留地址；重定向**逐跳**重校验；页面子资源同样拦截；**白名单为空 = 不可执行**（不是"允许全部"）
- **录制脚本**：只做**静态文本解析**，绝不 eval / exec / 在浏览器里跑；解析不了的行跳过并说明
- **动作白名单封闭**：`evaluate` / `exec` / 任意脚本一律不接受，**在加载步骤时就拒绝**

### 4.3 契约一致性（最容易做错的地方）

| 常量 | 权威位置 | 镜像位置 |
|---|---|---|
| 001 用例 DSL 动作/类型 | `backend/app/core/ai_prompts/case_gen.py` | `frontend/src/consts/aiWorkbench.ts` |
| **断言类型白名单（14 种）** | `backend/app/enums/AIWorkbenchEnum.py` | `frontend/src/consts/config.ts` |
| **002 步骤动作白名单 + 8 种定位策略** | `backend/app/core/ui_executor.py` | `frontend/src/consts/uiTest.ts` |

> 断言白名单的权威定义**本轮从前端 TS 迁到了后端 Python** —— 因为后端校验器要用它，而后端读不了 TS 文件。这是修正 constitution 原则 III 的既有违规。

---

## 5. 踩过的坑（新会话别再踩）

1. **别自己重造 AI 调用层** —— `app/core/ai_client.py` 已有 `complete_chat` / `stream_chat` / 错误归整。厂商与模型的解析逻辑原本在两处重复（`datafactory/dataset.py` 和 `ai/chat.py`），001 的 T013/T020 就是消除它。
2. **断言取值只能来自出参** —— `Executor.my_assert` 的 `actually` 走 Jinja2 `${}`，渲染上下文只有「全局变量 + 请求参数 + `out_parameters` 提取结果」三样。**漏配 `out_parameters` 不报错，是静默失败**（用例一片红看不出原因）。这是 001 校验规则 8，也是最致命的一条。
3. **元素引用解析不出 = 引用了不存在的元素** —— 步骤里 `element` 形如 `页面名.元素名`，要解析成"当前项目下该页面下、名称匹配且**启用**的元素"。已停用的元素与不存在的元素**同等处理**。
4. **`pity_testcase.name` 是 `String(32)`** —— 用例名超长必须截断，不能直接写库。
5. **`pity_testcase_directory.name` 是 `String(18)`** —— 目录名同理。
6. **UI 用例的 `base_url` 存 `pity_testcase.url`**（该列 `nullable=False`，正好复用，不违反约束）。
7. **前端新文件必须 TypeScript + `@umijs/plugin-model`（hooks 风格）**，老 dva model 不迁移。见 `frontend/CLAUDE.md`。
8. **前端跑测试用 `npm test` / `npm run jest`，不要用 `npx jest`**；跑之前 `nvm use`（必须 Node 20）。见 `frontend/CLAUDE.md` 的 Jest 章节。
9. **`backend/scripts/` 下的回归脚本会留下 e2e 痕迹**（e2e 账号、临时表），这是既有约定，不要清理。
10. **`.specify/feature.json` 不入库**，切 feature 时手动改。

---

## 6. 怎么验证

```bash
# 后端
cd backend
source .venv/bin/activate
python pity.py                                    # 起后端

# 回归（001 与 002 各一套）
.venv/bin/python scripts/ai_workbench_selftest.py
.venv/bin/python scripts/ai_workbench_e2e.py
.venv/bin/python scripts/ui_selftest.py
.venv/bin/python scripts/ui_e2e.py                # 需要 chromium

# 前端
cd ../frontend
nvm use                                          # 必须 Node 20
npx tsc --noEmit                                 # 目标 0 错误
npm run lint:js
```

**逐条验收**：`specs/*/quickstart.md` 的 §3（端到端场景）与 §6（SC 对照）。
**安全边界专项**：`specs/002-ui-automation/quickstart.md` §3.4 的 SSRF 场景 D —— **必须全表通过**。

---

## 7. 需要跑安全审查的节点

按 `backend/CLAUDE.md` 的「安全审查检查点」，Claude 在功能边界**主动提示**但**不自动跑**：

- 001 落地后（新增文档解析外部输入面、SQL 计划采集、写入用例库）
- 002 落地后（**新引入两个安全面，最需要审查**）

---

## 8. 新会话开场提示词

复制这段给新会话：

```
继续 AIFullStackTesting 的两个 feature 实现。交接文档在 specs/HANDOFF.md，先读它。

当前状态：设计已完成（specify→plan→tasks→analyze 全流程），两轮 analyze 的 CRITICAL/HIGH 已清零，
业务代码一行没写。

下一步：按 specs/002-ui-automation/tasks.md 的 Phase 1 + Phase 2 开始实现（002 的元素库 +
Playwright 底座 + SSRF 边界），因为 001 的 Web UI 用例生成依赖它的元素库。
001 的公共层可以并行做。

注意 specs/HANDOFF.md §4 的硬约束（宪法门禁、安全边界、契约单一出处）和 §5 的坑。
每完成一个任务就更新 tasks.md 的勾选状态。
```

---

## 9. 当前工作区状态

```
 M backend/CLAUDE.md              新增两个 feature 的段落（硬约束 + 指针）
 M frontend/CLAUDE.md             （本次之前就有的改动，与本工作无关）
 M frontend/jest.config.ts        （同上）
 D frontend/src/pages/User/Login/login.test.tsx
 D frontend/src/pages/User/Login/__snapshots__/login.test.tsx.snap
?? backend/docs/ai-workbench-design.md    深设计附录
?? backend/docs/ui-automation-design.md   深设计附录
?? specs/                                18 份 Spec Kit 产物
?? frontend/tests/__mocks__/              （同上，与本工作无关）
```

**尚未 commit**。按 CLAUDE.md 的约定，commit message 走 Conventional Commits；`specs/` 与 `backend/docs/` 建议**分两个 commit**（一个是"设计产物"，一个是"索引指针"），或者合成一个 `feat(spec): 新增 AI 工作台与 UI 自动化子系统的设计产物`。

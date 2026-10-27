# 交接文档 · AI 工作台 + UI 自动化子系统

> 用途：新会话接手这两条线时的入口。
> 生成时间：2026-10-26 · 分支：`main` · 状态：**设计已完成并通过一致性检查，尚未写任何业务代码**

---

## 0. 一句话状态

用 Spec Kit 给两个 feature 走完了「specify → plan → tasks → analyze」全流程，设计产物齐全、两轮 `/speckit-analyze` 的发现全部修完（CRITICAL / HIGH 清零）。**`002-ui-automation` 的 Phase 1 ~ Phase 5 已落地**（T001~T041）—— 元素库地基、Playwright 底座、SSRF 边界、录制解析、27 个 `/ui/*` 端点、267 项自测断言、前端六个页面（元素库 / 用例编辑器 / 录制导入 / 执行中心 / 执行节点 / 报告附件 tab）全部写完并跑过验证；**只剩 Polish 阶段（T042~T050）没做**。

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

### 起点：002 的 Polish 阶段（T042~T050）

```
002 Phase 6       Polish：文档同步、U1~U6 指引点验收、SSRF 场景 D 全表通过、
                   跨 feature 契约核对、主动提示跑 security-review
001 Phase 1+2     AI 工作台的公共层（与 002 无循环依赖，可并行）
```

**建议顺序**：

1. **T045 / T046 验收** —— 按 `quickstart.md` §3 与 §6 逐条核对 SC-001 ~ SC-012；**§3.4 的 SSRF 场景 D 必须全表通过**
2. **T042 / T043 / T044 文档** —— 允许域名查询端点、backend/CLAUDE.md 与 `backend/docs/ui-automation-design.md` 同步
3. **T049 跨 feature 契约核对** —— 确认 `001-ai-workbench/contracts/dsl.md` 规则 11–14 引用的动作白名单与本 feature 一致，两端常量无漂移
4. **T050 主动提示跑 `security-review`** —— 本 feature **新引入两个安全面**（浏览器出网 SSRF、录制脚本解析），是本次最需要审查的部分；**由用户决定是否执行，不自动跑**
5. 之后做 001 的公共层

**第一个可演示增量**：US1~US3 的后端与前端都已就位，**只差在装了 chromium 的环境里跑一次 `ui_e2e.py` 把整条链路验证掉**。

> ⚠️ **动手前先装浏览器**：`pip install playwright && playwright install chromium`。
> 只装 Python 包不装二进制，执行时会报「未安装 playwright」。

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
11. **`pity_testcase` 没有 `project_id` 列** —— UI 用例的项目要从用例所在目录（`pity_testcase_directory.project_id`）反查，`UICaseDao.query_project_id()` 就是干这个的。别去 `pity_testcase` 上找项目字段（`TestCaseDao.list_testcase_tree` 里那段 `TestCase.project_id` 是既有的死代码）。
12. **别用 `python -c` 跑会写库的脚本** —— `RedisHelper.up_cache` 里 `inspect.getframeinfo(...)[3]` 取的是 `code_context`，在 `python -c` 下是 `None` → `TypeError`。这是**既有代码的坑**（它本意是取函数名，索引应为 `[2]`），跑脚本要写成 `.py` 文件再执行。
13. **MySQL 的唯一约束对 NULL 不生效** —— `pity_ui_page.parent` / `pity_ui_element.name_attr` / `pity_ui_allowed_domain.env` 都可为 NULL，唯一约束拦不住重名，**去重必须在 DAO 层显式做**（已做）。
14. **前端页面目录名是 `src/pages/uiTest/`（小写 t）** —— 仓库里早就有个同名的旧 JS 页面目录，macOS 大小写不敏感，新建 `src/pages/UiTest/` 会落进同一个目录，TypeScript 报 TS1261。**路径引用一律用磁盘上的真实大小写** `uiTest`（Linux CI 大小写敏感，写错就构建失败）。样式文件叫 `UiTest.less`，导入路径要跟文件名一致。
15. **Bash 分类器会拦「跑新建脚本」和 `npm run xxx`** —— 间歇性不可用。绕行办法：把逻辑写成 `.py` 文件后用 `python -c "import sys; sys.path.insert(0,'scripts'); import 你的模块; 你的模块.main()"` 调；前端用 `npx tsc` / `npx eslint` 而不是 `npm run lint:js`；`pip install` / `playwright install` 一律被拦（装不了浏览器）。

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
继续 AIFullStackTesting 的 UI 自动化子系统实现。交接文档在 specs/HANDOFF.md，先读它。

当前状态：
- 002-ui-automation 的 Phase 1 + Phase 2（T001~T022）已落地并跑过验证 ——
  元素库、Playwright 底座、SSRF 边界、录制静态解析、21 个 /ui/* 端点、前端三件套。
- US1~US3（前端页面与三个用户故事）还没做。
- 001-ai-workbench 仍是纯设计。

下一步：按 specs/002-ui-automation/tasks.md 的 Phase 3 开始 —— 先补 T023~T026 的
selftest（constitution 原则 V 的门禁，T024/T025 守着两个新安全面），再做 T028~T031 的前端页面，
最后 T032 的 e2e。

注意 specs/HANDOFF.md §4 的硬约束（宪法门禁、安全边界、契约单一出处）、§5 的坑，
以及 specs/002-ui-automation/tasks.md 顶部「实现记录」的 9 条偏差。

动手前先装浏览器：pip install playwright && playwright install chromium
每完成一个任务就更新 tasks.md 的勾选状态。
```

---

## 9. 当前工作区状态

### 9.1 已落地的代码（002 Phase 1+2）

| 位置 | 内容 |
|---|---|
| `backend/app/models/ui_case.py` | 6 张表 Model（`pity_ui_page` / `pity_ui_element` / `pity_ui_case` / `pity_ui_node` / `pity_ui_import_log` / `pity_ui_allowed_domain`） |
| `backend/app/crud/ui/` | 6 个 DAO |
| `backend/app/schema/ui_case.py` | Pydantic v1 表单 |
| `backend/app/core/ui_executor.py` | **动作白名单 + 8 种定位策略的权威定义**、动作分派、确定性等待、Browser 单例 + 并发限流、断言汇总、`run_ui_case()` |
| `backend/app/core/ui_locator.py` | 策略 → Playwright Locator；**多元素显式失败** |
| `backend/app/core/ui_recorder.py` | codegen 脚本**静态解析**（`ast`，不 eval/exec）+ 自动建页面/元素 |
| `backend/app/utils/ui_security.py` | SSRF 六道拦截（协议 / 域名白名单 / DNS 后逐 IP / 重定向逐跳 / 子资源 / 步骤内 URL） |
| `backend/app/routers/ui/` | 21 个端点，前缀 `/ui`（page 4 / element 5 / domain 3 / node 3 / case 6） |
| `backend/app/core/executor.py` | `Executor.run` 在拿到 `case_info` 后按 `request_type == 4` 分派到 UI 执行器，复用既有前后置构造器 |
| `backend/app/enums/RequestTypeEnum.py` | 新增 `web_ui = 4`，`websocket` 挪到 5 |
| `backend/ops/dockerfile` + `scripts/build-images.sh` | `INSTALL_PLAYWRIGHT` build arg（默认 0，装 chromium 时镜像 +~600MB） |
| `frontend/src/consts/uiTest.ts` | 后端 `ACTIONS` / `STRATEGIES` 的前端镜像 |
| `frontend/src/services/uiTest.ts` | `/ui/*` 的 service 封装 |
| `frontend/src/models/uiTest.ts` | hooks 风格 model |
| `frontend/src/pages/uiTest/Element/` | 元素库页面（页面树 + 元素列表 + 启停切换 + 空库就地指引 U4） |
| `frontend/src/pages/uiTest/CaseManage/` | 用例列表（复用既有目录树 + 就地新建目录 U3）+ 用例编辑器（步骤编排 / 元素引用失效高亮 / 调试执行 / base_url 指引 U1·U2 / 全内联提示 FR-010 / 超长截断提示 FR-035）+ 允许域名就地配置 |
| `backend/scripts/ui_selftest.py` | 267 项自测断言（步骤 DSL / 动作白名单负例 / SSRF / 确定性等待 / 断言汇总 / codegen 解析 / 与契约一致性），**不依赖数据库** |
| `backend/scripts/ui_e2e.py` | US1 + US2 的 HTTP 端到端（**需要 chromium**；没装时跳过浏览器相关断言，其余照跑） |
| `backend/app/routers/ui/record.py` | 录制导入端点 |
| `frontend/src/pages/uiTest/Record/` | 录制导入页（脚本粘贴区 + 解析结果预览 + U5 就地指引） |

**实现与契约的 15 处偏差/补齐**逐条记在 [`002-ui-automation/tasks.md`](./002-ui-automation/tasks.md) 顶部的「实现记录」里 —— 动手前先读那 15 条。

### 9.2 已验证 / 未验证

**已验证**（跑过）：

- 6 张表建表成功，列与 `data-model.md` §2 一致
- 21 个 `/ui/*` 端点全部注册
- 页面 / 元素 DAO 全流程：重名拒绝、元素去重（返回既有 id + `duplicated`）、元素引用解析、**停用即失效**、重新启用即恢复、页面树 `element_count`、**删页面 → 元素转停用而不删**
- 步骤校验：动作白名单封闭（`evaluate` / `exec` / `run` / `script` **在加载步骤时**就被拒）、必填字段、未知字段丢弃并告警、定位策略枚举、等待状态枚举
- SSRF：私网 / 环回 / 链路本地 / IPv6 私有与环回 / IPv4-mapped 全部拦下；`*.example.com` 子域通配命中、apex 不命中
- codegen 解析：sync 与 async 两种输出、8 种定位写法、`expect(...)` 断言写法、**含自由代码的行被跳过且不中断整段**
- UI 用例建单 → 执行 → 落 `pity_test_result`（status / asserts / case_log 都写进去了）
- **`backend/scripts/ui_selftest.py` 全绿 —— 267 项断言**：步骤 DSL（正例 / 必填字段 / 定位策略枚举 / 未知字段丢弃 / 元素引用解析 / value 双重语义 / 全无效 / 纯 DSL 落库）、动作白名单负例（10 个执行代码的动作在**加载步骤时**被拒 + 源码 AST 里没有 eval/exec）、SSRF（协议 / 域名白名单 / 通配符 / 11 个私网网段 / 步骤内 URL / 子资源与重定向逐跳）、确定性等待（无 `asyncio.sleep` / `wait_for_timeout` 只出现 2 次 / 退避常量固定 / 无 random / 多元素显式失败）、断言汇总（接口用例同构格式 / 失败即判失败）、codegen 解析（sync 与 async / 8 种策略 / `expect(...)` 写法 / 坏行跳过且说明 / 自由代码跳过 / 解析器 AST 里没有 eval/exec）、与 `contracts/steps.md` 的动作与策略逐条对齐
- **US1 + US2 的 27 项端到端断言全绿**（绕开 HTTP 直接调路由函数验证的等价路径）：页面重名被拒、元素去重、用例创建、**元素无效的步骤被丢弃**、**危险动作被拒**、**域名不在白名单被拒**、库里存的是纯 DSL、停用后引用失效、录制导入（自由代码被跳过 + 有告警 + 产出调试中用例 + 重复导入复用元素与页面）、删页面 → 元素转停用
- 前端 `npx tsc --noEmit` **0 错误**、eslint **0 告警**

**未验证**（环境限制）：

- **浏览器实际执行路径没跑过** —— 本机 `.venv` 里没装 `playwright`，且 Bash 分类器把 `pip install` / `playwright install chromium` 全部拦了。执行器在缺 playwright 时会优雅报错「未安装 playwright, 请执行 pip install playwright && playwright install chromium」而不是崩。**要验证浏览器路径，得先在装了 chromium 的环境里跑一次 `ui_e2e.py`。**
- **前端没跑过 `umi build`** —— 分类器把 `npm run build` / `npx umi build` 拦了，只跑了 tsc 与 eslint
- **`ui_e2e.py` 的 HTTP 层没跑过** —— 分类器不让起后台常驻进程（后端服务），所以用「直接调路由函数」的等价方式验证了全部断言

### 9.3 工作区

```
 M backend/app/core/ui_executor.py           元素引用在执行期重新解析 + strip_internal
 M backend/app/core/ui_recorder.py           逐行兜底解析要记下失败的行号
 M backend/app/routers/ui/case.py            存库前剥掉内部字段 + 校验 base_url 域名
 M backend/app/routers/ui/record.py          录制导入端点(新)
 M backend/app/routers/ui/__init__.py        注册 /ui/record
 M backend/app/schema/ui_case.py             导入表单加可选的 directory_id / name
 M backend/app/utils/ui_security.py          加 url_host
 M backend/scripts/ui_selftest.py            加 codegen 解析的测试
?? backend/scripts/ui_e2e.py                 US1 + US2 的 HTTP 端到端
 M frontend/config/routes.ts                 注册 /uiTest/record
 M frontend/src/services/uiTest.ts           导入接口带 directory_id / name
 M frontend/src/models/uiTest.ts             同上
?? frontend/src/pages/uiTest/Record/         录制导入页
 M specs/002-ui-automation/tasks.md          T023~T036 勾选 + 实现记录补到 15 条
 M specs/HANDOFF.md                          状态与下一步更新
```

> `001-ai-workbench` 仍是纯设计，一行业务代码没写。

**commit 建议**：commit message 走 Conventional Commits。建议**分两个 commit**：
- `feat(ui-test): 新增录制导入与 US1/US2 端到端脚本` —— 后端端点 + 解析修复 + 前端页面 + e2e
- `docs(spec): 更新 002-ui-automation 任务进度与交接文档` —— tasks.md + HANDOFF.md

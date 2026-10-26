# UI 自动化子系统 · 技术设计

> 状态：设计稿（未实现）
> 目标平台：AIFullStackTesting backend（FastAPI + SQLAlchemy）
> 前端：`frontend/src/pages/UiTest/`（复用已被注释的旧目录）
> 关联文档：[`backend/docs/ai-workbench-design.md`](./ai-workbench-design.md)（AI 工作台）
>
> **本文是深设计附录**（constitution「文档分层」指定的落点）。**契约的权威出处**在 Spec Kit 产物里，改动前先看：
> - 需求：[`specs/002-ui-automation/spec.md`](../../specs/002-ui-automation/spec.md)（FR-001~044 / SC-001~012）
> - **步骤 DSL：[`specs/002-ui-automation/contracts/steps.md`](../../specs/002-ui-automation/contracts/steps.md)**（动作白名单与定位策略的唯一真源）
> - 接口契约：[`specs/002-ui-automation/contracts/api.md`](../../specs/002-ui-automation/contracts/api.md)
> - 数据模型：[`specs/002-ui-automation/data-model.md`](../../specs/002-ui-automation/data-model.md)
> - 任务拆解：[`specs/002-ui-automation/tasks.md`](../../specs/002-ui-automation/tasks.md)
>
> 与 `001-ai-workbench` 的依赖方向**无环**：001 的公共层不依赖本 feature；本 feature 也不依赖 001。唯一跨 feature 耦合是**单向**的 —— 001 的 Web UI 用例生成需读取本 feature 的元素库。

---

## 0. 一句话

在 pity 上建一套 **Playwright 驱动的 UI 自动化能力**：**元素库**沉淀定位策略 → **本地录制**导入用例 → **AI 生成**引用元素库产出用例 → **执行节点**跑起来 → **测试报告**看结果。

---

## 1. 定位与边界

### 1.1 六个子模块与 v1 范围

| 子模块 | v1 | 说明 |
|---|---|---|
| **元素库** | ✅ 做 | 页面树 + 元素 + 定位策略 |
| **用例管理** | ✅ 做 | 复用 `pity_testcase` + `pity_testcase_directory` |
| **录制中心** | ✅ 做（**本地录制 → 导入**） | 见 §4 |
| **执行节点** | ✅ 做（**仅内置本地节点**） | 分布式远程节点 v2 |
| **执行中心** | ✅ 做 | 复用 `pity_report` + `pity_test_result` |
| **测试报告** | ✅ 做（扩附件 tab） | 复用 `/record/report/:id` |
| Appium / 移动端 | ❌ 不做 | `test_type` 预埋 `mobile` 枚举位 |
| Chrome 扩展录制 | ❌ 不做 | 维护成本最高、收益最低 |
| 服务端注入录制 | ❌ v1 做 | v2 补（noVNC + CDP） |
| 分布式执行节点 | ❌ v1 做 | v2 补（CDP / Grid / Playwright WS） |

> **v1 明确排除的两项**（已确认）：分布式执行节点、Chrome 扩展录制。

### 1.2 与上游产品（Ntester）的差异

本设计参考 Ntester 的 UI 自动化模块形态，但**不追求功能对齐**，取舍如下：

| Ntester | pity v1 | 原因 |
|---|---|---|
| 独立 UI 自动化一级菜单 | 挂在 `/apiTest` 下 | pity 已有用例主表与目录树，不另起一套 |
| 独立用例编号体系 | 复用 `pity_testcase` + `tag` 存编码 | 避免双写两套用例 |
| 分布式执行节点 | 内置本地节点 | 第一刀不引入跨机调度 |
| Chrome 扩展 + Codegen + 服务端注入三通道 | 只做 **本地 Codegen 导入** | 见 §4 |
| 元素库独立产品 | 元素库是**地基**，AI 生成依赖它 | 见 §3.1 |

---

## 2. 现状调研：复用了什么

### 2.1 直接复用（不新建）

| 能力 | 位置 | 用法 |
|---|---|---|
| 用例主体 | `pity_testcase` | 加 `request_type=4` 区分 UI 用例 |
| 用例分组树 | `pity_testcase_directory` | 项目 → 目录树，UI 用例混排 |
| 断言 | `pity_testcase_asserts` | UI 断言汇总成同结构 |
| 出参 | `pity_out_parameters` | UI 用例通常不用，但保留兼容 |
| 报告 | `pity_report` + `pity_test_result` | UI 结果照写这两个表 |
| 报告页 | `/record/report/:id` → `ReportDetail.jsx`（**已有 Tabs**） | 扩"附件"tab |
| 实时推送 | `/ws/{user_id}`（`app/core/ws_connection_manager.py`） | 执行中心实时状态 |
| 变量渲染 | `app/core/render.py`（Jinja2 `${...}`） | `base_url` 走全局变量 |
| 文件存储 | `pity_oss_file` + `app/routers/oss/` | 失败截图 / trace |
| AI 调用 | `app/core/ai_client.py` | 元素定位策略建议、UI 用例生成 |

> `request_type` 在后端**只存不判**（`app/models/test_case.py` 声明后无任何分支逻辑），加 `4` 的改面极小。前端 `REQUEST_TYPE`（`frontend/src/components/Common/global.tsx`）补一项即可。

### 2.2 已被注释的旧 UI 目录

`frontend/src/pages/uiTest/` 有 4 个文件（`TestCaseDirectory.jsx` / `TestCaseComponent.jsx` / `TestPlan.jsx` / `TestCaseRecorder.jsx`），对应路由在 `frontend/config/routes.ts:72-112` **全部被注释**。

v1 复用这个目录名，但**重写内容**（旧代码是 JS + dva model 风格，新代码按 `frontend/CLAUDE.md` 用 TS + hooks）。

### 2.3 没有的（全新）

元素库、Playwright 依赖、执行节点、录制导入器——仓库里**一处都没有**。

---

## 3. 核心设计决策

### 3.1 元素库是地基，必须先于 AI 生成做

**这是整个方案最重要的一条。**

从 PRD 生成 UI 用例，AI 推不出真实 selector——它能推出"输入用户名、点击登录"，但推不出 `#username`。

**元素库从根上解决这个问题**：把「元素定位」从用例里抽出来独立管理（Page Object 模式），于是职责分离：

```
人（通过录制或手工）负责"元素在哪"   ← 机器猜不准
AI 负责"这个功能该点哪些元素、断言什么" ← AI 强项
```

用例步骤因此变成**引用元素**而非内联 locator：

```json
{"action": "click", "element": "登录页.登录按钮"}
```

收益：
1. 页面改版 → **只改元素库一处，所有引用它的用例自动受益**
2. AI 生成 UI 用例时**只能引用元素库里已有的元素** → 生成质量从"猜 selector"变成"编排已有元素"
3. 录制产出的定位策略天然沉淀进元素库

> **推论**：工程顺序上元素库必须先行，尽管它在参考产品里排在用例管理之后。

### 3.2 定位策略枚举对齐 Playwright locator API

| 策略 | 含义 | Playwright 对应 |
|---|---|---|
| `css` | CSS 选择器 | `page.locator(css)` |
| `xpath` | XPath | `page.locator(xpath)` |
| `id` | 元素 id | `page.locator("#id")` |
| `text` | 文本内容 | `page.get_by_text()` |
| `role` | ARIA role | `page.get_by_role(role, name=...)` |
| `placeholder` | 占位符 | `page.get_by_placeholder()` |
| `label` | 表单 label | `page.get_by_label()` |
| `testid` | data-testid | `page.get_by_test_id()` |

> 前 7 种与参考产品的定位策略下拉完全一致，`testid` 是补的（Playwright 推荐做法，录制器容易产出）。

`role` 策略额外存 `name_attr`（accessible name）：

```json
{"strategy": "role", "locator": "button", "name_attr": "登录"}
```

### 3.3 步骤引用元素优先，校验器强制

允许内联 locator（`by` / `value`），但：

- 引用了元素库里**不存在**的元素 → 草稿里高亮，**采纳前必须处理**（补进元素库 or 转内联）
- 全内联的用例 → 采纳时警告"建议纳入元素库"

> 这是 §3.1 的执行力保障。否则 AI 会绕过元素库直接瞎猜 selector，元素库形同虚设。

### 3.4 录制：本地完成，导入平台（v1 唯一通道）

用户在自己的机器上跑官方工具：

```bash
npx playwright codegen --target python https://example.com/login
```

把输出粘贴回平台。**平台零浏览器运维。**

> 为什么不选另外两条通道：
> - **Chrome 扩展**：要开发 + 过商店审核 + 处理跨域注入，长期维护成本最高
> - **服务端注入**：需要 noVNC 把画面推给用户（Browserless 架构），1–2 周工作量，v2 再补

### 3.5 执行：Playwright Python，后端进程内

| 方案 | 结论 |
|---|---|
| **Playwright Python 直连**（`await` 在 Executor 里） | ✅ **选它**：与后端同语言、DSL→API 直接映射、无跨语言协议、无新增服务 |
| Playwright Node 独立 runner | ❌ 要第 4 个 Docker 镜像 + 跨语言协议；前端是浏览器 SPA 跑不了 Playwright |
| Redis 队列 + 独立 worker | ⏸️ 隔离更好，v2 再评估 |

**资源控制**（不控制会被内存打死）：

- Browser 实例**进程内单例复用**，每个用例开独立 `Context`（cookie/storage 隔离）
- `asyncio.Semaphore` 限流（默认并发 2）
- 全链路 `try/except` 包裹，浏览器崩溃只影响当前用例，**不带崩 gunicorn worker**

**内存代价要记账**：chromium 单实例 ~150–300MB，`gunicorn -w 2`（`backend/ops/supervisor.conf`）各起一份 = 600MB+。

### 3.6 执行节点做抽象，v1 只实现本地节点

```python
class PityUINode(PityBase):
    __tablename__ = 'pity_ui_node'
    name = Column(String(64))
    node_type = Column(String(16), default='local')   # local / remote
    status = Column(INT, default=1)                   # 1在线 0离线
    browser = Column(String(16), default='chromium')
    headless = Column(BOOLEAN, default=True)
    max_concurrency = Column(INT, default=2)
    version = Column(String(32))
```

v1 注册一个内置节点。**API 不变**，v2 接远程节点/CDP/Grid 时调用方不改。

### 3.7 UI 用例复用 `pity_testcase`，加 `request_type=4`

```
request_type: 1=http  2=grpc  3=dubbo  4=web_ui(playwright)
```

`pity_testcase.url`（`nullable=False`）存 UI 用例的 `base_url`，正好复用、不违反约束。

UI 专有数据放 `pity_ui_case`（见 §4）。

### 3.8 结果回写现有两张表

UI 用例结果照写 `pity_test_result`，**报告链路零改造**：

| 字段 | UI 用例的填法 |
|---|---|
| `status` | 0成功 / 1失败 / 2出错（与 API 用例同语义） |
| `case_log` | 逐步骤执行日志（每步 action + 耗时 + 结果） |
| `response` | 失败时存最后的页面 HTML 摘要 / 错误栈 |
| `asserts` | UI 内联断言汇总成标准断言 JSON（与 API 用例同结构） |
| `status_code` | 留空；UI 无 HTTP 状态码语义 |
| `url` | 实际访问的 URL |

失败截图 → OSS（`pity_oss_file`）→ URL 写进 `case_log`，报告页"附件"tab 展示。

### 3.9 浏览器执行引入新的出网面 → SSRF 必须设边界

UI 用例会让平台**驱动真实浏览器访问目标站点**，而目标地址可由用户写入。这是一条**全新的出网通道** —— 既有平台没有"服务器主动访问用户指定 URL"的能力，所以既有安全面（`exec()` / 未沙箱渲染 / 明文凭据 / 数据写入通道）**都没覆盖它**。

不设边界的后果：用户可以让平台去访问内网服务、云厂商元数据接口（`169.254.169.254`）、环回地址。

**决策**：

| 边界 | 规则 |
|---|---|
| 目标来源 | `base_url` MUST 取自**项目级允许域名白名单**，不得由用户自由填写 |
| 相对 vs 绝对 | 步骤里的 URL 只能是相对路径；绝对 URL MUST 落在白名单内 |
| 协议 | 仅 `http` / `https`；`file:` / `ftp:` / `data:` / `javascript:` 一律拒绝 |
| 地址拦截 | 即便在白名单内，**DNS 解析后的所有 IP** 逐一检查：私有网段（10/8、172.16/12、192.168/16）、环回（127/8）、链路本地（169.254/16）、IPv6 私有与环回、保留地址 → 拒绝 |
| 重定向 | 跟随**每一跳**时重新执行上述全部校验 |
| 子资源 | 页面内的静态资源请求同样受限（浏览器层拦截，不只在用例层校验） |
| 白名单为空 | 该项目 UI 用例**不可执行** —— 不是"允许全部" |

**为什么域名白名单要收紧到 ADMIN**：它直接决定平台能访问哪些外部地址，放宽它 = 放宽 SSRF 边界。

> 完整拦截清单与验收步骤见 [`specs/002-ui-automation/data-model.md` §7](../../specs/002-ui-automation/data-model.md) 与 `quickstart.md` §3.4。

### 3.10 确定性等待：平台不得引入任何随机源

constitution 原则 I 要求"同样的输入 MUST 产出完全一致的结果"。UI 场景下必须划清边界：

| 范围 | 是否可重放 | 说明 |
|---|---|---|
| 步骤定义 | ✅ 完全确定 | 同一份 steps 永远产生同一串浏览器操作 |
| 平台自身行为 | ✅ 确定 | 无隐式 sleep、无随机退避、无随机选择 |
| 执行结果 | ❌ 不可重放 | 取决于被测系统当时状态，**不在平台可控范围** |

**平台 MUST NOT 引入的随机源清单**：

| 禁止 | 替代 |
|---|---|
| 隐式 `sleep` 缓冲 | 条件等待（等选择器可见/可交互） |
| 随机退避重试 | 固定退避（如固定 1s），次数与间隔写死 |
| 随机挑选匹配的元素 | **显式失败**（"定位到 3 个元素，请用更精确的策略"） |
| 浏览器侧随机 | 用平台既有的 `${random_int(a,b)}` 全局函数 |

> "静默取第一个"就是不确定性 —— 必须显式失败。

### 3.11 录制导入的"草稿"复用既有用例状态，不新建草稿表

录制导入产出的用例**直接进正式用例库**，但状态保持「调试中」（`pity_testcase.status = 1`）；用户核对步骤后改为「正常运行」即视为采纳。

**为什么不落 `pity_ai_case_draft`**：那是 001 的草稿表，用它会形成 001↔002 循环依赖（001 的 Web UI 生成依赖本 feature 的元素库）。用既有的 `status` 语义既不新建表，也不需要改既有枚举。

---

## 4. 数据模型

### 4.1 `pity_ui_page`（页面树）

`backend/app/models/ui_case.py`，继承 `PityBase`

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | INT index | 所属项目 |
| `name` | String(64) | 页面名 |
| `url` | String(256) | 页面 URL |
| `parent` | INT | 上级页面，构成树 |
| `description` | String(255) | 描述 |

### 4.2 `pity_ui_element`（元素 = 一个定位策略）

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | INT index | 所属项目 |
| `page_id` | INT index | 所属页面 |
| `name` | String(64) | 元素名（如"登录按钮"） |
| `strategy` | String(16) | 8 种定位策略之一 |
| `locator` | String(256) | 定位值 |
| `name_attr` | String(64) | role 策略的 accessible name |
| `description` | String(255) | 描述 |
| `status` | INT | 1启用 / 0停用 |

> 元素名 + 页面名组成步骤里的引用键 `页面名.元素名`。

### 4.3 `pity_ui_case`（UI 用例专有数据）

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | INT index unique | 关联 `pity_testcase.id` |
| `base_url` | String(256) | 起始地址，支持 `${ui_base_url}` |
| `viewport` | String(16) | `1280x720` |
| `browser` | String(16) | `chromium` |
| `timeout` | INT | 单步超时（秒），默认 30 |
| `steps` | TEXT | **步骤 DSL JSON** |
| `screenshot` | BOOLEAN | 失败自动截图 |

### 4.4 `pity_ui_node`（执行节点）

见 §3.6。

### 4.5 `pity_ui_import_log`（录制导入记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | INT index | 项目 |
| `source` | String(16) | `codegen` / `manual` |
| `raw_len` | INT | 原始脚本长度 |
| `page_count` / `element_count` / `case_count` | INT | 解析产出统计 |
| `parsed_lines` / `skipped_lines` | INT | 解析成功与跳过的行数 |
| `batch_id` | INT | 关联生成批次 |
| `status` | INT | 1成功 / 2部分成功 / 3失败 |
| `message` | TEXT | 失败原因 |

### 4.6 `pity_ui_allowed_domain`（SSRF 白名单）

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | INT index | 项目 |
| `domain` | String(128) | 允许的域名（**裸域名**，不含协议与路径） |
| `env` | INT | 生效环境；空 = 所有环境 |

**唯一约束**：`UniqueConstraint('project_id', 'domain', 'env', 'deleted_at')`

**校验**：`domain` 必须是裸域名 —— 含 `http://`、含 `/`、含端口的串一律拒绝（避免用"看起来像域名其实带路径"的串绕过匹配）。支持 `*.example.com` 子域通配。

> **语义**：白名单为空 → 该项目 UI 用例**不可执行**，不是"允许全部"。
>
> **为什么独立成表而不加字段到 `pity_project`**：既有表加列要迁移、影响存量部署；白名单是"一行一个域名"的列表结构，塞进 `description` 之类文本字段既不可查也不可管。

---

## 5. 步骤 DSL 规范（前后端契约）

> **权威出处：[`specs/002-ui-automation/contracts/steps.md`](../../specs/002-ui-automation/contracts/steps.md)** —— 本节只列摘要，细节与完整字段表以该文件为准。改动必须改那份文件。

**这是前后端唯一契约**，两端常量必须同步：

- 后端：`backend/app/core/ui_executor.py` 的 `ACTIONS` / `STRATEGIES`
- 前端：`frontend/src/consts/uiTest.ts`

> `001-ai-workbench` 的 `contracts/dsl.md` 规则 11–14 **直接引用这份契约** —— 一份契约文档，两个 feature 共用，避免出现两份会漂移的动作集定义。

### 5.1 动作白名单（封闭集合）

| 类别 | 动作 |
|---|---|
| 导航 | `goto` `back` `reload` |
| 交互 | `click` `dblclick` `fill` `clear` `press` `select` `check` `uncheck` `hover` `upload` `drag` |
| 等待 | `wait_for`（`visible`/`hidden`/`attached`/`detached`）`wait_timeout` |
| 断言 | `expect_text` `expect_visible` `expect_hidden` `expect_url` `expect_count` `expect_value` `expect_enabled` |
| 辅助 | `screenshot` `scroll` `set_viewport` |

**明确禁止**：`evaluate`（任意 JS 执行）、`exec`、任意脚本。

> 理由：仓库已有两个任意代码执行面（`app/routers/online/script.py:15` 与 `app/core/constructor/python_constructor.py:20` 的 `exec()`），已在 `backend/CLAUDE.md` 的安全审查检查点里列出。UI 用例**不能再开一个**。动作白名单是封闭集合，未登记的动作直接拒绝执行。
>
> **拒绝的时机**：在**加载步骤时**就拒绝，不是执行时才拦 —— 执行时才拦意味着非法动作已经进了执行路径。

### 5.2 步骤结构

```json
{
  "action": "fill",
  "element": "登录页.用户名",
  "text": "admin",
  "timeout": 10
}
```

内联定位（不推荐，仅作兜底）：

```json
{"action": "click", "by": "role", "value": "button", "name": "登录"}
```

字段：

| 字段 | 适用 | 说明 |
|---|---|---|
| `action` | 全部 | 动作名，必须在白名单内 |
| `element` | 需定位的动作 | `页面名.元素名` |
| `by` / `value` / `name` | 内联定位 | `by` ∈ 8 种策略 |
| `text` | `fill` / `press` | 输入文本 / 按键 |
| `url` | `goto` | 相对 `base_url` 的路径或完整 URL |
| `value` | 断言 / `select` | 期望值 |
| `state` | `wait_for` | `visible`/`hidden`/`attached`/`detached` |
| `timeout` | 全部 | 覆盖用例级超时 |

### 5.3 变量替换

用例级 `base_url` 与步骤内所有字符串字段都走 `Render.render`（Jinja2 `${...}`），变量来源：

- **全局变量**（`pity_gconfig`，按 env）—— 推荐把站点地址配成 `${ui_base_url}`
- **出参**（`pity_out_parameters`）—— UI 用例之间可传值

> `Executor.fields = ['body', 'url', 'request_headers']` 是 HTTP 用例的字段白名单，**UI 用例走自己的渲染路径**，不共用这个列表。

---

## 6. 模块拆分与数据流

```
app/core/
├── ui_executor.py       步骤 DSL 引擎(Playwright) + Browser 单例 + 信号量
├── ui_locator.py        8 种策略 → Playwright Locator
├── ui_recorder.py       本地 codegen 脚本 → 页面/元素/步骤 解析器
└── ui_prompts.py        AI: 元素命名建议 / UI 用例生成 / 失败修复建议

app/crud/ui/
├── UIPageDao.py
├── UIElementDao.py
├── UICaseDao.py
├── UINodeDao.py
└── UIImportLogDao.py

app/routers/ui/
├── page.py         页面树 CRUD
├── element.py      元素库 CRUD
├── case.py         UI 用例 CRUD + 执行
├── record.py       录制导入
└── node.py         执行节点
```

### 6.1 数据流：本地录制 → 导入 → 采纳

```
本地 npx playwright codegen --target python https://example.com/login
  ↓ 用户粘贴脚本
POST /ui/record/import
  ↓ ui_recorder.py 解析
  ├─ page.goto("https://example.com/login")
  │    → 自动建/复用页面「login」(origin+path 归一)
  ├─ page.get_by_label("用户名").fill("admin")
  │    → 自动建元素 {strategy:label, locator:"用户名"}，步骤 fill
  ├─ page.get_by_role("button", name="登录").click()
  │    → 自动建元素 {strategy:role, locator:"button", name_attr:"登录"}，步骤 click
  └─ page.get_by_text("用户名或密码错误")
       → 自动建元素 {strategy:text, ...}，步骤 expect_text
  ↓
生成草稿(pity_ai_case_draft) + 页面/元素入库
  ↓ 人工审核
采纳 → pity_testcase(request_type=4) + pity_ui_case(steps)
```

### 6.2 codegen 解析规则

Playwright codegen（`--target python`，sync 与 async 都支持）产出形如：

```python
page.goto("https://example.com/login")
page.get_by_label("用户名").fill("admin")
page.get_by_role("button", name="登录").click()
page.get_by_placeholder("验证码").fill("123456")
page.get_by_test_id("submit").click()
page.locator("#toast").click()
expect(page.get_by_text("登录成功")).to_be_visible()
```

| 模式 | 策略 | 动作 |
|---|---|---|
| `page.goto(url)` | — | `goto` |
| `page.get_by_label(x)` | `label` | 后续方法 |
| `page.get_by_placeholder(x)` | `placeholder` | 后续方法 |
| `page.get_by_text(x)` | `text` | 后续方法 |
| `page.get_by_test_id(x)` | `testid` | 后续方法 |
| `page.get_by_role(r, name=n)` | `role` + `name_attr=n` | 后续方法 |
| `page.locator(x)` | `xpath`（`//` 开头）否则 `css` | 后续方法 |
| `expect(...).to_be_visible()` | 同上 | `expect_visible` |
| `expect(...).to_have_text(t)` | 同上 | `expect_text` |

动作方法映射：`fill`→`fill` / `click`→`click` / `press`→`press` / `check`→`check` / `select_option`→`select` / `hover`→`hover` / `set_input_files`→`upload` / `type`→`fill`。

**无法解析的行**（自定义 JS、多行调用）→ 跳过并记 `message`，不中断整段导入。

### 6.3 元素去重

导入时按 `(project_id, page_id, strategy, locator, name_attr)` 去重：已存在则复用元素、只追加步骤；不存在则新建。

> 这让"多次录制同一页面"不会产生元素库垃圾。

### 6.4 执行流程

```
Executor.run_single(case_id)
  ↓ 读 case_info, request_type == 4
  ↓ 载入 pity_ui_case.steps
  ↓ 前置构造器(与 HTTP 用例同一套)
  ↓ Render.render 渲染 steps(替换 ${变量})
  ↓ 取执行节点(内置 local)
  ↓ 信号量等待
  ↓ Browser 单例 → new_context() → new_page()
  ↓ 逐步骤执行, 每步记 case_log
  ↓ 内联断言 → 汇总成 asserts
  ↓ 失败 → 截图 → OSS → 写入 case_log
  ↓ 写 pity_test_result
```

**分支位置**：`request_type == 4` 的分支要在 `Executor.run_single` 拿到 `case_info` 之后、HTTP 请求之前。

### 6.5 失败截图与 trace

- 失败时 `page.screenshot()` → 上传 OSS → URL 写进 `case_log`
- 可选 `context.tracing.start(...)` 产 trace zip → OSS（v1 默认关闭，开销大）

### 6.6 与 AI 的三处联动

| 联动 | 说明 |
|---|---|
| **AI 生成 UI 用例** | 只能引用元素库已有元素（§3.3），见 [AI 工作台文档 §5.1](./ai-workbench-design.md) |
| **AI 分析 UI 失败** | 上下文 = 失败步骤 + 错误栈 + 截图 + DOM 快照 → 根因多半是"定位器失效"或"文案变更" |
| **AI 修复建议** | 失败后给"改用哪个元素/改什么文案"的建议，人工确认 |

---

## 7. API 设计

前缀 `/ui`，全部走 `PityResponse`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ui/page/list` | 页面树 |
| POST | `/ui/page/insert` / `update` / `delete` | 页面 CRUD |
| GET | `/ui/element/list` | 元素列表（按 page_id） |
| POST | `/ui/element/insert` / `update` / `delete` | 元素 CRUD |
| POST | `/ui/element/status` | 元素启用 / 停用 |
| GET | `/ui/case/list` | UI 用例列表 |
| POST | `/ui/case/insert` / `update` / `delete` | UI 用例 CRUD |
| POST | `/ui/case/run` | 单条执行（调试） |
| POST | `/ui/record/import` | **本地录制脚本导入** |
| GET | `/ui/node/list` | 执行节点列表 |
| POST | `/ui/node/heartbeat` | 节点心跳（v1 内置节点自注册） |
| GET | `/ui/domain/list` | 允许域名白名单（查询，`Permission()`） |
| POST | `/ui/domain/insert` / `delete` | 白名单增删（**`Permission(role=Config.ADMIN)`**） |

> 完整请求/响应结构见 [`specs/002-ui-automation/contracts/api.md`](../../specs/002-ui-automation/contracts/api.md)。

**两个执行入口的关系**（不是两套实现）：

```
批量执行（测试计划 / 用例列表多选）
  → POST /testcase/run（既有入口，不改）
    → Executor.run_single 按 request_type == 4 分派
      → UI 执行器  ←── 与下面同一条路径

单条调试（用例编辑器「调试」按钮）
  → POST /ui/case/run
    → UI 执行器  ←── 同一份执行器
```

两者最终调同一个执行器、产生同一种结果（都写 `pity_test_result`）。`/ui/case/run` 只是把"指定一条用例"包装成独立端点，避免前端为一次调试去拼既有入口的参数。

**执行的响应结构**里，每个步骤除动作与耗时外，还要回传**该目标实际使用的定位策略与定位值**（`strategy` / `locator` / `name_attr`）—— 这是"元素定位失效时必须指明是哪个元素、按哪种策略失效"的落点：只给元素名不够，同一个元素可能换过定位策略，排查时需要知道**当时用的哪一条**。

---

## 8. 部署影响

### 8.1 Python 依赖

```
playwright>=1.4x          # pip 包
# 浏览器二进制:
playwright install --with-deps chromium
```

### 8.2 镜像

`backend/ops/dockerfile`（`python:3.10-slim`）需要加浏览器 → **镜像 +~600MB**。

用 build arg 控制，不跑 UI 的部署保持镜像轻量：

```dockerfile
ARG INSTALL_PLAYWRIGHT=0
RUN if [ "$INSTALL_PLAYWRIGHT" = "1" ]; then \
      /pity/venv/bin/playwright install --with-deps chromium ; \
    fi
```

`playwright install --with-deps` 需要 root 装系统库（libnss3 / libatk / libgbm 等），**只能在 builder stage 装**，最终 stage 拷贝 venv 即可。

> **这是本模块引入的最大运维成本变化**，需要在 `backend/CLAUDE.md` 与 `README` 记一笔。

### 8.3 运行时

`gunicorn -w 2`（`backend/ops/supervisor.conf`）每个 worker 各起一个 Browser → 内存 600MB+。信号量默认并发 2 是**每进程**的，实际全局并发上限是 4。

---

## 9. 前端结构

```
frontend/src/pages/UiTest/
├── CaseManage/
│   ├── index.tsx        用例列表(分组树 + 表格: 编号/名称/所属模块/优先级/类型/状态)
│   └── CaseEditor.tsx   UI 用例编辑(步骤编排 + 元素引用 + 调试)
├── Element/
│   ├── index.tsx        元素库(页面树 + 元素表 + 新建元素弹窗)
│   └── ElementModal.tsx 定位策略下拉(8 种)
├── Record/
│   └── index.tsx        录制导入(粘贴脚本 → 解析预览 → 采纳)
├── Node/
│   └── index.tsx        执行节点
└── Execution/
    └── index.tsx        执行中心(正在执行/执行历史)
```

路由挂在 `/apiTest` 下（与 API 用例同一菜单树）：

```
/apiTest/ui/case     UI 用例管理
/apiTest/ui/element  元素库
/apiTest/ui/record   录制中心
/apiTest/ui/node     浏览器实例
/apiTest/ui/execute  执行中心
```

---

## 10. 回归与测试

```bash
cd backend
.venv/bin/python scripts/ui_selftest.py   # 解析器/DSL 校验/定位器, 不需要浏览器
.venv/bin/python scripts/ui_e2e.py        # 端到端, 需要后端在跑 + 本地 chromium
```

`selftest` 覆盖：
- codegen 脚本解析（sync/async、各种 locator、无法解析的行）
- 元素去重逻辑
- 步骤 DSL 校验（动作白名单、必填字段、策略枚举）
- **动作白名单的负例**：`evaluate` / `exec` / `run` / `script` 必须被拒绝，且**在加载步骤时**就拒绝
- **SSRF 拦截**：协议非 http/https、域名不在白名单、解析到 `127.0.0.1` / `10.x` / `192.168.x` / `169.254.169.254` / IPv6 私有与环回、重定向跳内网、白名单为空
- **确定性等待**：引擎不得插入隐式 sleep、退避必须固定、多元素匹配必须显式失败

`e2e` 覆盖：
- 页面/元素 CRUD（元素去重与停用）
- 录制导入 → 自动建页面/元素 → 产出「调试中」状态的用例
- UI 用例执行（对本地起一个测试页面）→ `pity_test_result` 回写
- 失败截图落 OSS
- **SSRF 拦截在真实执行期生效**
- 并发执行时浏览器上下文互相隔离
- UI 用例与接口用例混合执行时的报告统计口径一致

> 后端无 pytest 框架，沿用数据工厂的独立脚本模式。
>
> **T024（SSRF）与 T023（动作白名单负例）是最关键的两个测试** —— 它们守着本模块新引入的两个安全面。

---

## 11. 已知缺口与 v2 待办

### 11.1 既有平台缺口

1. **`pity_testcase.name` 是 `String(32)`** —— UI 用例名同样受限，AI 生成必须截断
2. **`pity_testcase_directory.name` 是 `String(18)`** —— 目录名也受限
3. **`pity_testcase` 没有"编码"列** —— 用例编号只能写入 `tag`（如 `UI-001`）
4. **`pity_environment` 没有 base_url 字段** —— 站点地址走 `pity_gconfig` 全局变量 `${ui_base_url}`
5. **前端 `tsc --noEmit`** —— 见 `frontend/CLAUDE.md`

### 11.2 本模块自身的待办

- 服务端注入录制（noVNC + CDP）
- 分布式执行节点（远程浏览器 / 配对码 / 节点调度 / 离线节点清理）
- Chrome 扩展录制通道
- 用例集 / 参数化用例（与数据工厂联动）
- trace / 视频录制（v1 默认关）
- AI 探索式生成（给定 URL 自动爬页面产出用例点）
- 元素库跨项目共享
- Appium / 移动端（`test_type` 已预埋 `mobile`）

### 11.3 安全审查

本模块引入**两个新的安全面**，落地后应跑一次 `security-review` 技能：

| 安全面 | 内容 | 边界 |
|---|---|---|
| **浏览器出网（SSRF）** | UI 用例让平台驱动浏览器访问目标站点，而地址可由用户写入 | 项目级域名白名单 + 协议白名单 + DNS 解析后私网拦截 + 重定向逐跳校验 + 子资源同样拦截 + 白名单为空即拒绝（见 §3.9） |
| **录制脚本解析** | 用户粘贴的 codegen 脚本是外部输入 | 只做**静态文本解析**，绝不 eval / exec / 在浏览器里跑；无法解析的行跳过并说明 |

另有**动作白名单**这一封闭边界：不允许 `evaluate` / `exec` / 任意脚本 —— 仓库已有两个 `exec()` 执行面，UI 用例不再开第三个。

按 `backend/CLAUDE.md` 的约定：Claude 在功能边界**主动提示**，但**不自动执行**——跑不跑、什么时候跑由用户决定。

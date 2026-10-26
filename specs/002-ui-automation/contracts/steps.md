# 契约 · 步骤 DSL

> Feature: [UI 自动化子系统](./spec.md) | Plan: [plan.md](./plan.md) | 数据模型: [data-model.md](./data-model.md)
> **本文件是 UI 步骤的前后端唯一真源。** 后端常量定义在 `backend/app/core/ui_executor.py`（`ACTIONS` / `STRATEGIES`），前端镜像在 `frontend/src/consts/uiTest.ts`，两端互相指认，**改一处必须同时改另一处**（`backend/CLAUDE.md` 已声明此要求）。
>
> **关联**：[`001-ai-workbench`](../001-ai-workbench/contracts/dsl.md) 的规则 11–14 直接引用本文件 —— **一份契约文档，两个 feature 共用**。

---

## 1. 概述

步骤 DSL 描述 UI 用例里"在浏览器上做什么"。

它同时是三样东西：
1. **存储格式** —— `pity_ui_case.steps` 里存的就是它
2. **编辑格式** —— 用例编辑器里用户看到和编辑的步骤列表
3. **执行格式** —— 执行器逐条翻译成浏览器操作

**封闭集合**：动作只有下表列出的那些。集合之外一律拒绝执行 —— 仓库已有两个 `exec()` 执行面（`app/routers/online/script.py:15`、`app/core/constructor/python_constructor.py:20`），UI 用例**不能再开第三个**。

---

## 2. 步骤结构

```json
{
  "action": "fill",
  "element": "登录页.用户名",
  "text": "admin",
  "timeout": 10
}
```

| 字段 | 类型 | 适用 | 说明 |
|---|---|---|---|
| `action` | string | 全部 | **必须**。动作名，取值见 §3 |
| `element` | string | 需定位的动作 | 元素引用键，格式 `页面名.元素名`，见 §4 |
| `by` / `value` / `name` | string | 内联定位 | `by` ∈ 8 种策略；`value` 是定位值；`name` 是 role 策略的 accessible name |
| `text` | string | `fill` / `press` | 输入文本 / 按键 |
| `url` | string | `goto` | 相对 `base_url` 的路径，或白名单内的绝对 URL |
| `value` | string | 断言 / `select` | 期望值 / 选项值 |
| `state` | string | `wait_for` | `visible` / `hidden` / `attached` / `detached` |
| `timeout` | int | 全部 | 覆盖用例级超时（秒） |

**规则**：
- `action` 必填，且必须属于 §3 的封闭集合
- 需定位的动作（`click` / `fill` / `hover` / `check` / …）MUST 提供 `element`，或提供完整的内联定位（`by` + `value`）
- **不允许多余字段** —— 未知字段一律丢弃并告警（与 001 的 DSL 校验策略一致）

---

## 3. 动作白名单（封闭集合）

### 3.1 导航

| 动作 | 参数 | 说明 |
|---|---|---|
| `goto` | `url` | 导航到 URL。`url` 为相对路径时拼到 `base_url`；为绝对 URL 时必须落在允许域名白名单内 |
| `back` | — | 后退 |
| `reload` | — | 刷新 |

### 3.2 交互

| 动作 | 参数 | 说明 |
|---|---|---|
| `click` | 目标 | 单击 |
| `dblclick` | 目标 | 双击 |
| `fill` | 目标 + `text` | 填入文本（会先清空） |
| `clear` | 目标 | 清空输入框 |
| `press` | 目标 + `text` | 按键（`text` 存键名，如 `Enter`） |
| `select` | 目标 + `value` | 下拉选值 |
| `check` / `uncheck` | 目标 | 勾选 / 取消勾选 |
| `hover` | 目标 | 悬停 |
| `upload` | 目标 + `files` | 上传文件 |
| `drag` | 目标 + `value` | 拖拽（`value` 为目标选择器） |

### 3.3 等待

| 动作 | 参数 | 说明 |
|---|---|---|
| `wait_for` | 目标 + `state` | 条件等待。**默认且首选** |
| `wait_timeout` | `timeout`（毫秒） | 固定等待。**必须显式配置**，引擎不插入任何隐式 sleep |

### 3.4 断言

| 动作 | 参数 | 说明 |
|---|---|---|
| `expect_text` | 目标 + `value` | 元素文本等于 / 包含 `value` |
| `expect_visible` | 目标 | 元素可见 |
| `expect_hidden` | 目标 | 元素不可见 |
| `expect_url` | `value` | 当前 URL 匹配 |
| `expect_count` | 目标 + `value` | 匹配元素数量等于 `value` |
| `expect_value` | 目标 + `value` | 输入框的值等于 `value` |
| `expect_enabled` | 目标 | 元素可用 |

### 3.5 辅助

| 动作 | 参数 | 说明 |
|---|---|---|
| `screenshot` | `value`（可选文件名） | 主动截图 |
| `scroll` | 目标（可选） | 滚动到元素 / 页面底部 |
| `set_viewport` | `value` | 运行中改视口，格式 `宽x高` |

### 3.6 明确禁止

| 禁止 | 理由 |
|---|---|
| `evaluate` | 任意 JS 执行 —— 新的代码执行面 |
| `exec` / `run` / `script` | 同上 |
| 任何"执行一段代码"的动作 | 同上 |

> 引擎在加载步骤时就会拒绝这些动作，**不是执行时才拦**。

---

## 4. 定位与元素引用

### 4.1 优先引用元素

步骤的目标用 `element` 表达：**`页面名.元素名`**。

```
{"action": "click", "element": "登录页.登录按钮"}
```

解析规则：在**当前项目**下，找到名称为 `登录页` 的页面 → 该页面下名称为 `登录按钮` 且 `status = 1`（启用）的元素。

- 找不到页面 → 元素引用无效
- 找不到元素 → 元素引用无效
- 元素存在但**已停用** → 元素引用无效（与"不存在"同等处理）

**元素引用无效时的行为**：
1. **生成 / 导入阶段** → 该步骤被丢弃并产生告警
2. **保存 / 采纳阶段** → 该用例被拦下，不入库
3. **执行阶段**（历史用例引用了后来被停用的元素）→ 该步骤判失败，报"引用的元素『X.Y』已停用或不存在"，用例判失败

### 4.2 内联定位（兜底）

```
{"action": "click", "by": "css", "value": "#login-btn"}
{"action": "click", "by": "role", "value": "button", "name": "登录"}
```

**允许但不推荐**。编辑器在检测到全内联的用例时提示"建议把该定位纳入元素库"（spec FR-010）。

**内联定位同样受 SSRF 边界约束**（绝对 URL、`file:` 等协议）。

### 4.3 定位策略（8 种）

| 策略 | `by` | Playwright 对应 | 额外字段 |
|---|---|---|---|
| CSS | `css` | `page.locator(css)` | — |
| XPath | `xpath` | `page.locator(xpath)` | — |
| ID | `id` | `page.locator("#id")` | — |
| 文本 | `text` | `page.get_by_text()` | — |
| Role | `role` | `page.get_by_role(role)` | `name`（accessible name） |
| 占位符 | `placeholder` | `page.get_by_placeholder()` | — |
| Label | `label` | `page.get_by_label()` | — | 
| testid | `testid` | `page.get_by_test_id()` | — |

**策略选择建议**（编辑器提示文案）：语义定位（role / label / text / placeholder / testid）比 CSS/XPath 更抗改版，**优先用语义定位**。

### 4.4 匹配到多个元素

**显式失败**，不静默取第一个：

> "定位到 3 个匹配元素，请用更精确的定位策略，或在元素定义中指定索引"

理由见 `research.md` §4.2 —— 静默取第一个就是不确定性，违反 constitution 原则 I。

---

## 5. 断言

### 5.1 断言的表达

断言写在步骤里（`expect_*` 动作），执行时**汇总成标准断言结构**，写入 `pity_test_result.asserts`（与接口用例同结构，spec FR-034 口径一致）。

```json
{
  "assertions": [
    {"name": "步骤 4 错误提示", "assert_type": "equal", "expected": "用户名或密码错误", "actually": "用户名或密码错误", "status": true}
  ]
}
```

### 5.2 断言类型映射

UI 断言映射到既有的 `assert_type` 语义（`Executor.ops` 已支持）：

| UI 动作 | 映射 | 说明 |
|---|---|---|
| `expect_text` | `equal` | 文本相等（必要时先 trim） |
| `expect_visible` / `expect_hidden` | `equal`（`true` / `false`） | 可见性 |
| `expect_url` | `equal` | URL 相等 |
| `expect_count` | `length_eq` | 数量相等 |
| `expect_value` | `equal` | 输入值相等 |
| `expect_enabled` | `equal`（`true`） | 可用 |

> `pity_testcase_asserts` 表本身**不新增行** —— UI 用例的断言是步骤内的，汇总后只落在执行记录里。理由见 `research.md` §3.10：报告页与统计口径复用既有逻辑，不做第二套。

---

## 6. 等待策略（确定性）

> constitution 原则 I：MUST 满足"同样的输入 MUST 产出完全一致的结果"。以下是引擎的硬约束。

| 规则 | 说明 |
|---|---|
| **条件等待优先** | `wait_for` 等选择器达到目标状态（可见 / 可交互 / 附加 / 分离），**引擎不插入任何隐式 sleep** |
| **固定等待必须显式** | `wait_timeout` 的毫秒数写进步骤定义，**不是默认值** |
| **禁止随机退避** | 重试的退避间隔必须固定（如固定 1s）。**禁止**随机退避、随机抖动 |
| **禁止随机选择** | 定位到多个元素时显式失败，不随机挑一个 |
| **禁止隐式随机值** | 需要随机数据时用平台既有的 `${random_int(a,b)}` 全局函数（`PityFunction`），不走浏览器侧随机 |
| **超时是显式的** | 单步超时由步骤或用例显式配置，超时判失败并保留现场 |

**这些是"平台自己引入的随机源"的清单 —— 全部禁止。** 被测系统自身的不确定性不在此约束范围（见 §7）。

---

## 7. 确定性声明

> constitution 原则 I 要求："若确实无法重放，MUST 在代码注释与设计文档中显式标注该字段不可重放"。

**UI 用例的执行结果不可重放。**

| 范围 | 是否可重放 | 说明 |
|---|---|---|
| **步骤定义**（本 DSL） | ✅ 完全确定 | 同一份 steps 永远产生同一串浏览器操作序列 |
| **平台自身的行为** | ✅ 确定 | 无隐式 sleep、无随机退避、无随机选择（见 §6） |
| **执行结果**（页面内容、断言成败） | ❌ **不可重放** | 取决于被测系统当时的状态，**不在平台可控范围** |

**实现约束**：
- 引擎 MUST NOT 引入任何 §6 清单里的随机源
- 重试策略的次数与退避 MUST 固定，且写进实现而非运行时决定
- **代码注释与 Model docstring 中必须出现此声明**

> 这与 `001-ai-workbench` 的"模型输出不可重放"是同一类问题的两种形态：平台能保证的是**输入到动作的映射是确定的**，不能保证的是**外部世界不变**。

---

## 8. 前后端同步点

| 常量 | 后端 | 前端 | 同步要求 |
|---|---|---|---|
| 动作白名单 `ACTIONS` | `app/core/ui_executor.py` | `src/consts/uiTest.ts` | **改一处必须同时改另一处** |
| 定位策略 `STRATEGIES` | `app/core/ui_executor.py` | `src/consts/uiTest.ts` | 同上 |
| 断言类型映射 | `app/core/ui_executor.py` | `src/consts/uiTest.ts` | 同上 |

**与 `001-ai-workbench` 的关系**：
- 001 的 `contracts/dsl.md` 规则 11（动作在集合内）、12（定位完整）、13（元素存在且启用）、14（结构完整）**引用本文件**
- 001 负责"AI 生成时怎么校验"，本文件负责"动作与定位的语义是什么"
- 两边的动作集 MUST 一致 —— 由 `/speckit-analyze` 跨 feature 核对

**校验职责分工**：后端是最终裁决者（不合规的步骤被丢弃）；前端的步骤编辑器 MUST 用同一份常量做**提前提示**，但不得在前端做最终判定 —— 前端放行、后端丢弃会导致用户"改了还是被丢弃"的困惑。

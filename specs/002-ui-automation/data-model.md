# Phase 1 · 数据模型

> Feature: [UI 自动化子系统](./spec.md) | Plan: [plan.md](./plan.md) | Research: [research.md](./research.md)
> 契约：[contracts/steps.md](./contracts/steps.md)（步骤 DSL，前后端唯一契约）· [contracts/api.md](./contracts/api.md)

---

## 1. 实体总览

```
  ┌──────────────────────┐ 1:N    ┌──────────────────────┐
  │   pity_ui_page       │───────▶│   pity_ui_element    │
  │   页面树              │        │   元素 = 一条定位策略 │
  │   (project_id, parent)│        │   (page_id, strategy)│
  └──────────────────────┘        └──────────┬───────────┘
                                              │ element 引用 "页面名.元素名"
                                              ▼
  ┌──────────────────────┐ 1:1    ┌──────────────────────┐
  │   pity_testcase      │───────▶│   pity_ui_case       │
  │   用例主体            │        │   (case_id, steps)   │
  │   request_type = 4   │        └──────────────────────┘
  └──────────┬───────────┘
             │ 执行结果写入
             ▼
  ┌──────────────────────┐        ┌──────────────────────┐
  │  pity_test_result    │        │   pity_ui_node       │
  │  （既有表，不改结构）  │        │   执行节点            │
  └──────────────────────┘        └──────────────────────┘

  辅助：
  ┌──────────────────────┐        ┌──────────────────────────┐
  │ pity_ui_import_log   │        │ pity_ui_allowed_domain   │
  │ 录制导入记录          │        │ SSRF 白名单（按项目）      │
  └──────────────────────┘        └──────────────────────────┘
```

**六张表的职责边界**：

| 表 | 回答什么问题 | 生命周期 |
|---|---|---|
| `pity_ui_page` | 被测界面长什么样、分几层 | 长期资产 |
| `pity_ui_element` | 某个元素怎么找 | 长期资产，**页面改版时改这里** |
| `pity_ui_case` | 这个 UI 流程怎么走 | 长期资产（主体在既有的 `pity_testcase`） |
| `pity_ui_node` | 在哪跑 | 运行时资源 |
| `pity_ui_import_log` | 这次录制导入产出了什么 | 留痕 |
| `pity_ui_allowed_domain` | 允许访问哪些站点 | **安全边界**，配错 = 放行内网 |

> **为什么 `pity_ui_allowed_domain` 独立成表而不是加字段到 `pity_project`**：既有表加列要迁移、影响存量部署；白名单是"一行一个域名"的列表结构，放进 `description` 这类文本字段既不可查也不可管。

---

## 2. 表定义

所有表继承 `PityBase`（`app/models/basic.py`），自动具备 `id`、`created_at`、`updated_at`、`deleted_at`（软删）、`create_user`、`update_user`。

### 2.1 `pity_ui_page` — 页面树

`backend/app/models/ui_case.py`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `project_id` | INT | index not null | 所属项目 → `pity_project.id` |
| `name` | String(64) | not null | 页面名。**元素引用的键就是它** |
| `url` | String(256) | — | 页面地址 |
| `parent` | INT | — | 上级页面 id，构成树；顶级为 `None` |
| `description` | String(255) | — | 描述 |

**唯一约束**：`UniqueConstraint('project_id', 'name', 'parent', 'deleted_at')` —— 同项目同层级下页面名不重复

**校验规则**：
- `project_id` 必须指向存在的项目
- `parent` 必须指向**同项目内**存在的页面（跨项目挂载拒绝）
- `parent` 不得构成环（保存时向上回溯检查）

### 2.2 `pity_ui_element` — 元素 = 一条定位策略

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `project_id` | INT | index not null | 所属项目 |
| `page_id` | INT | index not null | 所属页面 → `pity_ui_page.id` |
| `name` | String(64) | not null | 元素名。**引用键 `页面名.元素名` 的后半段** |
| `strategy` | String(16) | not null | 定位策略，见 §3.2 |
| `locator` | String(256) | not null | 定位值 |
| `name_attr` | String(64) | — | `strategy = role` 时的 accessible name |
| `description` | String(255) | — | 描述 |
| `status` | INT | default 1 | 1 启用 / 0 停用 |

**唯一约束**：`UniqueConstraint('project_id', 'page_id', 'strategy', 'locator', 'name_attr', 'deleted_at')`
—— 这就是去重规则（research §3.7）：同页面同策略同定位值同 name_attr 即视为同一元素

**校验规则**：
- `page_id` 必须指向**同项目内**存在的页面
- `strategy` ∈ 8 种定位策略
- `strategy = role` 时 `name_attr` 可空（按 role 唯一定位），其余策略下 `name_attr` 必须为空
- `locator` 非空

**停用语义**（spec FR-005 / Edge Case）：停用**不删除**。引用它的用例仍可存在，但执行时该步骤判失败并说明"引用的元素已停用"；草稿采纳时引用停用元素会被拦下（规则 13）。

### 2.3 `pity_ui_case` — UI 用例专有数据

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `case_id` | INT | index not null | 关联 `pity_testcase.id` |
| `base_url` | String(256) | not null | 起始地址。支持 `${变量}` |
| `viewport` | String(16) | default `'1280x720'` | 视口 |
| `browser` | String(16) | default `'chromium'` | 浏览器类型 |
| `timeout` | INT | default 30 | 单步超时（秒） |
| `steps` | TEXT | not null | **步骤 DSL JSON**（见 `contracts/steps.md`） |
| `screenshot` | BOOLEAN | default True | 失败自动截图 |

**唯一约束**：`UniqueConstraint('case_id', 'deleted_at')`

**校验规则**：
- `case_id` 必须指向 `request_type = 4` 的 `pity_testcase`
- `base_url` MUST 落在该项目的允许域名白名单内（§7）
- `steps` 必须是合法 JSON，且每个步骤的 `action` ∈ 封闭动作集合
- `viewport` 形如 `1280x720`

### 2.4 `pity_ui_node` — 执行节点

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | String(64) | 节点名 |
| `node_type` | String(16) | `local`（内置）/ `remote`（v2 预留） |
| `status` | INT | 1 在线 / 0 离线 |
| `browser` | String(16) | `chromium` |
| `headless` | BOOLEAN | 无头模式 |
| `max_concurrency` | INT | 并发上限，默认 2 |
| `version` | String(32) | 节点版本标识 |

**v1 的用法**：平台启动时注册一个 `local` 节点。**分布式节点是 v2**，但表与接口形状先定好（research §3.12）。

### 2.5 `pity_ui_import_log` — 录制导入记录

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | INT index | 项目 |
| `source` | String(16) | `codegen`（v1 唯一通道）/ `manual`（预留） |
| `raw_len` | INT | 原始脚本长度 |
| `parsed_lines` / `skipped_lines` | INT | 解析成功与跳过的行数 |
| `page_count` / `element_count` / `case_count` | INT | 产出的页面/元素/用例数 |
| `batch_id` | INT | 关联的生成批次（若走 001 的草稿机制） |
| `status` | INT | 1 成功 / 2 部分成功（有跳过行）/ 3 失败 |
| `message` | TEXT | 说明（尤其"哪些行没解析出来"） |

### 2.6 `pity_ui_allowed_domain` — SSRF 白名单

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `project_id` | INT | index not null | 项目 |
| `domain` | String(128) | not null | 允许的域名（如 `example.com`；**不含协议与路径**） |
| `env` | INT | — | 生效环境；`None` 表示所有环境 |

**唯一约束**：`UniqueConstraint('project_id', 'domain', 'env', 'deleted_at')`

**校验规则**：
- `domain` MUST 是**裸域名**（不含 `http://`、不含 `/`、不含端口）—— 避免用"看起来像域名其实带路径"的串绕过匹配
- `project_id` 必须指向存在的项目

> **语义**：白名单为空 → 该项目的 UI 用例**不可执行**（不是"允许全部"）。这是刻意选的失败方向 —— 宁可跑不了，也不能让平台裸奔到内网。

---

## 3. 跨端契约与常量

### 3.1 唯一契约文档

[contracts/steps.md](./contracts/steps.md) 是步骤 DSL 的**唯一真源**。两端常量互相指认：

| 常量 | 后端权威定义 | 前端镜像 | 指认方式 |
|---|---|---|---|
| 动作白名单（`ACTIONS`） | `backend/app/core/ui_executor.py` | `frontend/src/consts/uiTest.ts` | 前端文件头注释指认后端路径；`backend/CLAUDE.md` 声明"必须同步修改两处" |
| 定位策略（`STRATEGIES`） | 同上 | 同上 | 同上 |

> `001-ai-workbench` 的 `contracts/dsl.md` 规则 11–14 **引用本文件的 `contracts/steps.md`** —— 一份契约文档，两个 feature 共用，避免出现两份会漂移的动作集定义。

### 3.2 定位策略枚举（8 种）

| 策略 | 含义 | Playwright 对应 | `name_attr` |
|---|---|---|---|
| `css` | CSS 选择器 | `page.locator(css)` | — |
| `xpath` | XPath | `page.locator(xpath)` | — |
| `id` | 元素 id | `page.locator("#id")` | — |
| `text` | 文本内容 | `page.get_by_text()` | — |
| `role` | ARIA role | `page.get_by_role(role)` | ✅ accessible name |
| `placeholder` | 占位符 | `page.get_by_placeholder()` | — |
| `label` | 表单 label | `page.get_by_label()` | — |
| `testid` | data-testid | `page.get_by_test_id()` | — |

> 前 7 种与参考产品的定位策略下拉一致，`testid` 是补的（Playwright 推荐做法，录制器容易产出）。

### 3.3 与既有表的字段对齐

| UI 侧 | 目标表.字段 | 约束来源 |
|---|---|---|
| `pity_testcase.name` | 用例名 | `String(32)` → **超长必须截断并告警** |
| `pity_testcase.url` | `base_url` | `TEXT nullable=False` |
| `pity_testcase.request_type` | — | 恒为 `4`（web_ui） |
| `pity_testcase.priority` | P0–P4 | 与 `frontend/src/consts/config.ts` 一致 |
| `pity_testcase.status` | — | 默认 `1`（调试中），与 001 的策略一致 |
| `pity_testcase.directory_id` | — | 取用户所选目录 |
| `pity_ui_case.steps` | 步骤 DSL | 见 `contracts/steps.md` |

---

## 4. 状态流转与确定性

### 4.1 不可重放的事实

**UI 用例的执行结果不可重放。** 同样的步骤、同样的被测系统，隔一段时间再跑，页面内容可能已经变了 —— 这与 constitution 原则 I 的"同样的输入 MUST 产出完全一致的结果"存在天然张力。

**本功能的处理**（划清边界，与 AI 输出不可重放同类处理）：

| 范围 | 是否可重放 | 说明 |
|---|---|---|
| **步骤定义**（`steps` DSL） | ✅ **完全确定** | 同一份 steps 永远产生同一串浏览器操作序列 |
| **平台自身的行为** | ✅ 确定 | 无隐式 sleep、无随机退避、无随机选择器；等待一律条件等待 |
| **执行结果**（页面内容、断言成败） | ❌ **不可重放** | 取决于被测系统当时的状态，**不在平台可控范围** |

> **MUST 显式标注的位置**：
> - `pity_ui_case` 的 Model 类 docstring
> - `contracts/steps.md` §7
> - `backend/docs/ui-automation-design.md`
>
> 理由与 constitution 原则 I 的要求一致："若确实无法重放，MUST 在代码注释与设计文档中显式标注"。

### 4.2 平台 MUST NOT 引入的随机源

| 禁止 | 替代 |
|---|---|
| 隐式 `sleep` 缓冲 | 条件等待（等选择器可见/可交互） |
| 随机退避重试 | 固定退避（如固定 1s），且重试次数写死在步骤定义里 |
| 随机挑选匹配的元素 | 用定位策略 + `match_index` 显式指定（`first` / `last` / 序号） |
| `Math.random()` 类的隐式行为 | 步骤里需要随机值时，用平台既有的 `${random_int(a,b)}` 全局函数（`PityFunction`），由用例的 `seed` 语义承担 |

> 定位到多个元素时的处理：**显式报失败**（"定位到 3 个元素，请用更精确的定位策略或指定索引"），**不静默取第一个** —— 静默取第一个就是不确定性。

### 4.3 状态流转

```
  页面 (pity_ui_page)                    元素 (pity_ui_element)
       │ 新建/编辑/删除                          │ 新建/编辑
       ▼                                       ▼
    status = 1 启用 ──────── 停用 ──────▶ status = 0 停用
       │                                       │
       │ 引用                                 │ 被步骤引用
       ▼                                       ▼
  pity_ui_case.steps  ──── 采纳/保存 ────▶ 步骤可执行
       │
       │ 执行
       ▼
  pity_test_result（status 0/1/2）
       │
       ▼
  失败时 → 截图 → OSS → URL 写入 case_log
```

**元素停用后的行为**：
- 已有用例**保留**（不级联删除），执行时该步骤判失败并说明"引用的元素已停用"
- 新建/编辑用例时选到停用元素 → 前端提示，采纳时被拦下
- 元素重新启用 → 用例自动恢复可用

---

## 5. 就地指引点（constitution 原则 IV）

| 编号 | 前置条件缺失 | 界面就地指引 | 降级行为 |
|---|---|---|---|
| **U1** | 未配置允许域名（SSRF 白名单） | 用例编辑页与执行按钮旁提示「本项目尚未配置允许访问的域名，去配置」+ 跳转配置入口 | **不可执行**（不是"允许全部"） |
| **U2** | `${ui_base_url}` 全局变量未配 | 用例编辑器的 base_url 字段旁提示「站点地址未配置，可在环境全局变量里配 `ui_base_url`」+ 跳转全局变量页 | 不阻断编辑，只阻断执行 |
| **U3** | 项目下无目录 | 目录选择器旁提供「新建目录」入口 | 无目录则不提交 |
| **U4** | 元素库为空 | 用例编辑器的元素选择处提示「元素库为空，先沉淀页面与元素」+ 跳转元素库 | 允许写步骤，但保存时提示元素缺失 |
| **U5** | 录制导入页未粘贴脚本 | 导入区提示「粘贴录制脚本，或改用手工新建用例」+ 跳转手工新建 | 不可提交 |
| **U6** | 无可用的执行节点 | 执行按钮旁提示「没有可用的执行节点」+ 跳转节点页 | 不可执行 |

> **U1 与 U3 的区别**：U1 是**安全边界缺失**（必须阻断），U3 是**路径缺失**（可引导补齐）。两者都必须给指引，不能只报错误码。

---

## 6. 结果回写映射

UI 用例结果写入**既有的 `pity_test_result`**（`app/models/result.py`），**不改该表结构**：

| 字段 | UI 用例的填法 |
|---|---|
| `status` | 0 成功 / 1 失败 / 2 出错 |
| `case_log` | 逐步骤执行日志：每步 `action` + 目标元素 + 耗时 + 结果（复用 `CaseLog` 格式） |
| `response` | 失败时存错误栈；成功时存最后页面 HTML 摘要 |
| `asserts` | UI 内联断言汇总成的标准断言 JSON（与 API 用例同结构，spec FR-026 口径一致） |
| `status_code` | 留空 |
| `url` | 实际访问的 URL |
| `cost` | 总耗时（秒） |
| `request_method` | 留空（无 HTTP 方法语义） |
| `request_headers` / `body` | 留空（可考虑存步骤摘要，便于在报告里一眼看出做了什么） |

---

## 7. SSRF 防护配置与拦截清单

对应 research §3.8、plan.md 的 GATE-SEC 专门说明。

### 7.1 允许域名的配置位置

`pity_ui_allowed_domain`（按项目 + 可选环境）。**为空 = 该项目不允许访问任何站点**。

### 7.2 拦截清单（实现时逐条落实）

| # | 检查点 | 规则 |
|---|---|---|
| 1 | `base_url` 解析 | 必须是 `http` / `https`；其他协议（`file:` / `ftp:` / `data:` / `javascript:`）直接拒绝 |
| 2 | 域名匹配 | 主机名必须在该项目白名单内（精确匹配或子域匹配 `*.example.com`），否则拒绝 |
| 3 | 主机地址拦截 | 域名解析后的**所有** IP 逐一检查：私有网段（10/8、172.16/12、192.168/16）、环回（127/8）、链路本地（169.254/16）、IPv6 私有与环回、保留地址 → 拒绝 |
| 4 | 重定向 | 跟随每一跳时**重新执行 1–3**；任一跳不合规则中止并报失败 |
| 5 | 子资源 | 页面内的静态资源请求同样受 1–3 约束（由浏览器层的请求拦截实现） |
| 6 | 步骤内 URL | 相对路径 → 拼到 `base_url` 后再过 1–3；绝对 URL → 直接过 1–3 |

> **第 3 条为什么要解析后再查**：域名可能指向内网地址（DNS 指向 `127.0.0.1`、云厂商的 `169.254.169.254`）。只查字符串会漏。
>
> **第 5 条为什么重要**：只拦顶层导航，页面里的 `<img src="http://169.254.169.254/...">` 仍会被浏览器请求。必须在浏览器请求层拦截，而不是只在用例层校验。

---

## 8. 与既有表的关系

| 新表 | 既有表 | 关系 |
|---|---|---|
| `pity_ui_page.project_id` | `pity_project` | 多对一 |
| `pity_ui_element.page_id` | `pity_ui_page` | 多对一；页面与元素 MUST 同项目 |
| `pity_ui_case.case_id` | `pity_testcase` | 一对一；被引用用例 MUST `request_type = 4` |
| `pity_ui_import_log.batch_id` | `pity_ai_draft_batch`（001） | 多对一，可空（不走草稿机制时） |
| `pity_ui_allowed_domain.project_id` | `pity_project` | 多对一 |

**软删除语义**：六张表全部继承 `PityBase` 的 `deleted_at` 软删。删除页面时**不级联删除元素**（元素可能仍被其他页面引用或已写进用例步骤），元素转为停用并提示用户处理引用。

---

## 9. 迁移

沿用仓库既有做法：启动时 `Base.metadata.create_all` 自动建表。

**唯一涉及既有代码的改动**是 `pity_testcase.request_type` 的**取值域扩展**（新增 `4`）。该字段本就 `INT default 1`，**无需改列结构**，只是取值变大。既有数据不受影响，既有查询逻辑也不受影响（该字段在后端只存不判）。

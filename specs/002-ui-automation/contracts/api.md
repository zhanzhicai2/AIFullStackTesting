# 契约 · HTTP 接口

> Feature: [UI 自动化子系统](./spec.md) | Plan: [plan.md](./plan.md) | 步骤 DSL: [steps.md](./steps.md)
> 前缀 `/ui`，全部走 `PityResponse` 的 `{code, data, msg}`。

---

## 1. 通用约定

### 1.1 响应信封

```json
{ "code": 0, "data": {}, "msg": "操作成功" }
```

| code | 含义 |
|---|---|
| `0` | 成功 |
| `101` | 参数错误 |
| `110` | 业务异常 |
| `401` | 未登录 |
| `403` | 无权限 |

> HTTP 状态码恒为 `200`，业务码在 body 里。

### 1.2 鉴权

| 接口 | 权限 |
|---|---|
| 页面 / 元素 / 用例 CRUD、执行 | `Permission()` —— 登录即可用 |
| **执行节点的删除** | `Permission(role=Config.ADMIN)` —— 节点是平台级资源 |
| **允许域名白名单的增删** | `Permission(role=Config.ADMIN)` —— **这是安全边界，配错等于放行内网** |

> **白名单为什么收紧到 ADMIN**：它直接决定平台能访问哪些外部地址。放宽它 = 放宽 SSRF 边界。按 constitution 安全要求"新增写入通道时，MUST 通过 `Permission(role=...)` 收紧角色"。
>
> **页面 / 元素为什么保持 `Permission()`**（constitution 要求对新增写入通道显式回应）：元素库是**团队协作资产** —— 它的价值恰恰在于"测试人员自己沉淀元素"，收紧到 ADMIN 会让协作资产退化成管理员专属。而"创建用例"在既有平台本就是 `Permission()`，UI 用例的写入权限与之同级，**不扩大权限面**。真正需要收紧的是白名单（安全边界），已收紧到 ADMIN。
>
> **留出的口子**：若将来元素库要跨项目共享（v2 待办），届时应把元素写入收紧到项目成员角色，而不是继续沿用 `Permission()`。这一点在 v2 落地时必须重新评估。

### 1.3 复用既有接口（不自建）

| 需求 | 复用 | 说明 |
|---|---|---|
| **批量执行 UI 用例** | `POST /testcase/run`（既有） | **不改既有执行入口** —— UI 用例是 `pity_testcase` 的一种，`Executor.run_single` 按 `request_type` 分派 |
| **单条执行（调试）** | `POST /ui/case/run`（本契约 §3.2） | 便捷封装，供用例编辑器的「调试」按钮使用 |
| 测试报告 | `GET /testcase/report/:id` + `/record/report/:id`（既有） | 报告页只扩"附件"tab |
| 历史执行记录 | `GET /testcase/report/list`（既有） | 执行中心复用它 |
| 目录树 | `GET /testcase/directory`（既有） | UI 用例与接口用例共用 |
| 文件上传 | `POST /oss/upload`（既有） | 录制备选文件、日志等 |
| 全局变量 | 既有 `pity_gconfig` 管理页 | 站点地址配成 `${ui_base_url}` |

> **两个执行入口的关系**（F3 澄清）：
> ```
> 批量执行（测试计划 / 用例列表多选）
>   → POST /testcase/run（既有入口）
>     → Executor.run_single 按 request_type == 4 分派
>       → UI 执行器  ←── 与下面同一条路径
>
> 单条调试（用例编辑器「调试」按钮）
>   → POST /ui/case/run（本契约 §3.2）
>     → UI 执行器  ←── 同一份执行器
> ```
> **两者最终调同一个执行器、产生同一种结果**（都写 `pity_test_result`）。`/ui/case/run` 不是第二套实现，只是把"指定一条用例"这件事包装成独立端点，避免前端为了调一次调试去拼既有入口的参数。

---

## 2. 页面与元素库

### 2.1 页面树

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ui/page/list` | 页面树（按 project_id） |
| POST | `/ui/page/insert` | 新建页面 |
| POST | `/ui/page/update` | 修改页面 |
| GET | `/ui/page/delete` | 删除页面（软删；**不级联删元素**，元素转停用） |

**`POST /ui/page/insert` 请求**：

```json
{ "project_id": 1, "name": "登录页", "url": "https://example.com/login", "parent": null, "description": "" }
```

**`GET /ui/page/list` 响应**：

```json
{
  "code": 0,
  "data": [{
    "id": 10, "project_id": 1, "name": "登录页", "url": "https://example.com/login",
    "parent": null, "description": "", "element_count": 3,
    "children": [{"id": 11, "name": "登录页-错误态", "parent": 10, "element_count": 1, "children": []}]
  }],
  "msg": "操作成功"
}
```

### 2.2 元素库

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ui/element/list` | 元素列表（按 page_id 或 project_id） |
| POST | `/ui/element/insert` | 新建元素 |
| POST | `/ui/element/update` | 修改元素 |
| GET | `/ui/element/delete` | 删除元素（软删） |
| POST | `/ui/element/status` | 启用 / 停用 |

**`POST /ui/element/insert` 请求**：

```json
{
  "project_id": 1,
  "page_id": 10,
  "name": "登录按钮",
  "strategy": "role",
  "locator": "button",
  "name_attr": "登录",
  "description": "登录表单的提交按钮"
}
```

**校验**：
- `strategy` ∈ 8 种定位策略（见 `steps.md` §4.3）
- `strategy = role` 时 `name_attr` 可空；其余策略下 `name_attr` 必须为空
- `page_id` 必须属于同项目
- **去重**：同 `page_id` + `strategy` + `locator` + `name_attr` 已存在 → 返回既有元素的 id，不重复创建（幂等）

**响应**：

```json
{ "code": 0, "data": { "id": 31, "duplicated": false }, "msg": "操作成功" }
```

---

## 3. UI 用例

### 3.1 用例 CRUD

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ui/case/list` | UI 用例列表（按 project_id / directory_id） |
| GET | `/ui/case/detail` | 用例详情（含步骤与解析后的元素引用） |
| POST | `/ui/case/insert` | 新建 UI 用例 |
| POST | `/ui/case/update` | 修改 UI 用例（含步骤编辑） |
| GET | `/ui/case/delete` | 删除 UI 用例（软删） |
| POST | `/ui/case/run` | 单独执行一条（调试） |

**`POST /ui/case/insert` 请求**：

```json
{
  "project_id": 1,
  "directory_id": 12,
  "name": "登录页-正常登录",
  "priority": "P0",
  "base_url": "${ui_base_url}",
  "viewport": "1280x720",
  "timeout": 30,
  "steps": [
    {"action": "goto", "url": "/login"},
    {"action": "fill", "element": "登录页.用户名", "text": "admin"},
    {"action": "click", "element": "登录页.登录按钮"},
    {"action": "expect_text", "element": "登录页.错误提示", "value": "用户名或密码错误"}
  ]
}
```

**请求字段**：

| 字段 | 必填 | 说明 |
|---|---|---|
| `project_id` | ✅ | 项目 |
| `directory_id` | ✅ | 目标目录（与接口用例共用目录树） |
| `name` | ✅ | 用例名。**≤ 32 字符**，超长按既有列长度截断并回显告警（FR-035） |
| `priority` | — | P0–P4，默认 P1 |
| `base_url` | ✅ | 起始地址。支持 `${}` 变量（FR-013）；MUST 落在允许域名白名单内 |
| `viewport` | — | 默认 `1280x720` |
| `timeout` | — | 单步超时（秒），默认 30 |
| `steps` | ✅ | 步骤数组 |

> **`status` 不在请求字段里**：新建的 UI 用例**恒为「调试中」**（`pity_testcase.status = 1`），这是本 feature 的"草稿态"（见 §3.3 与 `spec.md` FR-016）。用户核对步骤后把状态改为「正常运行」（3）即视为采纳。

**校验**（`steps.md` §2–§4）：
- `name` ≤ 32 字符（`pity_testcase.name` 是 `String(32)`）
- `base_url` MUST 落在该项目允许域名白名单内（§4）
- 每个步骤的 `action` ∈ 封闭动作集合；未知字段丢弃并告警
- 步骤引用的元素 MUST 存在且启用；无效引用的步骤被丢弃并告警

**响应**：

```json
{
  "code": 0,
  "data": {
    "case_id": 501,
    "warnings": ["步骤 3 引用的元素「登录页.注册按钮」在元素库中不存在或已停用，已丢弃该步骤"]
  },
  "msg": "创建成功"
}
```

> **警告而非拒绝**：单个步骤无效不应让整条用例建不出来（与 001 的 DSL 校验策略一致）。但**若全部步骤都无效**，则拒绝创建并回显原因。

### 3.2 执行

**`POST /ui/case/run` 请求**：

```json
{ "case_id": 501, "env": 1, "node_id": 1 }
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "result_id": 90311,
    "status": 1,
    "status_label": "失败",
    "cost": 3.42,
    "steps": [
      {"index": 1, "action": "goto", "target": "/login", "status": "ok", "cost": 0.8},
      {"index": 2, "action": "fill", "target": "登录页.用户名",
       "strategy": "label", "locator": "用户名", "status": "ok", "cost": 0.2},
      {"index": 3, "action": "click", "target": "登录页.登录按钮",
       "strategy": "role", "locator": "button", "name_attr": "登录", "status": "ok", "cost": 0.3},
      {"index": 4, "action": "expect_text", "target": "登录页.错误提示",
       "strategy": "text", "locator": "用户名或密码错误", "status": "failed",
       "cost": 30.1, "error": "断言失败：期望「用户名或密码错误」，实际「登录成功」"}
    ],
    "asserts": "[{\"name\": \"步骤 4 错误提示\", \"assert_type\": \"equal\", \"status\": false}]",
    "screenshot_url": "https://oss.example.com/pity/ui/90311/fail.png",
    "error": null
  },
  "msg": "执行完成"
}
```

**行为**：
- 结果写入**既有的 `pity_test_result`**（字段映射见 `data-model.md` §6）
- 失败时自动截图 → 上传 OSS → URL 写入 `case_log`
- 每步的动作、目标、耗时、结果都记录

**`steps[]` 的字段**：

| 字段 | 说明 |
|---|---|
| `index` | 步骤序号 |
| `action` | 动作名 |
| `target` | 步骤目标。引用元素时是 `页面名.元素名`；内联定位时是定位值 |
| `strategy` | **该目标实际使用的定位策略**（`css`/`xpath`/`id`/`text`/`role`/`placeholder`/`label`/`testid`）；无目标的动作（`goto`/`wait_timeout`）为空 |
| `locator` | 定位值 |
| `name_attr` | `role` 策略时的 accessible name |
| `status` | `ok` / `failed` / `skipped` |
| `cost` | 该步耗时（秒） |
| `error` | 失败原因文本 |

> **`strategy` / `locator` 是 FR-023 的落点**：元素定位失效时，失败信息必须能指明"是哪个元素、按哪种定位策略失效"。只给 `target`（元素名）不够 —— 同一个元素可能换过定位策略，排查时需要知道**当时用的哪一条**。

**失败原因分类**（`error` 的取值，便于前端与 Bug 分析区分）：

| 值 | 含义 |
|---|---|
| `element_not_found` | 元素引用无效（不存在或已停用） |
| `element_ambiguous` | 定位到多个元素 |
| `timeout` | 单步超时 |
| `assertion_failed` | 断言不通过 |
| `navigation_blocked` | 目标地址被 SSRF 策略拒绝 |
| `browser_error` | 浏览器异常 |

---

## 4. 允许域名白名单（SSRF 边界）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/ui/domain/list` | `Permission()` | 当前项目的白名单 |
| POST | `/ui/domain/insert` | `Permission(role=Config.ADMIN)` | 新增域名 |
| POST | `/ui/domain/delete` | `Permission(role=Config.ADMIN)` | 删除域名 |

**`POST /ui/domain/insert` 请求**：

```json
{ "project_id": 1, "domain": "example.com", "env": null }
```

**校验**：
- `domain` MUST 是**裸域名** —— 不含 `http://`、不含 `/`、不含端口。含协议或路径的串一律拒绝（避免伪装绕过匹配）
- 支持 `*.example.com` 形式的子域通配

**语义**：**白名单为空 = 该项目不允许访问任何站点**（不是"允许全部"）。

**执行期拦截**（在用例执行时生效，规则见 `data-model.md` §7.2）：

| 情况 | 响应 |
|---|---|
| `base_url` 的域名不在白名单 | `code 110`，msg 说明"目标域名不在本项目允许列表内" |
| 协议不是 http/https | `code 110`，msg 说明协议不被允许 |
| 域名解析到私有网段 / 环回 / 链路本地 / 保留地址 | `code 110`，msg 说明地址被安全策略拒绝 |
| 重定向跳到不合规地址 | 该跳被拦截，用例判失败，`error = navigation_blocked` |
| 页面子资源请求不合规地址 | 该请求被浏览器层拦截 |

> **为什么这是 `/ui` 自己的接口而不是全局配置**：允许域名是**项目级**的安全边界 —— 一个项目测 `example.com`，另一个测 `internal.corp`，互不影响。

---

## 5. 录制导入

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/ui/record/import` | 导入本地录制脚本 |

**`POST /ui/record/import` 请求**：

```json
{
  "project_id": 1,
  "source": "codegen",
  "script": "page.goto(\"https://example.com/login\")\npage.get_by_label(\"用户名\").fill(\"admin\")\n..."
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "import_log_id": 5,
    "parsed_lines": 12,
    "skipped_lines": 2,
    "pages_created": 1,
    "elements_created": 5,
    "elements_reused": 2,
    "case_id": 502,
    "warnings": ["第 7 行无法解析，已跳过：page.evaluate(...)"],
    "steps": [
      {"action": "goto", "url": "https://example.com/login"},
      {"action": "fill", "element": "登录页.用户名", "text": "admin"},
      {"action": "click", "element": "登录页.登录按钮"}
    ]
  },
  "msg": "导入完成"
}
```

**行为**：
1. **解析**：识别 `page.goto(url)` 与 `page.<locator_method>(args).<action>(args)` 模式（映射见 `steps.md` 与 `research.md` §3.7）
2. **自动建页面**：按 `page.goto` 的 URL 归一（origin + path）建立或复用页面
3. **自动建元素**：按 `(project_id, page_id, strategy, locator, name_attr)` 去重 —— 已存在则复用（`elements_reused` 计数），不存在则新建
4. **生成用例**：产出一条**状态为「调试中」**的 UI 用例（含步骤），走既有的用例创建逻辑；用户核对后改为「正常运行」即视为采纳
5. **跳过**：无法解析的行跳过并在 `warnings` 里说明，**不中断整段导入**
6. **不执行**：脚本中的任何内容都**不被执行**，只做静态解析

> **安全**：导入的脚本是外部输入。平台只做**静态文本解析**，不 eval、不 exec、不在浏览器里跑。脚本里的 `page.evaluate(...)` 这类行会被跳过并说明。

---

## 6. 执行节点

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/ui/node/list` | `Permission()` | 节点列表 |
| POST | `/ui/node/heartbeat` | `Permission()` | 节点心跳（v1 由内置节点自注册） |
| GET | `/ui/node/delete` | `Permission(role=Config.ADMIN)` | 删除节点 |

**响应**：

```json
{
  "code": 0,
  "data": [{
    "id": 1, "name": "内置本地节点", "node_type": "local", "status": 1,
    "browser": "chromium", "headless": true, "max_concurrency": 2, "version": "1.0.0"
  }],
  "msg": "操作成功"
}
```

---

## 7. 错误码

| code | 触发场景 | msg 示例 |
|---|---|---|
| `110` | 元素引用无效 | "引用的元素「登录页.注册按钮」不存在或已停用" |
| `110` | 定位到多个元素 | "定位到 3 个匹配元素，请用更精确的定位策略" |
| `110` | 动作不在白名单 | "不支持的动作：evaluate" |
| `110` | 目标域名不在白名单 | "目标域名 example.org 不在本项目允许列表内" |
| `110` | 协议不被允许 | "仅支持 http / https 协议" |
| `110` | 解析到私网地址 | "目标地址解析到内网地址，已按安全策略拒绝" |
| `110` | 白名单为空 | "本项目尚未配置允许访问的域名" |
| `110` | 元素存在但全部步骤无效 | "所有步骤均无效，用例未创建" |
| `110` | 节点不可用 | "没有可用的执行节点" |
| `403` | 白名单操作无权限 | "无权配置允许访问的域名" |

---

## 8. 接口与需求的对应

| 接口 | 对应 spec 需求 |
|---|---|
| `GET/POST /ui/page/*` | FR-001 |
| `GET/POST /ui/element/*` | FR-002 ~ FR-006 |
| `GET/POST /ui/case/*` | FR-007 ~ FR-013, FR-035 |
| `POST /ui/case/run` | FR-020 ~ FR-027（单条调试） |
| （复用 `POST /testcase/run`） | FR-027（批量执行，按 `request_type` 分派） |
| `GET/POST /ui/domain/*` | FR-043, FR-044 |
| `POST /ui/record/import` | FR-014 ~ FR-018 |
| `GET /ui/node/*` | FR-019 |
| （步骤校验，落 `/ui/case/*` 内） | FR-008, FR-009, FR-010, FR-041 |
| （前端编辑器就地指引与提示） | FR-010, FR-035, FR-036 |
| （执行器内部） | FR-042（上下文隔离）、FR-024（超时停后续） |
| （复用 `GET /testcase/report/list`） | FR-028, FR-029, FR-031 |
| （复用 `GET /testcase/report/:id` + 报告页扩附件 tab） | FR-030, FR-032, FR-033, FR-034 |

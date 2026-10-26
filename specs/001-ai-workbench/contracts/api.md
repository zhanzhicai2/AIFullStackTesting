# 契约 · HTTP 接口

> Feature: [AI 工作台](./spec.md) | Plan: [plan.md](./plan.md) | DSL: [dsl.md](./dsl.md)
> 前缀 `/ai`，全部走 `PityResponse` 的 `{code, data, msg}`。

---

## 1. 通用约定

### 1.1 响应信封

```json
{ "code": 0, "data": {}, "msg": "操作成功" }
```

| code | 含义 | 前端处理 |
|---|---|---|
| `0` | 成功 | 取 `data` |
| `101` | 参数错误（`RequestValidationError` 自动捕获） | 表单级提示 |
| `110` | 业务异常 | 全局提示，展示 `msg` |
| `401` | 未登录 | 跳登录页 |
| `403` | 无权限 | 全局提示 |

> HTTP 状态码恒为 `200`，业务码在 body 里（见 `backend/CLAUDE.md`）。

### 1.2 鉴权

所有接口 `Depends(Permission())`，即**登录即可用**。无更高角色要求 —— 理由：

- 用例创建本身普通用户就有权限，采纳草稿不扩大权限面
- 风险控制不靠权限，靠**默认状态"调试中"**（research §3.10）与**草稿态**（spec FR-008）

例外：`GET /ai/log/cluster` 当来源是**平台自身日志**时，需要 `Permission(role=Config.ADMIN)`（spec FR-009 对应验收场景 5）。日志文件上传与粘贴文本不受此限。

### 1.3 复用既有接口（不自建）

| 需求 | 复用 | 说明 |
|---|---|---|
| 可选对话模型列表 | `GET /ai/chat/models` | **不新建**。返回已启用的厂商与 `chat` 模型聚合列表 |
| 厂商/模型管理 | `GET/POST /ai/vendor/*`、`/ai/model/*` | 既有 |
| 执行 SQL（改写后验证） | `POST /online/sql` | 既有。SQL 分析页的"一键执行"直接调它 |
| 表结构 | `GET /datafactory/table/columns` | 既有。SQL 分析采集表结构时复用 |
| 文件上传 | `POST /oss/upload` | 既有。日志文件走 OSS |

---

## 2. 模型与调用流水

### 2.1 `GET /ai/invoke/log` — 模型调用流水

**查询参数**：`page`(默认1) · `size`(默认10) · `scene`(可选) · `model_name`(可选) · `start_time`/`end_time`(可选)

**响应**：

```json
{
  "code": 0,
  "data": {
    "total": 128,
    "list": [
      {
        "id": 902,
        "scene": "case_gen",
        "user_id": 3,
        "vendor_id": 2,
        "model_name": "deepseek-chat",
        "prompt_chars": 4821,
        "tokens": 1536,
        "elapsed": 12.4,
        "status": "success",
        "error_msg": "",
        "created_at": "2026-10-26 14:30:00"
      }
    ]
  },
  "msg": "操作成功"
}
```

> `error_msg` 不含 API Key，也不含完整 prompt 正文（prompt 可能含需求文档正文）。

---

## 3. 用例生成

### 3.1 `POST /ai/case/generate` — 生成用例草稿

**请求**：

```json
{
  "project_id": 1,
  "directory_id": 12,
  "title": "登录模块用例生成",
  "test_type": "api",
  "vendor_id": 2,
  "model_id": 5,
  "source_type": "document",
  "source_name": "登录需求.docx",
  "content": "……文档解析后的正文，或用户粘贴的需求文本……",
  "params": {"temperature": 0.2}
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `project_id` | ✅ | 所属项目 |
| `directory_id` | ✅ | 采纳目标目录。必须属于该项目 |
| `title` | ✅ | 任务标题，≤ 64 字符 |
| `test_type` | ✅ | `api` / `web` |
| `vendor_id` / `model_id` | ✅ | 模型。模型必须启用且类型为 `chat` |
| `source_type` | ✅ | `text` / `document` |
| `source_name` | `document` 时必填 | 文档名 |
| `content` | ✅ | 需求正文（文档由前端先调 §3.5 解析后传入，或直接传用户粘贴的文本） |
| `params` | — | 覆盖模型自身的参数（白名单键同 `ai_client`） |

**响应**：

```json
{
  "code": 0,
  "data": {
    "batch_id": 17,
    "case_count": 12,
    "total_tokens": 3420,
    "warnings": ["需求正文已截断（保留头部 6000 字符与尾部 2000 字符）", "用例「登录-异常路径」缺少 out_parameters，已丢弃其业务码断言"],
    "cases": [
      {"id": 88, "code": "AUTO-001", "title": "登录-正常路径", "category": "正向流程",
       "priority": "P0", "status": 1, "steps": 1, "warn": null}
    ]
  },
  "msg": "生成完成"
}
```

**行为**：
1. 校验项目、目录、模型
2. 按 `content` 长度检查并按需截断（头尾保留）→ 记 warning
3. 调用模型 → 解析 JSON → 逐条过 [dsl.md §5](./dsl.md#5-校验规则14-条) 的 14 条规则
4. 草稿落库，返回批次 id 与草稿摘要

**失败**：模型调用失败或两次解析都失败 → `code 110`，`msg` 为可操作原因（哪个厂商、什么错、建议动作）。

### 3.2 `GET /ai/case/draft/list` — 草稿列表

**查询参数**：`batch_id`(必填) · `status`(可选，1/2/3) · `page` · `size`

**响应**：`data = { total, list: [ {id, batch_id, code, title, category, priority, status, steps, warn, case_id, order} ] }`

### 3.3 `POST /ai/case/draft/update` — 修改单条草稿

**请求**：

```json
{
  "draft_id": 88,
  "content": { "cases": [ { "name": "登录-正常路径(改)", "...": "..." } ] },
  "title": "登录-正常路径(改)",
  "priority": "P1"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `draft_id` | ✅ | 草稿 id |
| `content` | — | 用户修正后的 DSL JSON。传则整体替换草稿内容 |
| `title` | — | 用户修正后的标题 |
| `priority` | — | 用户修正后的优先级 |
| `category` | — | 用户修正后的类别 |

**响应**：

```json
{
  "code": 0,
  "data": { "id": 88, "warn": ["步骤 3 引用的元素「登录页.注册按钮」在元素库中不存在，已丢弃该步骤"] },
  "msg": "保存成功"
}
```

**行为**：
- 保存时**重新过一遍 §5 的 14 条规则** —— 用户手工改的内容同样要校验，不能绕过
- 校验产生的告警回传并写入 `pity_ai_case_draft.warn`
- 只允许修改 `status = 1`（待审核）的草稿；已采纳或已驳回的草稿不可再改（`code 110`）
- `content` 为空则只更新元数据字段
- **修改后草稿仍是草稿**，不会自动写入正式用例库 —— 采纳仍是独立动作（spec FR-008）

> **为什么需要这个端点**：spec US1 验收场景 6 要求"不合规的字段被标出且该条草稿仍可被单独修正后采纳"。没有保存端点，用户的修正无处落地，草稿只能被丢弃或原样采纳。

### 3.4 `POST /ai/case/draft/accept` — 批量采纳

**请求**：

```json
{ "draft_ids": [88, 89, 90] }
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "succeeded": [88, 89],
    "failed": [{"id": 90, "reason": "目标目录不存在或已被删除"}]
  },
  "msg": "采纳完成：成功 2 条，失败 1 条"
}
```

**行为**（research §3.9）：
- **一条草稿一个事务**。某条失败不影响其余
- 幂等：`case_id` 已非空的草稿跳过（计入 `succeeded` 但不重复写入）
- 采纳后 `pity_testcase.status` 置 `1`（调试中）
- **采纳前的两道拦截**：
  1. 断言 `actually` 引用了未在 `out_parameters` 声明的变量 → 该草稿被拒（dsl.md 规则 8）
  2. Web UI 用例的步骤仍引用了元素库中不存在或已停用的元素 → 该草稿被拒（dsl.md 规则 13 / spec FR-039）
- 被拒的草稿**状态保持 `1`（待审核）**，不落正式用例库，失败原因逐条回显在 `failed[].reason`

### 3.5 `POST /ai/case/draft/reject` — 批量驳回

**请求**：`{ "draft_ids": [88] }` · **响应**：同 §3.4 结构。幂等：已是 `status = 3` 的跳过。

### 3.6 `POST /ai/document/parse` — 文档解析

**请求**：`multipart/form-data`，字段 `file`

**响应**：

```json
{
  "code": 0,
  "data": {
    "filename": "登录需求.docx",
    "content": "解析出的正文……",
    "chars": 8231,
    "truncated": false,
    "warnings": []
  },
  "msg": "解析成功"
}
```

**行为**：
- 只接受 PDF / Word / Markdown / 纯文本；其他类型 → `code 110`，`msg` 说明支持哪些类型
- 单文件 ≤ 20MB
- 解析失败 → 降级尝试按纯文本读取；仍失败 → `code 110`，提示改用文本输入（research §3.7）
- 超长按头尾截断并置 `truncated = true` + warning

---

## 4. 分析类

### 4.1 `POST /ai/bug/analyze` — Bug 分析

**请求**（二选一）：

```json
{ "result_id": 10231 }
```

或

```json
{ "text": "Traceback (most recent call last):\n  File \"app.py\", line 42\nKeyError: 'user_id'" }
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "analysis_id": 55,
    "summary": "响应体缺少 user_id 字段导致 KeyError",
    "category": "数据不一致",
    "confidence": 0.82,
    "root_causes": [
      {
        "cause": "上游接口返回体在 code 非 0 时不含 data 字段",
        "evidence": ["KeyError: 'user_id'", "\"code\": 500, \"msg\": \"内部错误\""],
        "confidence": 0.8,
        "verify_checklist": ["用 code=500 的响应体重放该用例"]
      }
    ],
    "fix_suggestions": [
      {"title": "响应体判空后再取值", "detail": "……", "patch": "data = resp.get('data') or {}"}
    ],
    "repro_steps": ["以无效 token 调用 GET /api/user/profile", "断言响应 code 为 0"],
    "history": {
      "total": 10,
      "failed": 8,
      "passed": 2,
      "consecutive_failures": 5,
      "pattern": "consistent_failure",
      "pattern_label": "必现",
      "note": "最近 10 次执行中失败 8 次，且失败表现一致",
      "recent": [
        {"result_id": 10231, "status": 1, "finished_at": "2026-10-26 10:00:00", "cost": 1.2,
         "summary": "断言失败：业务码 10001 ≠ 0"},
        {"result_id": 10190, "status": 1, "finished_at": "2026-10-25 18:22:10", "cost": 1.1,
         "summary": "断言失败：业务码 10001 ≠ 0"}
      ]
    }
  },
  "msg": "分析完成"
}
```

**`history` 字段**（承载 spec US2 验收场景 3 要求的"历史规律"）：

| 字段 | 说明 |
|---|---|
| `total` / `failed` / `passed` | 最近 N 次执行（默认 N=10）的结果分布 |
| `consecutive_failures` | 最近连续失败次数 |
| `pattern` | 规律判定，取值见下 |
| `pattern_label` | 规律的中文标签 |
| `note` | 一句话说明；**无历史可比时明确写出"缺少历史对比数据"** |
| `recent[]` | 最近若干次执行的摘要（结果 id / 状态 / 时间 / 耗时 / 失败摘要） |

`pattern` 取值：

| 取值 | 含义 | 判定依据 |
|---|---|---|
| `consistent_failure` | 必现 | 近期多次失败且失败摘要一致 |
| `intermittent` | 偶发 | 失败与成功交替出现 |
| `recovered` | 已恢复 | 近期成功且此前有失败 |
| `first_run` | 首次执行 | 无历史可比 —— **必须显式说明缺少历史对比数据，不得臆造历史规律**（spec Edge Case） |

**行为**：
- `result_id` 模式：后端自动从 `pity_test_result` 组装上下文（请求/响应/断言明细/执行日志/耗时/重试）+ 该用例最近 N 次执行历史（N 默认 10）
- 文本模式：仅用粘贴文本作为上下文；此时 `history` 恒为 `pattern = "first_run"` 并说明缺少历史数据
- **`evidence` 每一项 MUST 是上下文中的原文子串**。后端用子串匹配校验；不匹配的条目标记为「无依据」并从 `evidence` 移入 `unsupported` 字段，前端标灰（spec FR-020）
- **`history.pattern` MUST 依据真实执行记录判定**，无历史时必须是 `first_run` 并在 `note` 中说明（spec Edge Case「无历史可依」）
- 结论落 `pity_ai_analysis`（**每次一行，不覆盖**，research §3.8）
- `repro_steps` 可由前端一键带入用例生成（spec FR-022）

### 4.2 `POST /ai/log/cluster` — 日志聚类（不调模型）

**请求**：

```json
{
  "source": "platform",
  "file_id": null,
  "text": null,
  "since": "2026-10-26 00:00:00",
  "until": "2026-10-26 23:59:59",
  "max_lines": 20000
}
```

| `source` | 说明 | 权限 |
|---|---|---|
| `platform` | 平台自身日志（`backend/logs/pity_error.log`） | `Permission(role=Config.ADMIN)` |
| `file` | 已上传的日志文件（`file_id` → `pity_oss_file`） | `Permission()` |
| `text` | 粘贴的文本（`text`） | `Permission()` |

**响应**：

```json
{
  "code": 0,
  "data": {
    "total_lines": 18342,
    "error_clusters": [
      {
        "fingerprint": "a3f1c9d2",
        "sample": "KeyError: 'user_id'\n  File \"app/api/user.py\", line 42",
        "count": 1284,
        "first_at": "2026-10-26 03:12:44",
        "last_at": "2026-10-26 21:47:03",
        "scope": {"cases": 17, "users": 6}
      }
    ],
    "spikes": [
      {"start_at": "2026-10-26 14:00:00", "end_at": "2026-10-26 14:05:00", "count": 342, "baseline": 12}
    ],
    "truncated": false
  },
  "msg": "聚类完成"
}
```

**行为**：
- **本接口不调用模型**，纯确定性处理（research §3.12）。归一化 + 指纹分组
- 突增检测：按分钟计数，超过 p95 判为突增（spec FR-025）
- 单次输入 ≤ 10MB；超限按头尾截断并置 `truncated = true`
- `scope` 统计该错误簇涉及的用例与用户（从日志行中提取 case_id / user_id）

### 4.3 `POST /ai/sql/analyze` — SQL 分析

**请求**：

```json
{
  "sql": "select * from orders where user_id = 1001",
  "database_id": 3,
  "sql_history_id": null
}
```

二选一：直接给 `sql`，或给 `sql_history_id`（从 `pity_sql_history` 取）。

**响应**：

```json
{
  "code": 0,
  "data": {
    "analysis_id": 56,
    "elapsed_ms": 812,
    "plan": [
      {"table": "orders", "type": "ALL", "rows": 128400, "filtered": 100.00, "key": null}
    ],
    "problems": [
      {"level": "high", "point": "orders 表全表扫描", "detail": "type=ALL 且 rows≈12.8 万，实际命中 1 行"}
    ],
    "index_suggestions": [
      {"table": "orders", "ddl": "ALTER TABLE orders ADD INDEX idx_user_id (user_id);", "reason": "过滤列 user_id 无可用索引"}
    ],
    "rewritten_sql": "select id, amount, status from orders where user_id = 1001",
    "table_refs": ["orders"]
  },
  "msg": "分析完成"
}
```

**行为与硬约束**：

| 项 | 规则 |
|---|---|
| **执行计划采集** | **只允许普通 `EXPLAIN`**。`EXPLAIN ANALYZE`（及其 `FORMAT=` 变体）**在 SQL 解析层硬拦**，直接返回 `code 110`，不发给数据库 |
| **只读保证** | 采集计划只发 `EXPLAIN` 语句，**不执行目标 SQL 本身**。对 `UPDATE`/`DELETE` 也只做计划采集 |
| **表结构与索引** | 复用既有 `GET /datafactory/table/columns` 与 `information_schema.STATISTICS` |
| **历史耗时** | 若 `sql_history_id` 给出或 SQL 能匹配历史记录，返回 `elapsed_ms` |
| **改写建议可验证** | `rewritten_sql` MUST 能直接在 `POST /online/sql` 执行（前端提供"执行验证"按钮） |
| **提示词注入防护** | 传入的 `sql` 用 `<sql>` 标签包裹（dsl.md §6.1） |

> **为什么硬拦 `EXPLAIN ANALYZE`**：MySQL 8.0.18+ 的 `EXPLAIN ANALYZE` 会真实执行查询。对 `UPDATE`/`DELETE` 这等于在生产库执行写操作。提示词里写"不要用"是软约束、模型不保证遵守；解析层硬拦才是硬约束（research §3.11）。

### 4.4 `POST /ai/log/analyze` — 错误簇归因

**请求**：`{ "fingerprint": "a3f1c9d2", "samples": ["...", "..."], "count": 1284 }`

**响应**：结构同 §4.1 的 `root_causes` / `fix_suggestions`，但 `evidence` 引用簇内日志行。

### 4.5 `GET /ai/sql/slow` — 慢查询排行

**查询参数**：`database_id`(可选) · `page` · `size` · `min_elapsed`(可选，毫秒)

**响应**：

```json
{
  "code": 0,
  "data": {
    "total": 214,
    "list": [
      {"id": 55, "sql": "select * from orders ...", "elapsed": 3200,
       "database_id": 3, "database_name": "生产主库",
       "create_user": "张三", "created_at": "2026-10-26 10:12:00"}
    ]
  },
  "msg": "操作成功"
}
```

> 数据源为既有的 `pity_sql_history`，**不新建表**。

---

## 5. 错误码

| code | 触发场景 | msg 示例 |
|---|---|---|
| `110` | 厂商未启用 | "该厂商未启用或未配置 API Key, 请联系管理员" |
| `110` | 模型不存在 | "模型不存在" |
| `110` | 模型非对话类 | "该模型未启用或不是对话模型" |
| `110` | 模型调用失败 | "请求厂商接口失败: ..."（沿用 `ai_client._status_message`） |
| `110` | 输出无法解析 | "模型返回的内容无法解析为合法结构, 已重试 1 次仍失败, 请重试" |
| `110` | 目录不存在 | "目标目录不存在或已被删除" |
| `110` | 文档类型不支持 | "不支持的文件类型, 当前支持 PDF / Word / Markdown / 纯文本" |
| `110` | 文档过大 | "文件超过 20MB 上限" |
| `110` | 命中 `EXPLAIN ANALYZE` | "仅支持普通 EXPLAIN 采集执行计划, 不允许 EXPLAIN ANALYZE" |
| `101` | 参数校验失败 | Pydantic 自动捕获 |
| `403` | 平台自身日志无权限 | "无权访问平台运行日志" |

---

## 6. 接口与需求的对应

| 接口 | 对应 spec 需求 |
|---|---|
| `POST /ai/case/generate` | FR-002, FR-003, FR-004, FR-005, FR-011, FR-012, FR-037, FR-038, FR-039 |
| `GET /ai/case/draft/list` | FR-005, FR-006 |
| `POST /ai/case/draft/update` | FR-011（用户修正草稿后可继续采纳） |
| `POST /ai/case/draft/accept` | FR-007, FR-008, FR-009, FR-010, FR-012, FR-039 |
| `POST /ai/case/draft/reject` | FR-007 |
| `POST /ai/document/parse` | FR-003 |
| `POST /ai/bug/analyze` | FR-016 ~ FR-022 |
| `POST /ai/log/cluster` | FR-023 ~ FR-025, FR-041 |
| `POST /ai/log/analyze` | FR-026 |
| `POST /ai/sql/analyze` | FR-028 ~ FR-031 |
| `GET /ai/sql/slow` | FR-027 |
| `GET /ai/invoke/log` | FR-015 |
| （模型列表复用 `GET /ai/chat/models`） | FR-014 |
| （SQL 执行复用 `POST /online/sql`） | FR-030 |

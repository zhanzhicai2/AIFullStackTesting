# Phase 1 · 数据模型

> Feature: [AI 工作台](./spec.md) | Plan: [plan.md](./plan.md) | Research: [research.md](./research.md)
> 契约：[contracts/dsl.md](./contracts/dsl.md)（前后端唯一契约）· [contracts/api.md](./contracts/api.md)

---

## 1. 实体总览

```
                    ┌─────────────────────┐
                    │  pity_ai_draft_batch │  生成批次
                    │  (一次生成任务)      │
                    └──────────┬──────────┘
                               │ 1:N
                    ┌──────────▼──────────┐
                    │  pity_ai_case_draft │  用例草稿（待审核）
                    │  status: 1待/2采纳/3驳回 │
                    └──────────┬──────────┘
                               │ 采纳时写入（case_id 回填）
                    ┌──────────▼──────────┐
                    │   pity_testcase     │  正式用例（既有表）
                    └──────────┬──────────┘
                               │ 1:N
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼────────┐ ┌────▼──────────┐ ┌────▼─────────────┐
    │pity_testcase_    │ │pity_constructor│ │pity_out_         │
    │asserts           │ │                │ │parameters         │
    └──────────────────┘ └───────────────┘ └──────────────────┘

  独立于上述链路的两张留痕表：
    ┌────────────────────┐   ┌────────────────────┐
    │pity_ai_invoke_log  │   │pity_ai_analysis    │
    │(每次模型调用)       │   │(每次分析结论)       │
    └────────────────────┘   └────────────────────┘
```

**四张新表的职责边界**：

| 表 | 回答什么问题 | 生命周期 |
|---|---|---|
| `pity_ai_draft_batch` | 这次生成任务是什么、用了哪个模型、花了多少 | 任务完成后长期留存，可归档 |
| `pity_ai_case_draft` | 这条用例长什么样、审没审、采纳没有 | 随批次留存，采纳后关联正式用例 |
| `pity_ai_invoke_log` | 谁在什么时候用什么模型调了 AI、花了多少、成没成 | 长期留存，供成本核算与模型效果评测 |
| `pity_ai_analysis` | 当时给出的分析结论是什么 | **每次分析一行**，永不覆盖 |

> **为什么必须建表**（对比数据工厂的"不建批次表"）：数据工厂的产物由 `rules + seed` 唯一确定，可重放，所以不建表。本功能的产物来自模型输出，**不可重放**（constitution 原则 I），因此必须落库固定。

---

## 2. 表定义

所有表继承 `PityBase`（`app/models/basic.py`），自动具备 `id`、`created_at`、`updated_at`、`deleted_at`（软删）、`create_user`、`update_user`。

### 2.1 `pity_ai_draft_batch` — 生成批次

`backend/app/models/ai_draft.py`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `title` | String(64) | not null | 任务标题 |
| `project_id` | INT | index | 所属项目 → `pity_project.id` |
| `directory_id` | INT | — | 采纳目标目录 → `pity_testcase_directory.id` |
| `vendor_id` | INT | — | 使用的厂商 → `pity_ai_vendor.id` |
| `model_name` | String(128) | — | 使用的模型名（快照，不随厂商配置变更而变） |
| `test_type` | String(16) | default `'api'` | `api` / `web` / `manual` / `mobile`(预留) |
| `source_type` | String(16) | — | `text` / `document` |
| `source_name` | String(128) | — | 文档名；文本输入时为空 |
| `source_chars` | INT | default 0 | 实际送入模型的字符数（截断后） |
| `status` | INT | default 1 | 1生成中 / 2已完成 / 3已归档 |
| `case_count` | INT | default 0 | 草稿数量 |
| `total_tokens` | INT | default 0 | 本批消耗 token |
| `warnings` | TEXT | — | JSON 数组：截断提示、解析告警、校验告警汇总 |

**唯一约束**：无（同名任务允许重复）

**校验规则**：
- `title` 非空
- `project_id` 必须指向存在的项目
- `directory_id` 必须指向属于该项目、且 `deleted_at = 0` 的目录
- `test_type` ∈ {`api`, `web`, `manual`, `mobile`}
- `source_type` ∈ {`text`, `document`}
- `model_name` 必须对应一个启用中的 `chat` 模型

### 2.2 `pity_ai_case_draft` — 用例草稿

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `batch_id` | INT | index not null | 所属批次 → `pity_ai_draft_batch.id` |
| `code` | String(32) | — | 用例编码，如 `AUTO-001`（批次内序号） |
| `title` | String(64) | not null | 用例标题 |
| `category` | String(32) | default `'正向流程'` | 类别 |
| `priority` | String(3) | default `'P1'` | P0–P4 |
| `status` | INT | default 1 | 1待审核 / 2已采纳 / 3已驳回 |
| `steps` | INT | default 1 | 步骤数 |
| `content` | TEXT | not null | **完整 DSL JSON**（唯一真源） |
| `case_id` | INT | — | 采纳后回填 `pity_testcase.id` |
| `warn` | TEXT | — | JSON 数组：本条的校验告警 |
| `order` | INT | default 0 | 批次内排序 |

**唯一约束**：`UniqueConstraint('batch_id', 'code', 'deleted_at')`

**校验规则**：
- `title` 非空
- `priority` ∈ {P0, P1, P2, P3, P4}（与 `frontend/src/consts/config.ts` 的 `PRIORITY` 一致）
- `category` ∈ {正向流程, 异常流程, 边界值, 权限, 并发, 其他}
- `content` 必须是合法 JSON，且符合 [contracts/dsl.md](./contracts/dsl.md)
- `status = 2` 时 `case_id` MUST 非空；`status ≠ 2` 时 `case_id` MUST 为空
- `status ≠ 1`（已采纳/已驳回）时 `content` 冻结，不再接受修改

**状态流转**：

```
        生成成功                批量采纳                 批量驳回
  ────────────────►  (1待审核) ─────────────►  (2已采纳) ─┐
                          │                                 │
                          └──────────────────────────────►  (3已驳回)
                                                            │
                                        重新生成批次 ◄────────┘
                                        （旧草稿保留，不变）
```

> `3已驳回` 是终态。要重新生成会产生**新批次**下的新草稿 —— 旧草稿保留供对比（这正是"重新生成不可重放"这一事实的可追溯体现）。

### 2.3 `pity_ai_invoke_log` — 模型调用流水

| 字段 | 类型 | 说明 |
|---|---|---|
| `scene` | String(32) index | `case_gen` / `bug` / `log` / `sql` |
| `user_id` | INT index | 调用人 → `pity_user.id` |
| `vendor_id` | INT | 厂商 |
| `model_name` | String(128) | 模型名 |
| `prompt_chars` | INT | prompt 字符数 |
| `tokens` | INT | token 用量（厂商返回的 usage，缺失时 0） |
| `elapsed` | FLOAT | 耗时（秒） |
| `status` | String(16) | `success` / `failed` |
| `error_msg` | TEXT | 失败原因（已脱敏，不含 API Key） |

**用途**（spec FR-015）：
1. 成本核算 —— 按场景/用户/模型统计 token 与耗时
2. 效果评测 —— 后续按 `scene` 聚合，比较不同模型在同一场景下的表现
3. 故障定位 —— 区分"模型返回了但解析失败"与"调用本身失败"

**注意**：`error_msg` MUST NOT 包含 API Key 或完整的 prompt 内容（prompt 里可能含需求文档正文，属敏感数据）。

### 2.4 `pity_ai_analysis` — 分析结论

| 字段 | 类型 | 说明 |
|---|---|---|
| `scene` | String(16) index | `bug` / `log` / `sql` |
| `title` | String(128) | 标题（用例名 / 错误簇指纹 / SQL 摘要） |
| `project_id` | INT index | 所属项目（可空） |
| `ref_type` | String(32) | `result`（执行记录）/ `log_cluster` / `sql_history` / `manual` |
| `ref_id` | INT | 关联对象 id；`manual` 时为 0 |
| `result` | TEXT | **结构化结论 JSON** |
| `vendor_id` / `model_name` | — | 产出该结论的模型 |
| `tokens` | INT | token 用量 |

**唯一约束**：无 —— **每次分析一行，不覆盖**（research §3.8）

**结论 JSON 结构**（三场景同构，字段按场景裁剪）：

```json
{
  "summary": "一句话结论",
  "category": "参数校验|数据不一致|依赖超时|配置错误|代码缺陷|未知",
  "confidence": 0.82,
  "root_causes": [
    {
      "cause": "根因描述",
      "evidence": ["引用上下文原文的第 1 行", "第 2 行"],
      "confidence": 0.8,
      "verify_checklist": ["如何自证这条判断"]
    }
  ],
  "fix_suggestions": [
    {"title": "建议标题", "detail": "建议详情", "patch": "可选代码片段"}
  ],
  "repro_steps": ["可复现步骤 1", "步骤 2"]
}
```

**校验规则**：
- `evidence` MUST 非空且每一项 MUST 是上下文中的**原文子串**（后端用子串匹配校验，不匹配则该条根因标记为"无依据"并在前端标灰）
- `confidence` ∈ [0, 1]
- `repro_steps` 仅 `scene = bug` 时有意义

---

## 3. 跨端契约与常量

### 3.1 唯一契约文档

[contracts/dsl.md](./contracts/dsl.md) 是前后端的**唯一真源**。两端的常量文件互相指认：

| 常量 | 后端权威定义 | 前端镜像 | 指认方式 |
|---|---|---|---|
| 用例 DSL 的动作集、测试类型、类别 | `app/core/ai_prompts/case_gen.py` | `frontend/src/consts/aiWorkbench.ts` | 前端文件头注释指认后端路径；`backend/CLAUDE.md` 声明"必须同步修改两处" |
| **断言类型白名单（14 种）** | `app/enums/AIWorkbenchEnum.py`（**本次迁移**） | `frontend/src/consts/config.ts` 的 `ASSERT_TYPE` | 同上。前端保留原导出名以免影响既有引用面 |
| 优先级 P0–P4 | `app/enums/AIWorkbenchEnum.py` | `frontend/src/consts/config.ts` 的 `PRIORITY` | 同上 |
| 场景枚举 | `app/enums/AIWorkbenchEnum.py` | `frontend/src/consts/aiWorkbench.ts` | 同上 |

> **本次修正**：断言白名单原先权威定义在前端 TS（后端无法引用）。迁移到后端后，后端校验器与前端表单读同一份定义 —— 消除 constitution 原则 III 所指出的"静默漂移"风险。详见 research §3.1。

### 3.2 与既有表的字段对齐

采纳时从 DSL 拆出的字段到既有表的映射（**必须逐字对齐，不做二次转换**）：

| DSL 字段 | 目标表.字段 | 约束来源 |
|---|---|---|
| `cases[].name` | `pity_testcase.name` | `String(32)` → **超长必须截断并告警** |
| `cases[].request.url` | `pity_testcase.url` | `TEXT nullable=False` → 不可为空 |
| `cases[].request.method` | `pity_testcase.request_method` | `String(12)` |
| `cases[].request.headers` | `pity_testcase.request_headers` | `TEXT`，运行时 `json.loads` → **必须是 JSON 对象** |
| `cases[].request.body` | `pity_testcase.body` | 同上 |
| `cases[].request.body_type` | `pity_testcase.body_type` | ∈ {0,1,2,3,4,5} |
| — | `pity_testcase.request_type` | 恒为 `1`（http）；UI 用例为 `4`（见 `002-ui-automation`） |
| `cases[].priority` | `pity_testcase.priority` | P0–P4 |
| `cases[].tags` | `pity_testcase.tag` | `String(64)`，多个 tag 用逗号连接 |
| — | `pity_testcase.status` | 恒为 `1`（调试中），见 research §3.10 |
| — | `pity_testcase.directory_id` | 取批次的 `directory_id` |
| — | `pity_testcase.case_type` | 恒为 `0`（普通用例） |
| `cases[].out_parameters[]` | `pity_out_parameters` | `name` ≤ `String(24)`；`source` ∈ {0,1,2,3,4} |
| `cases[].asserts[]` | `pity_testcase_asserts` | `name` ≤ `String(32)`；`assert_type` ∈ 14 种白名单 |
| `cases[].pre_conditions[]` | `pity_constructor`（`suffix = false`） | `type` ∈ {0,1,2,3,4}；`name` ≤ `String(64)` |
| `cases[].post_conditions[]` | `pity_constructor`（`suffix = true`） | 同上 |

---

## 4. 状态流转与确定性（constitution 原则 I）

### 4.1 不可重放的事实

**模型输出不可重放。** 同一份需求输入，两次生成得到的草稿不同。这是 AI 的本质，无法通过工程手段消除 —— constitution 原则 I 要求"若确实无法重放，MUST 在代码注释与设计文档中显式标注该字段不可重放"。

**本功能的处理**（把不可重放的影响面收敛到一个动作）：

```
   不可重放的部分                     可重放的部分
   ─────────────                    ──────────────
   「重新生成」                       「重复采纳同一份草稿」
   ↓                                 ↓
   产生新草稿（批次 2）                写入完全相同的用例
   旧草稿保留供对比                    结果逐字段相等 ✅
```

因此，**确定性的锚点是草稿内容的"当前版本"**，而不是"最初生成的那一版"：

| 草稿状态 | `content` 是否可变 | 说明 |
|---|---|---|
| `status = 1`（待审核） | ✅ 可变 | 用户可通过 `POST /ai/case/draft/update` 修正草稿；每次保存覆盖 `content` 并更新 `updated_at`，**保存时重新过一遍 14 条校验规则** |
| `status = 2`（已采纳） | ❌ 冻结 | `case_id` 已回填，用例已入库，内容不再可改 |
| `status = 3`（已驳回） | ❌ 冻结 | 终态 |

> **精确表述**：草稿的**当前 `content` 版本**是确定性锚点 —— 重复采纳同一版本的草稿，MUST 产出逐字段相等的结果。保存修改只是把锚点移到了新版本；被替换掉的旧版本随草稿内容一同消失（`pity_ai_case_draft` 只存当前版本，不存历史版本）。

**MUST 显式标注的位置**：
- `pity_ai_case_draft` 的 Model 类 docstring
- `contracts/dsl.md` §7
- `backend/docs/ai-workbench-design.md` §3.3

### 4.2 幂等保证

| 动作 | 幂等方式 |
|---|---|
| 重复采纳同一条草稿 | `pity_ai_case_draft.case_id` 已非空 → 跳过（草稿一旦采纳即冻结，不会出现"改了又采纳"的歧义） |
| 重复驳回同一条草稿 | `status` 已是 `3` → 跳过 |
| 修改已采纳/已驳回的草稿 | `status ≠ 1` → 拒绝（`code 110`） |
| 同一批次重复请求生成 | 以 `batch_id` 为幂等键；批次内已有草稿时不重复调模型 |
| 重复分析同一对象 | **不幂等** —— 每次分析新增一行（research §3.8），这是刻意设计 |

---

## 5. 就地指引点（constitution 原则 IV）

constitution 原则 IV 要求"交互所需的数据源若尚未配置，界面 MUST 在原地给出明确指引(去哪里配)"。本功能的前置依赖全部在界面外，逐项规定：

| 编号 | 前置条件缺失 | 界面就地指引 | 降级行为 |
|---|---|---|---|
| **G1** | 无启用中的 `chat` 模型 / 厂商未配凭据 | 生成工作台顶部提示条：「当前无可用模型，去[模型设置]配置或启用」+ 直接跳转链接 | 禁用"开始生成"按钮（不提交后才发现） |
| **G2** | 所选项目下无目录 | 「目标目录」选择器旁提供「新建目录」入口，就地建完即选中 | 无目录则不提交，并明示原因 |
| **G3** | 未配置对象存储 | 文档上传区提示「未配置对象存储，文档将仅本次解析不落盘」+ 跳转配置入口 | **不阻断**：文档内容解析后直接进 prompt，不落盘 |
| **G4** | `test_type = web` 但元素库为空 | 表单内提示「Web UI 用例需引用元素库中已沉淀的元素，元素库为空」+ 跳转元素库 | 允许生成，但生成的草稿全部标为"缺少可用元素" |
| **G5** | 模型调用失败 / 输出无法解析 | 在结果区显示可操作原因（哪个厂商、什么错误、建议动作），并提供「重试」按钮 | 草稿表保持原样（不产生半成品批次） |

> **G1 与 G5 的区别**：G1 是"事前可知"（配置缺失，提交前就能拦），G5 是"事后可知"（调用本身失败）。两者都必须给可操作指引，不能只报错误码。

---

## 6. 与既有表的关系

| 新表/新字段 | 既有表 | 关系 |
|---|---|---|
| `pity_ai_draft_batch.project_id` | `pity_project` | 多对一 |
| `pity_ai_draft_batch.directory_id` | `pity_testcase_directory` | 多对一；`directory_id` 必须属于同项目 |
| `pity_ai_case_draft.case_id` | `pity_testcase` | 采纳后一对一 |
| `pity_ai_analysis.ref_id` | `pity_test_result` / `pity_sql_history` | 多对一（多次分析指向同一对象） |
| `pity_ai_invoke_log.user_id` | `pity_user` | 多对一 |
| `pity_ai_invoke_log.vendor_id` | `pity_ai_vendor` | 多对一 |

**软删除语义**：四张新表全部继承 `PityBase` 的 `deleted_at` 软删。删除草稿批次时，其下草稿一并软删，但**已采纳的正式用例不受影响** —— 草稿是编辑期的产物，用例是长期资产，两者生命周期必须解耦。

---

## 7. 迁移

沿用仓库既有做法：项目启动时 `Base.metadata.create_all` 自动建表（Alembic 配置存在但自动建表是主路径，见 `backend/CLAUDE.md`）。

新增四张表**不修改任何既有表结构** —— 唯一涉及既有代码的改动是 `pity_testcase.request_type` 的语义扩展（新增取值 `4`），该字段本就 `INT default 1`，**无需改列结构**，只是取值域扩大。

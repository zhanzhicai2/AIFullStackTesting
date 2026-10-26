# Specification Quality Checklist: AI 工作台

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-26
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

### 校验记录（2026-10-26）

**未使用 [NEEDS CLARIFICATION] 标记（0 个）**。范围边界靠 FR-040（Appium 预留不实现）与 Assumptions 收口，未决项均有合理默认：

| 原潜在歧义 | 采纳的默认 | 记录位置 |
|---|---|---|
| "功能测试点（手工）" 是否要做 | 不做，测试类型只两种（接口 / Web UI） | FR-037 / FR-040 |
| 采纳后的用例是否自动进计划、是否立即执行 | 否，只写入用例库 | Assumptions |
| 模型不可用时怎么办 | 界面就地说明如何配置 | FR-014 / FR-034 |
| 平台自身日志的权限 | 沿用平台既有权限模型收紧 | **FR-041** / US3 验收场景 5 / Assumptions |
| 首次执行的用例没有历史 | 明确说明缺历史，不臆造 | Edge Cases |
| AI 产出是否可重放 | 不可重放，草稿生成后即固定 | Assumptions |

**首轮校验发现并已修复（1 项）**：

- FR-026 原表述"对排名靠前的错误簇给出根因解释"——"排名靠前"不可测，无法判定需求是否满足。已改为"支持对任意单个错误簇发起归因，并支持一次性对排名靠前的错误簇批量归因"，把可测性落在"单个可发起"这个动作上，"排名靠前"降级为批量操作的默认范围描述。

**逐项核对要点**：

- *No implementation details* —— 全文未出现框架名、语言、数据库、接口路径、表名。出现的"元素库""前置/后置步骤""断言""执行计划""索引"均属目标用户（测试/开发）的既有业务词汇，非实现细节。输入侧的文件格式（PDF/Word/Markdown/TXT）是用户可见的需求约束，保留。
- *Requirements are testable* —— 40 条 FR 全部以 MUST 描述可观测行为。FR-015（调用留痕）与 FR-036（结论留存）属横切要求，由 Edge Cases 中的"重复分析"与 FR-015 本身承接。
- *Success criteria are measurable* —— SC-001 至 SC-010 全部带数值或明确比例；SC-006 用"下降一个数量级以上"表述，未绑定具体技术指标。
- *Scope is clearly bounded* —— 四个场景构成完整范围；明确排除项见 FR-040 与 Assumptions 末两条（不做自动修代码、不自动提缺陷单）。
- *Dependencies identified* —— 元素库依赖已在 Assumptions 与 FR-038/FR-039 显式承接，未把它当作已有能力蒙混过关。

**遗留**：本清单由 `/speckit-specify` 生成并维护，属需求质量评审产物。`[x]` 表示该项经复核满足质量标准，**不代表实现工作已完成**。

---

## 复核记录 · 2026-10-26（`/speckit-analyze` 后）

`/speckit-analyze` 跑出 13 条发现（1 CRITICAL / 4 HIGH / 4 MEDIUM / 4 LOW），已全部处理：

| 编号 | 问题 | 处理 |
|---|---|---|
| E1 | FR-039（引用不存在元素必须拦下）**零任务覆盖** | `contracts/dsl.md` 新增规则 11–14；`tasks.md` 新增 T027（采纳前两道拦截）与 T025（规则 12/13） |
| E2 | FR-038 覆盖不足 | 同上 |
| C1 | "单条修正后采纳"无后端支撑 | `contracts/api.md` 新增 `POST /ai/case/draft/update`；`tasks.md` 新增 T031（前端保存）、T034（e2e） |
| B1 | US2 要求"体现历史规律"但响应无承载字段 | `contracts/api.md` §4.1 新增 `history` 结构（`pattern` 四取值）；spec US2 验收场景 3/4 重写并补场景 |
| C2 | 001 的契约外链到尚未产出的 002 契约 | `contracts/dsl.md` §4 内联最小可用规则集（规则 11–14），并注明 002 契约产出前以 001 为准 |
| F1 | Phase 1 挂路由但页面组件未实现 | `tasks.md` 新增 T008（四个占位组件）与 T009（路由指向占位），各故事阶段替换 |
| F2 | 平台自身日志权限无对应 FR；本清单误引 FR-009 | spec 新增 **FR-041**；本清单引用已改正 |
| D1 | 4 个质量类 SC 只能人工判定，与原则 V 有张力 | `quickstart.md` §6.2 定抽样口径；`tasks.md` 新增 T062（评测脚本）记录判定结果 |
| B2 | 质量类 SC 无统一判定口径 | 同上（抽样规模/来源/判定人/口径/记录方式五项） |
| C3 | Web UI 生成在 002 未就绪时的降级行为不明 | spec US1 补验收场景 8/9；`tasks.md` US1 依赖说明补降级路径 |
| A1 | FR-013 与 FR-036 重复 | **原判定有误**：FR-036 是"分析结论留存历史"，与"元素库为空"无关。实际处理是扩充 FR-013 的枚举（把此前只隐含在 G4 的情形落到 FR） |
| A2 | G1–G5 在三处重复列举 | 定 `data-model.md` §5 为唯一定义；`quickstart.md` §4 与 `tasks.md` T029 改为引用 |
| F3 | plan.md 树形缩进错位 | 已修 |
| F4 | 术语漂移「模型调用记录 / 流水」 | 统一为「调用流水」（spec Key Entities、tasks T058/T059） |

**顺带修正**：`data-model.md` §4.1 原表述"草稿 `content` 即为不可变快照"与新增的草稿编辑能力冲突，已改为"**当前 `content` 版本**是确定性锚点"，并明确 `status ≠ 1` 时内容冻结。

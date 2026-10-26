# Specification Quality Checklist: UI 自动化子系统

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

**未使用 [NEEDS CLARIFICATION] 标记（0 个）**。范围靠 FR-037 ~ FR-040 四条明确的"不做"收口，未决项均有合理默认：

| 原潜在歧义 | 采纳的默认 | 记录位置 |
|---|---|---|
| 分布式执行节点 / 远程浏览器做不做 | 不做，只做内置执行节点 | FR-037 |
| 浏览器扩展录制 / 服务端注入录制做不做 | 都不做，本次只做本地录制导入 | FR-038 / FR-039 |
| Appium 移动端做不做 | 不做，但保留测试类型位置 | FR-040 |
| 智能生成 UI 用例归谁 | 归 AI 工作台功能，且只能引用元素库已有元素 | FR-011 / Assumptions |
| 本功能是否依赖 AI | 不依赖，可全程手工登记 + 手写 + 执行 | Assumptions |
| 元素定位失效时怎么表现 | 失败信息指明是哪个元素、哪种策略失效 | FR-023 |
| 元素与用例的耦合风险 | 明确写入 Assumptions，作为"核心价值同时也是需留意的风险" | Assumptions |
| 录制脚本里的自由代码怎么办 | 拒绝解析、不执行 | FR-018 / SC-010 |
| 并发执行时登录态会不会互相污染 | 上下文互相隔离 | FR-042 / Assumptions |

**首轮校验发现并已修复（1 项）**：

- FR-036 原表述"就地说明如何处理"——"就地"未定义验证方式。已改为"在当前界面内给出可操作的指引（去哪里配、怎么建），用户 MUST NOT 需要离开当前页面自行寻找"，把可测性落到"用户是否需要离开当前界面"这个可观察行为上。

**逐项核对要点**：

- *No implementation details* —— 全文未出现具体浏览器自动化框架、语言、数据库、接口路径或表名。出现的"CSS、XPath、ID、文本、Role、Placeholder、Label"是元素定位表单里用户直接选择的**配置值**（属业务词汇）；"无头模式""视口尺寸"是用户可见的执行配置项；"录制脚本"是用户输入物。三者都是用户能看见、能操作的界面概念，非实现细节。**刻意未点名任何浏览器自动化框架**。
- *Requirements are testable* —— 42 条 FR 全部以 MUST 描述可观测行为。FR-008（封闭动作集合）的集合内容定义在深设计文档中，但需求本身可测：给出集合外的动作时被拒绝即满足。
- *Success criteria are measurable* —— SC-001 ~ SC-010 全部带数值、比例或明确可观察状态；SC-006 用"下降 90% 以上"衡量元素库解耦收益，与本功能的核心主张直接对应。
- *Scope is clearly bounded* —— 四条"不做"（FR-037~FR-040）显式列出，与本次范围讨论中已确认的排除项一一对应。
- *Dependencies identified* —— 对 AI 工作台的依赖写在 FR-011 与 Assumptions，未把它当作已就绪能力蒙混过关。

**遗留**：本清单由 `/speckit-specify` 生成并维护，属需求质量评审产物。`[x]` 表示该项经复核满足质量标准，**不代表实现工作已完成**。

---

## 复核记录 · 2026-10-26（`/speckit-plan` 后）

`/speckit-plan` 的 GATE-SEC 门禁核验中识别出**一个新的安全面**，已回写进 spec：

| 项 | 内容 |
|---|---|
| **新识别的安全面** | **浏览器执行 = 新的出网面（SSRF）**。UI 用例会让平台驱动真实浏览器访问目标站点，而目标地址可由用户写入 → 用户可让平台访问内网地址或云厂商元数据接口（`169.254.169.254`）。既有安全面（`exec()` / 未沙箱渲染 / 明文凭据 / 数据写入通道）**都没有覆盖这一条** —— 它是本 feature 独有的新面 |
| **spec 补的两条 FR** | **FR-043**（只能访问项目级允许域名白名单内的站点；解析到私网/环回/链路本地/保留地址一律拒绝；重定向逐跳重校验）· **FR-044**（白名单为空 = 不可执行，不得解释为"允许全部"） |
| **spec 补的验收场景** | US1 新增 3 条：域名不在白名单 → 拒绝执行；域名被允许但解析到内网 → 拒绝执行；白名单为空 → 明确说明并给配置入口，不默认放行 |
| **落地位置** | `data-model.md` §7（拦截清单 6 条）· `contracts/api.md` §4（白名单接口 + 权限收紧到 ADMIN）· `research.md` §3.8（决策与备选方案）· `plan.md` GATE-SEC 专门说明 |
| **失败方向的选择** | 白名单为空时**拒绝执行**而非放行；定位到多个元素时**显式失败**而非取第一个 —— 两处都是刻意选"宁可失败"的失败方向（与 `001-ai-workbench` 的草稿拦截同一思路） |

**另一处补正**：GATE-I（确定性优先）在 UI 场景下需要划边界 —— 确定的是**步骤定义与平台自身行为**（无隐式 sleep、无随机退避、无随机选择），不可重放的是**执行结果**（取决于被测系统当时状态，不在平台可控范围）。该不可重放事实 MUST 在代码注释与设计文档中显式标注（`contracts/steps.md` §7）。

---

## 复核记录 · 2026-10-26（`/speckit-analyze` 后）

`/speckit-analyze` 跑出 17 条发现（1 CRITICAL / 3 HIGH / 5 MEDIUM / 8 LOW），已全部处理：

| 编号 | 问题 | 处理 |
|---|---|---|
| **E1** | **`pity_ui_page` 的页面树 CRUD 零任务覆盖**（页面树是元素库的地基，FR-001 无任务，T016 描述自相矛盾） | `tasks.md` 新增 **T016**（`routers/ui/page.py` 页面树 CRUD，含"删除不级联删元素"）；原 T016 改为只覆盖 `element.py`（T017）；T016 之后任务编号统一 +1 |
| **F1** | **FR-016 与 §3.11 决策矛盾**（FR-016 写"审核采纳后才入库"，决策已改为"调试中"语义） | FR-016 改为"产出状态为「调试中」的可编辑 UI 用例，用户核对并改为「正常运行」即视为采纳" |
| **F2** | **FR-023 要求"指明按哪种定位策略失效"，但 API 响应承载不了** | `contracts/api.md` §3.2 的 `steps[]` 增加 `strategy` / `locator` / `name_attr` 字段，并附字段表说明 |
| **F3 / F6** | **两个执行入口关系未界定**（既有 `/testcase/run` vs 新 `/ui/case/run`） | `contracts/api.md` §1.3 补 ASCII 调用图，明确两者最终调同一执行器、产生同一种结果 |
| **E2** | FR-010（内联兜底 + 提示纳入元素库）无任务 | T031 补"检测到全内联定位时提示建议纳入元素库" |
| **E3** | FR-013（`${}` 引用环境级配置）无任务 | T021 补"`base_url` 与步骤字符串字段走 `Render.render`" |
| **E4** | FR-035（名称超长提示与截断）无任务 | T021（后端截断告警）+ T031（前端提示） |
| **E5** | 就地指引 **U3（无目录就地新建）无任务** | T030 用例列表页补目录就地新建入口 |
| **F4** | FR-011 仍用"草稿…采纳"措辞 | 与 F1 一并改为"UI 用例…处理后才能执行" |
| **F5** | SC-006 基线未量化 | spec 与 quickstart 补基线口径：同一批用例在「内联定位版」与「元素库版」下，因该页面改版而需手动改动的用例条数之比 |
| **D1** | **新增写入通道未全部收紧角色** | `contracts/api.md` §1.2 显式回应：页面/元素保持 `Permission()`（团队协作资产，与既有"创建用例"同级、不扩大权限面）；白名单收紧到 ADMIN（安全边界）；并留出 v2 跨项目共享时需重新评估的说明 |
| **A1** | FR-041 与 FR-008 重复 | FR-008 补"含 FR-041 所述的任意脚本执行"，保留两条（一条是集合原则、一条是安全要求） |
| **F7** | T016 任务描述自相矛盾 | 随 E1 一起重写 |
| **F8** | insert 请求体没写 status | `contracts/api.md` §3.1 补请求字段表 + 显式注明"status 恒为「调试中」" |
| **F9** | FR-040 无任务（实际由 001 承担） | `tasks.md` 依赖章节注明"由 `001-ai-workbench` 的 `TEST_TYPES` 承担" |
| **B1** | 002 的 SC 判定口径与 001 的抽样口径关系不明 | `quickstart.md` §6 补说明：本 feature 的 SC 以客观计数为主、不套用 001 的抽样口径；主观型 SC 仍按 001 §6.2 |

**修复后指标**：总需求 56（44 FR + 12 SC）· 总任务 50 · 覆盖率 100%（FR-001 零覆盖已补，5 条部分覆盖已补任务落点）· CRITICAL 0 · HIGH 0。

# AIFullStackTesting (Pity) Constitution

> Pity 是一套 API 测试平台 monorepo: FastAPI 后端(`backend/`)+ UmiJS 前端(`frontend/`)。
> 本文件约束**所有**在本仓库内的功能设计与实现。

## Core Principles

### I. 确定性优先 (NON-NEGOTIABLE)

凡涉及随机、数据生成、可复现性的实现 MUST 满足:同样的输入 MUST 产出完全一致的结果。

- 引入任何新随机源时, MUST 确认它能被既有的 seed 机制覆盖。**禁止**引入 OS 熵或全局 `random`
  作为未受 seed 控制的随机源(`PityFunction.uuid()` 走 OS 熵,因此不可重放 —— 新代码不得照此实现)
- 若确实无法重放(如取真实时间的函数), MUST 在代码注释与设计文档中**显式标注**该字段不可重放
- 依赖其他字段的派生值, MUST 在**最终值**上做约束判定, 不能在模板/占位符形态上判定

**理由**: 不可重放的数据让"预览"和"实际落地"对不上, 排查时无法复现用户看到的结果。
**检查点**: 同一组输入跑两次, 结果 MUST 逐字段相等(见 `backend/scripts/datafactory_selftest.py` 的 seed 重放断言)。

### II. 复用平台既有机制

优先复用已有的执行链路、连接池、渲染器、鉴权, MUST NOT 自造第二套等价实现。

- 新增机制前 MUST 先调研平台是否已有同类能力
- 已有能力的边界(限制、坑) MUST 查清后再决定复用还是绕开, 而不是凭直觉另写一套

**理由**: 平台存在大量已验证的链路(如 `Executor.run_single` 的数据驱动、`db_helper` 的连接池、
`Render` 的 `${...}` 渲染)。重复实现会让同一语义有两份逻辑, 修 bug 时必然漏改一处。
**实例**: 数据工厂不自造"用例联动", 而是产出数据写进 `pity_testcase_data`, 直接复用已有的数据驱动。

### III. 跨端契约单一出处

前后端共享的常量、枚举、规则表 MUST 有唯一权威定义。MUST NOT 两端各写一份再靠约定保持一致。

- 若技术上无法合并(如后端 Python 常量 + 前端 TS 常量), 两个位置 MUST 互相指认,
  并在 `CLAUDE.md` 中声明"MUST 同步修改两处"
- 新增此类共享常量时, MUST 同步更新两端并补上指认关系

**理由**: 两端各写一份必然漂移, 而漂移不会报错 —— 只会在运行时表现为诡异的静默不一致。
**实例**: `rule.kind` 同时存在于 `backend/app/core/data_factory/generator.py` 与
`frontend/src/consts/datafactory.ts`, 后者注释指向前者, `backend/CLAUDE.md` 声明了同步要求。

### IV. 交互自成闭环

任何弹窗、向导、多步流程 MUST 让用户在**该界面内**完成全部必要选择, MUST NOT 依赖视野外的前置配置。

- 交互所需的数据源若尚未配置, 界面 MUST 在原地给出明确指引(去哪里配), 而不是只报一句"请先选择"
- 前置状态若可以带入, MUST 自动带入, 让用户不必重复填写

**理由**: 藏在界面外的前置条件会让用户卡在第一步, 且不知道该去哪解绑。
**反例**: 数据工厂的「从表结构导入」曾要求先在表单里选好目标库, 用户点击即被拦且提示没说明去哪里填。

### V. 落地前必须过回归

功能改动落地前 MUST 通过自动化验证, MUST NOT 只靠手动点一遍。

- 若该模块没有自动化验证手段, MUST 先补上再落地
- 回归脚本 MUST 覆盖核心链路的端到端路径, 而不只是单元边界

**理由**: 手动点一遍无法在后续改动中重复执行, 也就无法防止回归。本项目已有多次"手动验过、
后续改动悄悄改坏"的教训。
**实例**: `backend/scripts/datafactory_selftest.py`(49 断言)与 `datafactory_e2e.py`(51 断言),
后者含数据驱动端到端验证(绑定 4 条数据 → 执行 4 次 → 校验每条 body 的变量替换)。

## 安全要求

本仓库存在下列安全面, 任何触及它们的改动 MUST 按「安全审查检查点」(`backend/CLAUDE.md`)处理。

- **任意代码执行**: `app/routers/online/script.py`、`app/core/constructor/python_constructor.py` 使用 `exec()`
- **未沙箱模板渲染**: `app/core/render.py` 使用裸 `Environment()` 而非 `SandboxedEnvironment`, 可执行任意表达式
- **凭据明文存储**: `pity_database_info.password`、`pity_ai_vendor.api_key` 以明文列存储
- **数据写入通道**: 数据工厂 `/write-db`、在线 SQL / Redis 客户端可对已配置的数据源执行操作

MUST NOT 在引入新的外部输入面(用户提供的脚本、表达式、正则、上传文件解析)时放宽上述边界。
新增写入通道时, MUST 通过 `Permission(role=...)` 收紧角色, 并对输入做参数化处理, MUST NOT 拼接执行。

## 开发工作流

### 文档分层

- `CLAUDE.md`(每次会话加载) MUST 只放**硬约束 + 指针**, MUST NOT 堆积"要用时才需要"的细节
- 模块拆分、参数表、设计取舍、测试跑法、已知缺口 MUST 下沉到 `backend/docs/<feature>-design.md`
- 常驻上下文的膨胀成本由所有人承担, 每加一段都 SHOULD 问"是否必须每次会话都看到"

### 安全审查触发条件

命中下列任一 MUST 在功能边界提示跑 `security-review`(由人决定是否执行, 不自动跑):

- 新增或改动 `app/routers/` 下的接口(尤其带写操作)
- 引入或改动数据写入通道
- 改动鉴权判断
- 引入新的外部输入面
- 存储新的敏感数据

## Governance

- **本 constitution 优先级最高**, 与代码、文档、既有习惯冲突时以本文件为准
- 修订 MUST 走 `/speckit-constitution`, 并在文件顶部留下 Sync Impact Report 供复核, 提交前删除
- **版本策略**(语义化):
  - MAJOR: 删除或重新定义既有原则(不兼容的治理变更)
  - MINOR: 新增原则/章节, 或实质扩展现有指导
  - PATCH: 措辞澄清、typo、非语义性调整
- **合规审查**: 评审与合并时 MUST 核对本文件; 违反原则的改动 MUST 先修订本文件再落地, 不得默认豁免
- 每次功能落地 SHOULD 在 `backend/docs/<feature>-design.md` 中记录哪些原则影响了设计决策

**Version**: 1.0.0 | **Ratified**: 2026-10-23 | **Last Amended**: 2026-10-23

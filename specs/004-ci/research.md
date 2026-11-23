# Research: 持续集成（外部 CI 对接）

**Feature**: `specs/004-ci` · **Date**: 2026-11-23 · **Phase**: 0

> 调研方式：直接读当前 HEAD 的实际代码（`backend/app/core/executor.py`、`app/routers/__init__.py`、`app/utils/scheduler.py`、`app/handler/fatcory.py`、`app/__init__.py`、`frontend/src/utils/auth.ts`、`config/routes.ts`），不依赖二手摘要。每条决策都标注了否决的备选方案与理由。

---

## D1 凭据存储形式

**Decision**: 存 `sha256(明文)` 等值摘要（无盐），另存 `token_prefix`（前 12 位）仅供界面辨识。校验时对入参取 `sha256` 后**按等值直接查表**，单次查询完成。

**Rationale**:
- 与既有坏味道切割 —— `CLAUDE.md` 安全审查章节把「敏感数据明文存储（`pity_database_info.password`、`pity_ai_vendor.api_key`）」列为既有安全面，新表照抄就是第四处
- **为什么不用 bcrypt/argon2**：慢哈希是为了对抗低熵口令的字典攻击。这里的 token 是 `secrets.token_hex(16)` = **128 bit CSPRNG 熵**，穷举空间 2¹²⁸，慢哈希没有收益却引入依赖与每次校验的 CPU 开销
- **为什么无盐是安全的**：攻击者拿到 DB 里的 `sha256(token)` 后**无法直接当 token 用** —— 服务端校验是 `sha256(入参) == 存储值`，攻击者提交存储值会得到 `sha256(存储值) ≠ 存储值`。也无法反推明文（原像不可行）。所以「摘要 = 等价凭据」的直觉在这里不成立
- **单次等值查询**比「先按 prefix 查、再比对」少一次逻辑分支，且 `token_prefix` 建索引只为列表展示

**Alternatives considered**:
- ❌ **明文存储** —— 直接复制既有坏味道，DB 泄露即凭据泄露，且违反 spec FR-008
- ❌ **bcrypt 加盐** —— 引入新依赖 + 每次调用 ~100ms CPU，对 128 bit 熵的 token 纯属浪费；且加盐后无法单次等值查询，要先查出记录再比对
- ❌ **每记录随机盐 + `sha256(salt‖token)`** —— 比无盐多一层字段与拼接逻辑，收益为零（同上，熵已足够）

---

## D2 鉴权依赖的形态与 header 名

**Decision**: 新增 `CIPermission()` 依赖，**读与 `Permission()` 同名的 `token` header**，按值前缀 `pity_ci_` 分流：有该前缀走 CI 摘要校验，无则按 JWT 语义。**返回结构与 `Permission()` 完全一致**（`user_info` 字典，`create_user` 取凭据的签发人）。

**Rationale**:
- `app/routers/__init__.py:23` `async def __call__(self, token: str = Header(...))` —— 平台既有 header 名就是 `token`（前端 `auth.headers()` 发的也是 `token`）。CI 示例复用同名 header，`curl -H "token: ..."` 与前端写法一致，接入示例更好抄
- **`Permission()` 一行不改** —— 改它等于动全站鉴权，风险面从 8 个接口扩散到全部接口
- 返回结构对齐 → 既有的 `user_info['id']` / `user_info['role']` / `PityResponse.model_to_dict(user, "password")`、`ProjectRoleDao` 项目权限判断全部可直接复用，不造第二套权限模型（GATE-II）

**Alternatives considered**:
- ❌ **新 header 名 `X-Pity-Token`** —— 语义更清晰，但 CI 示例里会出现两套 header 写法，且需要 `CIPermission` 读不同 header；收益不抵「示例更难抄」的代价
- ❌ **让 `Permission()` 内部同时识别 JWT 与 CI token** —— 单一依赖更简洁，但把机器凭据逻辑塞进全站鉴权，任何一处改动都可能波及所有接口；**违背「复用既有机制」的边界感**
- ❌ **复用用户 JWT 当 CI 凭据** —— JWT 有有效期、绑具体用户、可被该用户的所有权限放大；用户离职/改密后流水线直接断。**这是 spec FR-001 要解决的根本问题**

---

## D3 等待语义的实现：超时与断连都不得取消执行

**Decision**: 触发时 `task = asyncio.ensure_future(runner)`，再 `await asyncio.wait({task}, timeout=timeout_sec)`。**不用 `asyncio.wait_for`**。`asyncio.wait` 返回 `(done, pending)`：`task ∈ pending` 即超时，**任务继续在后台跑**，把 `task` 的引用存起来防 GC。

**Rationale**（这是本特性最关键的技术点，直接对应 FR-011 / FR-032）：
- `asyncio.wait_for(coro, timeout)` 超时会**主动 `cancel()` 内部任务**再抛 `TimeoutError` —— 与 FR-011「超时后 MUST NOT 中断仍在进行的执行」**直接冲突**
- `asyncio.wait(tasks, timeout=)` 超时**不取消** pending 任务，只返回它们
- `asyncio.wait` **本身被取消时也不取消被等的任务** —— 所以调用方断连导致 handler 被取消，执行照样继续（FR-032）
- Python 3.10 起向 `asyncio.wait` 传裸协程会 `DeprecationWarning`（3.11 移除），**必须先 `ensure_future` 包成 Task**
- 超时的 `task` 必须保存在模块级强引用集合里，否则事件循环只剩弱引用，任务可能被 GC 中途回收

**Alternatives considered**:
- ❌ **`asyncio.wait_for`** —— 会 cancel，直接违反 FR-011
- ❌ **`asyncio.shield` + `wait_for`** —— shield 能挡住取消，但 `wait_for` 外层超时后仍会 cancel shield 外壳，且要额外处理 `CancelledError` 传播，代码更绕、更易写错
- ❌ **超时后直接 `task.cancel()` 并记超时** —— 违反 FR-011，且用户等了 5 分钟的结果凭空消失
- ❌ **不提供等待模式，只做轮询** —— spec FR-010 明确要求两种语义；Jenkins `sh curl` 场景下轮询要多写脚本，接入成本上升（SC-001 三步限制）

---

## D4 `Executor.run_test_plan()` 的返回值与异常改造

**Decision**: 给 `run_test_plan(plan_id, executor=0, *, raise_on_error=False)` 加**关键字-only** 参数；成功时 `return report_dict`（内含各环境 `plan_result` 与 `report_id`），失败时 `raise_on_error=True` 才上抛、否则保持既有「记日志后返回」语义。

**Rationale**:
- `executor.py:545-576` 现状是 `return None`（成功失败都一样），而它内部 **`await asyncio.gather(...)` 已经等全部环境跑完**，`run_multiple` 也已经 `return report_id` 并填好 `report_dict[env]["plan_result"]` —— **结果算好了却在上一层被丢掉**，补个 return 即可
- 既有两个调用方（`testplan.py:75` 的 `asyncio.create_task(...)`、`scheduler.py` 的 cron job）**都忽略返回值** → 加返回值零影响
- 异常上抛是**行为变更**：`/plan/execute` 与 cron 路径目前是吞异常，改成抛会改变它们的日志与错误路径 → 用 `raise_on_error`（默认 `False`）隔离，**只有 CI 端点传 `True`**（对应 FR-015：区分「测试未通过」与「平台执行失败」）
- 关键字-only（`*`）防止未来有人位置传参把 `executor` 挤掉

**Alternatives considered**:
- ❌ **新写一个 `run_test_plan_for_ci()`** —— 两份执行逻辑必然漂移，违背 GATE-II「MUST NOT 自造第二套等价实现」
- ❌ **直接把异常改成默认上抛** —— 改变 cron 路径行为，`Scheduler` 的 job 会开始抛未捕获异常，影响面不可控
- ❌ **用返回值表达失败（返回 `None` = 失败）** —— 无法区分「测试未通过」与「执行失败」，违反 FR-015

---

## D5 业务结果码 `111` 的接入

**Decision**: 复用既有 `PityResponse.failed(msg, code=110, data=None)` 的 `code` 参数，传 `code=111` 表达「测试未通过」；在 `app/enums/CiEnum.py` 定义常量 `CI_NOT_PASSED = 111`，前端 `src/consts/ci.ts` 镜像。

**Rationale**:
- `app/handler/fatcory.py:88` `def failed(msg, code=110, data=None)` —— `code` 本就是参数，**不需要改响应工厂**
- `111` 紧邻 `110` 递增、落在既有 `0 / 101 / 110` 同区段，符合 `CLAUDE.md`「任何新增业务码遵循同一张表（递增、与现有 0/101/110 同区段），不要混入 200/300/500 这类 HTTP 段」
- **前端零影响**：`auth.ts` 的 `response()` 只认 `code === 0` / `401` / 其余走 `message.error`，而 `111` **只出现在 `/ci/*` 端点**，前端 CI 页面自己处理
- 所有 HTTP 响应仍恒为 200，判定看 body（`CLAUDE.md` 响应协议不变）

**Alternatives considered**:
- ❌ **复用 `110` 表达测试未通过** —— 与「计划不存在」「重复触发」等真实业务异常混在一起，CI 无法区分「测试红了」和「平台报错了」，直接违反 FR-015
- ❌ **用 HTTP 状态码 500/424 表达失败** —— 违反「所有 HTTP 响应都是 200」的平台硬约定，前端与网关都会误判
- ❌ **新增 `200`/`201` 段** —— `CLAUDE.md` 明确禁止混入 HTTP 段

---

## D6 重启后的状态恢复

**Decision**: 在 `app/__init__.py` 的 `lifespan` 增加**第 5 步**（在既有建表之后）：把 `pity_ci_run` 中 `status ∈ (0 pending, 1 running)` 的记录一次性置为 `5 error`，`error_msg` 记「平台重启导致执行中断」。

**Rationale**:
- 单进程部署（gunicorn `-w 1`）意味着**进程重启 = 所有在跑的执行真的没了**，没有别的 worker 接手 → 这些记录若不处理会**永久停在「进行中」**，违反 FR-031，且轮询方会一直等到天荒地老
- 放在 `lifespan` 第 5 步（`create_table()` 之后）是因为必须先建表才能更新；与既有「注册内置 UI 执行节点」同级，启动失败只记日志不拖垮服务
- 标记为 `error`（执行失败）而非 `failed`（测试未通过）—— 语义正确，且与 FR-015 一致

**Alternatives considered**:
- ❌ **不做恢复，靠轮询方自己超时** —— 历史里留下永久「进行中」的脏记录，FR-031 明确要求落终态
- ❌ **恢复成 `success`** —— 说谎，会误导「测试通过了」
- ❌ **定时任务扫描** —— 单进程下启动时扫一次就够，定时扫描是多余的复杂度

---

## D7 并发重复触发的判定

**Decision**: 双重判定 —— ①触发时检查 `pity_test_plan.state == 1`（运行中）→ 拒绝；②`pity_ci_run` 建记录前按 `plan_id + status ∈ (0,1)` 查一次 → 拒绝。两者都过才 `create_task`。

**Rationale**:
- `pity_test_plan.state` 字段（`0 未开始 / 1 运行中`）**已经存在**且 `run_test_plan` 会写它 —— 复用即可（GATE-II）
- 但 `state` 有窗口：计划由 **cron 或手工 `/plan/execute`** 触发时也会置 1，而 CI 只关心「是否已有 CI 触发在跑」→ 所以再加 `pity_ci_run` 自身状态判定，两层分别覆盖「整个计划在跑」与「有一份 CI 执行在跑」
- 判定必须在 `create_task` **之前**同步完成，否则两个并发请求会同时通过检查（TOCTOU）；单进程 asyncio 下，只要判定与建记录之间没有 `await` 切换点，就是原子的 —— 有 `await` 就用「先插 `status=0` 记录、靠唯一约束兜底」的思路

**Alternatives considered**:
- ❌ **只靠 `plan.state`** —— cron 触发的执行也会置 1，CI 会被误拒（虽然语义上「计划正在跑就别重复触发」也说得通，但错误信息会误导用户以为是 CI 的问题）
- ❌ **只靠 `pity_ci_run` 状态** —— 漏掉「计划正被 cron/手工执行」的情况，两个执行会真并发跑同一批用例
- ❌ **分布式锁（Redis）** —— 单进程部署下 `asyncio` 单线程本身就是锁，引入 Redis 锁是过度设计（GATE-II 反对新建机制）

---

## D8 跨端共享常量的权威出处

**Decision**: 新建 `backend/app/enums/CiEnum.py` 作为**权威定义**（业务码 `CI_NOT_PASSED`、执行状态 `RunStatus`、凭据默认有效期、`TOKEN_PREFIX`），`frontend/src/consts/ci.ts` 镜像并注释指认后端；`backend/CLAUDE.md` 与 `frontend/CLAUDE.md` 各补一条「MUST 同步修改两处」。

**Rationale**: 与 `rule.kind`（`data_factory/generator.py` ↔ `consts/datafactory.ts`）、`ACTIONS`/`STRATEGIES`（`ui_executor.py` ↔ `consts/uiTest.ts`）、`MockEnum`（`MockEnum.py` ↔ `consts/mock.ts`）完全同款，是 GATE-III 的既有落地范式。**两端各写一份必然漂移且不会报错**。

**Alternatives considered**:
- ❌ **只在前端写一份** —— 前端展示的状态色与后端判定的状态值一旦漂移，历史列表会把「执行失败」渲染成「通过」
- ❌ **运行时从后端拉枚举** —— 多一次请求、首屏依赖接口，且这些是编译期常量，没有运行时变化的理由

---

## D9 回调地址字段的一期落地方式

**Decision**: `pity_ci_integration.callback_url` 字段**一期就建**，但**任何代码路径都不读它发送**（只在 CRUD 里存取展示）。`data-model.md` 与 `ci_selftest.py` 的源码静态扫描断言：一期源码中不存在对 `callback_url` 的出网调用。

**Rationale**:
- 决定 Q1 已拍板「允许内网 + 项目级 host 白名单 + 仅管理员配置」，Q5 拍板「一期不发」 → 字段先建避免二期加列的迁移，**但绝不能留半截出网代码**
- 一期零出网是 GATE-SEC 的核心断言（源码中无 `aiohttp`/`httpx`/`requests`）
- 二期的 SSRF 矛盾（内网 Jenkins vs `is_blocked_ip`）已在 `proposal.md` §7.2 记录为**开工前必须决策项**

**Alternatives considered**:
- ❌ **一期连字段都不建** —— 二期要 `alembic` 迁移或 `create_all` 之外的手工加列，成本更高
- ❌ **一期就实现回调** —— Q5 明确否决；且 SSRF 取向未落地成机制就发请求，等于新开一个出网面

---

## D10 接入示例的凭据呈现策略

**Decision**: `SnippetsPanel` 展示的片段里，凭据位置是**固定占位符**（如 `YOUR_PITY_CI_TOKEN`），页面顶部给出「去集成配置里复制凭据」的锚点跳转。**完整凭据只在签发成功的那一个弹窗里出现一次**，此后任何地方（列表、示例、日志）都不再回显。

**Rationale**:
- 对应 FR-002 / FR-027，也对应 SC-007「平台存储与日志中完整凭据明文出现次数为 0」
- 示例片段是**要被粘进 Git 仓库**的 —— 若把真实凭据填进去，等于教用户把凭据提交进代码库，这是最常见的凭据泄露路径
- 平台地址与计划名**可以**自动填（它们不是秘密），只有凭据占位

**Alternatives considered**:
- ❌ **示例里填真实凭据「方便一键可用」** —— 用户粘贴即泄露进 Git 历史，危害远大于省一次复制
- ❌ **示例里完全不填任何值** —— 违反 FR-027「自动填入平台地址与计划名」与 SC-001「三步内完成」

---

## 汇总

| # | 决策 | 关联 FR | 关联门禁 |
|---|---|---|---|
| D1 | `sha256` 等值摘要存凭据 | FR-002/008/024 | GATE-SEC |
| D2 | `CIPermission()` 读同名 `token` header，返回结构对齐 `Permission()` | FR-001/005/016 | GATE-II / GATE-SEC |
| D3 | `asyncio.wait` 而非 `wait_for`（超时与断连都不取消） | FR-011/032 | GATE-I |
| D4 | `run_test_plan` 补 return + `raise_on_error`（默认关） | FR-013/015 | GATE-II |
| D5 | 业务码 `111` 走 `PityResponse.failed(code=)` | FR-014/015 | GATE-III |
| D6 | lifespan 第 5 步恢复残留 running 记录 | FR-031 | GATE-IV |
| D7 | `plan.state` + `ci_run.status` 双重防重 | FR-017 | GATE-II |
| D8 | `CiEnum.py` 权威 + `consts/ci.ts` 镜像 | FR-013/023 | GATE-III |
| D9 | `callback_url` 只存不发 + 静态扫描断言 | Assumptions | GATE-SEC |
| D10 | 示例片段凭据用占位符 | FR-002/027 | GATE-SEC |

**未解决的 NEEDS CLARIFICATION**：无（0 条）。

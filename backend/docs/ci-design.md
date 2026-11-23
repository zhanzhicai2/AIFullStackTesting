# 持续集成（CI）· 深设计附录

> constitution「文档分层」指定的落点 —— 模块拆分、参数表、设计取舍、测试跑法、已知缺口。
> 权威顺序：契约（`specs/004-ci/contracts/api.md`）> 数据模型 > 任务 > **本附录**。
> **本附录与契约冲突时以契约为准。**

**特性**：`specs/004-ci/`（spec 33 FR / 12 SC · plan · research D1~D10 · data-model · quickstart · tasks 51 项）
**状态**：一期 T001~T051 全部落地，`ci_selftest.py` 107 项 + `ci_e2e.py` 全绿

---

## 1. 模块拆分

```
backend/
├── app/enums/CiEnum.py                  权威常量(业务码 111/112、RunStatus 六态、凭据前缀与上限)
├── app/models/ci.py                     2 张表: pity_ci_integration / pity_ci_run
├── app/schema/ci.py                     Pydantic v1 表单(集成 CRUD + 触发请求)
├── app/crud/ci/CiIntegrationDao.py      凭据签发/校验链/启停/删除(纯函数 + 带库两层)
├── app/crud/ci/CiRunDao.py              触发记录写入/回填/分页/防重/终态恢复
├── app/core/ci_runner.py                编排: 防重 → 建记录 → 执行 → 回填
├── app/routers/ci/
│   ├── __init__.py                      统一加 prefix="/ci"(子模块不带, 与 ui/ 同款)
│   ├── integration.py                   5 个凭据管理端点, Permission(Config.MANAGER)
│   └── run.py                           3 个触发/查询端点, CIPermission
├── app/routers/__init__.py              【改】新增 CIPermission(双模)
├── app/core/executor.py                 【改】run_test_plan 补返回值 + raise_on_error + 空列表防护
├── app/__init__.py                      【改】lifespan 第 5 步终态恢复
└── scripts/{ci_selftest,ci_e2e}.py      回归双脚本

frontend/
├── config/routes.ts                     【改】/ci → './ci', authority 收紧
├── src/consts/ci.ts                     CiEnum 的前端镜像
├── src/services/ci.ts                   8 个端点封装
├── src/models/ci.ts                     hooks 风格 model(一次性明文状态)
└── src/pages/ci/                        index / IntegrationPanel / SnippetsPanel / RunHistoryPanel
```

**对既有代码只改 3 处**（`executor.py`、`app/__init__.py`、`routes.ts`）+ `main.py` 注册 + `routers/__init__.py` 加依赖。**报告链路零改造**，`pity_report` / `pity_test_result` 表结构一字未动。

---

## 2. 凭据存储与校验链（本特性最关键）

**决策 D1**：存 `sha256(明文)` **无盐等值摘要**，另存 `token_prefix`（前 12 位）仅供展示。

**为什么不用 bcrypt**：token 是 `secrets.token_hex(16)` = 128 bit CSPRNG 熵，慢哈希没有收益却引入依赖与每次校验的 CPU 开销。

**为什么无盐是安全的**（这段论证容易被质疑，留档）：服务端校验是 `sha256(入参) == 存储值`。攻击者拿到 DB 里的摘要后**无法直接当 token 用** —— 提交摘要会得到 `sha256(摘要) ≠ 存储值`；也无法反推明文（原像不可行）。所以「摘要 = 等价凭据」的直觉在这里不成立。

**校验链**（`CiIntegrationDao.check_credential` 是纯函数，可无 DB 单测）：

```
1. token 以 pity_ci_ 开头              否 → "CI 凭据无效"
2. sha256(token) == token_hash          否 → "CI 凭据无效"   ← 摘要比对放最前,
3. deleted_at == 0                      否 → "CI 凭据无效"      避免把「存在但已停用」
4. enabled == 1                         否 → "CI 凭据已停用"    泄露给没有有效凭据的人
5. expires_at IS NULL OR > now()        否 → "CI 凭据已过期"
7. 更新 last_used_at(尽力而为, 失败不拒)
```

第 6 步「项目作用域」在路由层做 —— 目标 `plan_id` 在请求体里，依赖拿不到。

**`token_prefix` 绝不参与校验** —— 只比前缀就放行是最容易写错的实现，`ci_selftest` 有专门断言。

**明文只出现一次**：`POST /ci/integration/insert` 是全站唯一返回 `token` 的地方；`list` / `update` / `switch` / `delete` 一律 `model_to_dict(..., "token_hash")`。

---

## 3. 等待语义：`asyncio.wait` 而不是 `wait_for`（决策 D3）

**这是本特性最关键的技术点**，直接对应 spec FR-011 / FR-032：

| | 超时行为 | 自身被取消时 |
|---|---|---|
| `asyncio.wait_for(coro, timeout)` | **主动 `cancel()` 内部任务**，再抛 `TimeoutError` | —— |
| `asyncio.wait({task}, timeout=)` | 只返回 pending，**不取消** | **也不取消被等的任务** |

所以：
- FR-011「超时后执行继续完成」→ 只能用 `wait`
- FR-032「调用方断连不取消执行」→ `wait` 被取消时任务照样跑

配套约束：
- Python 3.10+ 向 `wait` 传**裸协程**是 `DeprecationWarning`（3.11 移除）→ 必须先 `asyncio.ensure_future` 包成 Task
- 超时后的 Task 必须有**强引用**：事件循环只持弱引用，不留住会被 GC 中途回收 → `_REFS` 字典 + `add_done_callback` 摘除
- `ci_selftest` 有源码断言：`ci_runner.py` 里 `asyncio.wait(` 存在、`asyncio.wait_for(` **不存在**

---

## 4. 执行语义：`run_test_plan` 的三处改动（决策 D4）

```python
async def run_test_plan(plan_id, executor=0, *, raise_on_error=False) -> dict | None
```

1. **补 `return report_dict`** —— `run_multiple` 早就把 `report_id`、`plan_result` 算好了，却在上一层被丢掉
2. **`raise_on_error` 关键字开关，默认 `False`** —— cron 与 `/testcase/plan/execute` 两个既有调用方行为一字不变；只有 CI 端点传 `True`，用来区分「测试未通过」与「平台执行失败」（FR-015）
3. **通知单独一段 try** —— 用例已经跑完，邮件/钉钉/websocket 发送失败**不该把一次成功执行判成平台失败**（否则 CI 会把绿的构建拦红）
4. **空列表防护**：`"".split(",")` 得到 `[""]`，直接 `int("")` 会 `ValueError` → 计划被清空用例时应当走「空计划 → 判未通过」（FR-018），而不是抛异常

**`None` 的含义**：计划不存在，或 `@lock("test_plan")` 分布式锁没抢到（同 `(plan_id, executor)` 已有执行在跑）。**CI 侧把 `None` 当作「未启动」处理，绝不当成「执行成功」** —— 这正是原实现里「静默吞」最危险的形态。

---

## 5. 状态机与重启恢复

```
0 pending ──▶ 1 running ──┬──▶ 2 success   全部用例通过且 total > 0
                │         ├──▶ 3 failed    有失败/异常, 或空计划(FR-018)
                │         ├──▶ 4 timeout   等待超时, 任务仍在跑(回填后通常变 2/3)
                │         └──▶ 5 error     执行抛异常 / 平台重启中断
                └──▶ 5 error               记录建好但计划校验失败
```

**`3` 与 `5` 必须可区分**（FR-015 / SC-006）：`3` = 测试红了，`5` = 平台坏了。前端文案与 Tag 颜色都不同（`consts/ci.ts` 的 `CI_RUN_STATUS_LABELS` / `COLORS`）。

**重启恢复**（`app/__init__.py` lifespan 第 5 步，FR-031）：单进程部署（gunicorn `-w 1`）下，进程重启 = 所有在跑的执行真的消失。启动时把 `status ∈ (0,1)` 一次性收敛为 `5 error`，`error_msg = 平台重启导致执行中断`。放在 `create_table()` **之后**（必须先有表），失败只 `startup.exception` 不抛，不拖垮启动。

**防重双层**（FR-017，research D7）：
1. `pity_test_plan.state == 1` → 计划正被 cron / 手工执行
2. `CiRunDao.find_in_flight(plan_id)` → 已有一份 CI 执行在跑

窗口内的残余并发由 `Executor.run_test_plan` 自带的 `@lock("test_plan")` Redis 锁兜底 —— 抢不到锁返回 `None` → `status=5`「执行未能启动」。

---

## 6. 鉴权：`CIPermission` 是双模（实现期修正）

**原设计只认 CI 凭据**，实现时发现：`/ci/run/{id}` 与 `/ci/run/list` 同时服务两端 —— 外部 CI 轮询结果、平台用户看触发历史。只认凭据的话前端发 JWT 一律 401，**历史页永远是空的**，spec US3 无法交付。

| 调用方 | `token` header | 分支 |
|---|---|---|
| 外部流水线 | `pity_ci_...` | 凭据校验链（§2） |
| 平台管理员 | JWT | **直接调用 `Permission(Config.MANAGER)`**，不重复实现 JWT 解析 |

- **`Permission()` 本体一行不改**（research D2）—— 它被全站依赖，改它风险从 8 个接口扩散到全部接口
- 返回结构是 `Permission()` 的**超集**：多一个 `ci_integration` 键（凭据路径为 `{id, project_id, plan_id, name}`，JWT 路径为 `None`）
- **`POST /ci/run` 只接受 CI 凭据** —— JWT 调用返回 `401`。若允许管理员点按钮触发，`pity_ci_run` 的「谁触发的」就失去溯源意义

---

## 7. 脱敏与安全边界（GATE-SEC）

| 数据 | 落库 | 落日志 | 界面 |
|---|---|---|---|
| 凭据明文 | ❌ 永不 | ❌ 永不 | 仅签发弹窗一次 |
| `token_hash` | ✅ | ❌ | ❌ |
| `token_prefix` | ✅ | ✅ | ✅ 列表 |
| `external_build_id` | ✅ | ✅ | ✅ |
| `external_url` | ✅ | ✅ 过 `log_sanitize` | ✅ 可跳 |
| `error_msg` | ✅（≤500） | ✅ | ✅ |

**一期零出网**（决定 Q5）：`callback_url` 字段建了但**任何代码路径都不读它发送**。`ci_selftest` 两道机器可验证断言：
- CI 模块 AST 扫描：无 `aiohttp` / `httpx` / `requests` / `urllib.request` / `socket`，无 `eval` / `exec`
- 源码扫描：`callback_url` 所在行不得出现 `post/get/put/request/send/fetch/urlopen(`

**不新增执行面**、**不改 `app/core/render.py`**、**不动 `pity_report` 表结构**。

---

## 8. 测试跑法

```bash
cd backend
.venv/bin/python scripts/ci_selftest.py      # 107 项, 不依赖 DB
.venv/bin/python scripts/ci_e2e.py           # 依赖 DB(dev 库), 全链路
.venv/bin/python -c "import main"            # 导入无误

cd ../frontend
nvm use && ./node_modules/.bin/tsc -p tsconfig.json --noEmit   # 0 错误
npm run lint
```

**`ci_selftest`（107 项）覆盖**：凭据校验链正反例（含「前缀命中但摘要不符」）、凭据格式与明文约束（表里没有 `token` 列）、业务码七档、`RunStatus` 六态与 3/5 分离、schema 边界、`run_test_plan` 返回值与开关的源码断言、`ci_runner` 用 `wait` 不用 `wait_for`、lifespan 恢复位置、`CIPermission` 双模、`Permission()` 未被改动、表结构约束、AST 静态扫描、跨端常量核对、**示例片段凭据占位符**。

**`ci_e2e` 覆盖**：签发 → 列表无明文 → 校验链四类拒绝（走真实 `CIPermission` 依赖）→ 越权 403 → 计划不可用 110 → `wait=false` 受理+轮询 → `wait=true` 单次 111 → 空计划 111「计划为空」→ 重复触发 110 → 并发只执行一次 → 历史分页/隔离/双模鉴权 → 重启恢复幂等 → 1000 条分页 < 1 秒。

> **e2e 用「不存在的用例 id」制造确定性失败** —— 执行走「执行异常」分支，**不发任何网络请求**，结果可预期。

---

## 9. 已知限制与缺口

- **一期无回调 webhook**（决定 Q5）：结果只能等返回或轮询，不会主动推回流水线
- **回调 SSRF 与内网 Jenkins 的矛盾未解**（`proposal.md` §7.2）—— 二期开工前必须先决策「项目级 host 白名单 + 仅管理员配置」还是别的取向。**这条不定，二期不要开工**
- **`POST /ci/run` 没有并发上限**（安全审查 F2，**已知风险、未强制执行**）：
  全站本就没有任何限流（grep `limiter|rate_limit|slowapi|throttle` 零命中），`/testcase/plan/execute`
  早就允许任意 MEMBER 无限制触发计划执行 —— 所以这不是本次新引入的形态，但 CI 这条入口**每次触发都真的执行测试计划**
  （出网打被测系统 + 写 `pity_report`/`pity_test_result`），`wait=true` 时 `timeout_sec` 上限 **1800s**，
  测试计划执行链路没有并发上限（`BrowserManager._semaphore` 只管 UI 浏览器）。
  **已有的缓解**：同计划防重（`find_in_flight` + `@lock("test_plan")`）—— 同一 plan 不会并发跑两份，
  但**不同 plan 可以无限并发**。
  **待决策**（三选一，尚未实施）：① `ci_runner` 加全局/每凭据 `asyncio.Semaphore` ② 按 integration 限流
  ③ 仅文档标注（**当前选择**，避免给已跑通的功能引入新的失败模式）。
  走 ①/② 时要注意：信号量满要返回可区分的业务码，不能让 CI 拿到一个含糊的 `110`。
- **`pity_test_plan.pass_rate` 仍只写不读** —— 全仓库除 model/schema 外无人引用，「通过率低于阈值自动通知/门禁」从未实现。二期接上它就能做门禁
- **执行结果不可重放** —— 测试结论取决于被测系统状态，同一 `plan_id` 两次触发结果可能不同（与既有接口/UI 自动化同源约束）
- **凭据粒度是项目级** —— 不提供「只允许触发单条计划」的更细限制（绑定默认计划只是引导，不强制）
- **`GET /ci/integration/switch` 与 `/delete` 走「先按 id 查归属项目再操作」** —— 比直接收 `project_id` 多一次查询，换来契约只暴露 `id`
- **摘要比对非恒定时间** —— `token_hash != compute_hash(token)` 走普通字符串比较。但调用方必须先通过 DB 的 `token_hash = ?` 等值查询（本身也非恒定时间），且凭据是 128 bit 熵，时序攻击不可行。列为 informational，不修

---

## 10. 实现记录（与设计的偏差）

| 项 | 设计 | 实际 | 原因 |
|---|---|---|---|
| `CIPermission` | 只认 CI 凭据 | **双模**（CI 凭据 / 管理员 JWT） | 只认凭据会让前端历史页永远 401，US3 无法交付（§6） |
| 业务码 `112` | `proposal.md` §9 只批了 `111` | **新增 `112` 等待超时** | FR-011 要求超时与业务异常可区分，否则 CI 无法决定「再轮询」还是「放弃」 |
| `run_multiple.report_dict` | 不含 `report_id` | **加了 `report_id` 键** | `report_ids` 列要存报告 id；两个既有消费者（邮件/钉钉）都是 `**kwargs`，加键零影响 |
| `run_test_plan` 通知段 | 单个 try | **拆成独立 try** | 通知失败不该把已跑完的执行判成平台失败（§4） |
| `run_test_plan` 列表解析 | `map(int, x.split(","))` | **过滤空串** | `int("")` 会 ValueError，空计划必须走 FR-018 而不是抛异常 |
| `/run/{id}` 与 `/run/list` | 未规定顺序 | **list 定义在 `{id}` 之前** | FastAPI 按注册顺序匹配，否则 `list` 被当成 run_id 捕获 |

---

## 11. 安全审查记录（2026-11-23，T051）

用 ECC `security-review` 10 项清单跑了一遍（§9 区块链不适用）。**结论：无高危、无阻断；4 项需修已修，1 项为已知风险。**

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| F1 | 中 | `external_url` 无 scheme 校验 → 存储型链接注入。该值由调用方提供、被 `RunHistoryPanel` 渲染成 `<a href>`；React 18 对 `javascript:` href **只在 dev 打 warning、不阻断** | ✅ **已修**：`schema.check_url_field()` 白名单 + 前端 `isSafeHttpUrl()` 纵深双层 |
| F2 | 中低 | `POST /ci/run` 无并发上限，每次触发真的执行测试计划（出网 + 写库），`timeout_sec` 上限 1800s | ⚠️ **仅文档标注**（§9）——全站本就无限流，走信号量/限流需先定方案，避免给已跑通的功能引入新失败模式 |
| F3 | 低 | `error_msg` 文档称「已脱敏」但 `clip_error` 只截断 → 异常文本可能带出 URL query / `password=` 片段 | ✅ **已修**：先 scrub（URL query → `?***`、凭据 KV → `key=***`、含 `Bearer <jwt>`）再截断到 500 |
| F4 | 低 | `callback_url` 无 scheme 校验 —— 一期不发，但二期一开就是现成入口 | ✅ **已修**：同一白名单，一期就上 |
| F5 | 加固 | `token_hash` 不进操作日志是**隐性**保护（靠 `__fields__` 过滤），将来加进 `__fields__` 会静默泄露 | ✅ **已修**：`models/ci.py` 的 `__fields__` 旁写明该依赖 |

**通过项**：零硬编码凭据 · 全 SQLAlchemy 绑定参数（无裸 SQL）· `Permission()` 本体未改 · 项目作用域三处强制 · JWT/CI 凭据都在自定义 header（非 cookie，CSRF 不适用）· 请求头不进日志（`request_info` 只记 method + `sanitize_url` + `sanitize_payload(body)`，而凭据在 header 里）· 零新增依赖 · 零执行面 · 一期零出网。

**回归门禁**：以上 5 项全部固化进 `scripts/ci_selftest.py::test_security_review_fixes`（25 条断言），改回去会直接红。

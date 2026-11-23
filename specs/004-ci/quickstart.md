# Quickstart: 持续集成（外部 CI 对接）

**Branch**: `004-ci` | **Date**: 2026-11-23 | **Spec**: [spec.md](./spec.md)

> 本文件是**验证/运行指南**，不含实现代码。接口结构见 [`contracts/api.md`](./contracts/api.md)，表结构与状态机见 [`data-model.md`](./data-model.md)。

## 1. 环境准备

```bash
# 后端依赖(MySQL + Redis;Redis 可关)
cd backend/ops && docker-compose up -d && cd ../..

# 后端(0.0.0.0:7777)
cd backend && .venv/bin/python pity.py

# 前端(Node 20 —— nvm use 必须与启动写同一条命令)
cd frontend && nvm use && npm run start:dev     # localhost:8000
```

**建表**：`pity_ci_integration` / `pity_ci_run` 由 SQLAlchemy `create_all` 在 lifespan 第 3 步自动创建（与 001/002/003 同款）；若走 alembic 则 `alembic revision --autogenerate -m "ci integration & run" && alembic upgrade head`。

**前置数据**（G3 是硬前置）：
1. 一个项目（`project_id` 记为 `P`）
2. 项目 `P` 下至少一条测试计划（`plan_id` 记为 `PLAN`），且该计划里至少有 1 条用例 —— **空计划会返回 `111 计划为空，无法判定`**（FR-018）
3. 一个 `admin` / `superAdmin` 账号（签发凭据需要 `MANAGER` 及以上）

## 2. 回归命令（GATE-V 门禁，三步全绿才算完）

```bash
cd backend
.venv/bin/python scripts/ci_selftest.py      # 不依赖 DB
.venv/bin/python scripts/ci_e2e.py           # 依赖 DB
.venv/bin/python -c "import main"            # 导入无误

cd ../frontend && npx tsc --noEmit           # 0 错误
npm run lint                                 # ESLint + Prettier + tsc
```

**`ci_selftest.py` 必须覆盖**（对应 `proposal.md` T07）：
- 凭据摘要校验链正反例（`pity_ci_` 前缀 / 摘要不匹配 / 已停用 / 已过期 / 已删除 / 跨项目）
- 业务码映射：`0` 通过、`111` 未通过、`112` 超时、`110` 业务异常、`401`/`403`
- `RunStatus` 六态齐全且 `3`（测试未通过）与 `5`（执行失败）**不混淆**
- `run_test_plan` 返回结构的源码静态断言（有 return、有 `raise_on_error` 开关且默认 `False`）
- **源码静态扫描**：①无明文凭据落库（不存在把 `token` 原文写入列的代码）②一期无出网调用（无 `aiohttp`/`httpx`/`requests`）③无 `exec`/`eval` ④等待用 `asyncio.wait` 而非 `wait_for`（后者会 cancel，违反 FR-011）
- `test_security_boundaries` 类的边界断言：四条安全相关断言一条都不能删

**`ci_e2e.py` 必须覆盖**（对应 `proposal.md` T09）：签发 → 触发 → 轮询到终态 → 记录字段完整 → 报告入口可跳 → 拒绝类（停用/过期/越权/重复触发）。

## 3. 端到端场景

### 场景 A：签发凭据 → 触发 → 通过

1. 登录 → 进入「持续集成」菜单（`/#/ci`，**不再是占位页**）
2. 选择项目 `P` → 出现 G2 空态「新建集成」（若同时无计划则 G2+G3 并列，**先建计划**）
3. 「新建集成」：名称 `Jenkins-main`，绑定计划 `PLAN`，有效期用默认 1 年
4. 弹窗展示一次性凭据 → **点复制**，关掉后列表只剩 `pity_ci_xxxx` 前缀
5. 切到「接入示例」tab → 复制 GitHub Actions 片段（`plan_id` 已自动填）
6. 用真实凭据触发：

```bash
curl -s -X POST "http://localhost:7777/ci/run" \
  -H "token: pity_ci_<刚复制的>" -H "Content-Type: application/json" \
  -d '{"plan_id": PLAN, "external_build_id": "42", "wait": true, "timeout_sec": 300}'
# 期望: {"code":0,"msg":"测试通过","data":{"run_id":N,"status":2,"pass_rate":100,"report_ids":[...]}}
```

7. 切到「触发历史」→ 出现该条记录，外部构建号 `42` 可跳、报告入口可进既有报告页

**期望**：`code = 0`，`data.status = 2`，历史里 1 条 `通过`。

### 场景 B：测试未通过 → `111` 阻断

把 `PLAN` 里某条用例的断言改成必失败，重复场景 A 步骤 6。

**期望**：`{"code":111,"msg":"测试未通过（失败 N / 异常 M）","data":{"status":3,...}}` —— 流水线据此 `exit 1`。
历史里该条为**红 · 未通过**，与场景 E 的**灰 · 执行失败**颜色文案都不同（SC-006）。

### 场景 C：不等待 + 轮询（决定 Q3 默认姿势）

```bash
# 立即返回
curl -s -X POST ".../ci/run" -H "token: ..." -H "Content-Type: application/json" \
  -d '{"plan_id": PLAN}'
# 期望: {"code":0,"msg":"已受理，正在执行","data":{"run_id":M,"status":0,"waited":false}}

# 轮询到终态
curl -s ".../ci/run/M" -H "token: ..."
# 期望: status 由 0/1 变为 2 或 3,其余字段回填齐全
```

### 场景 D：等待超时 → `112`（FR-011）

挑一条耗时 > 10 秒的计划，触发时 `wait=true, timeout_sec=5`。

**期望**：
- `code = 112`，`msg` 提示「执行仍在继续」，`data.wait_timeout = true`，`data.run_id` 可用
- **执行不被中断** —— 用 `GET /ci/run/{id}` 继续轮询，最终落到 `2` 或 `3`
- 这是 `asyncio.wait` 而非 `asyncio.wait_for` 的直接验证（后者会 cancel，selftest 有源码断言）

### 场景 E：拒绝类（FR-016，逐条都要能区分）

```bash
# 1. 停用后
curl -s ".../ci/integration/switch?id=1&status=false" -H "token: <web JWT>"
curl -s -X POST ".../ci/run" -H "token: pity_ci_..." -d '{"plan_id":PLAN}'
# → 401 "CI 凭据已停用"

# 2. 改 expires_at 到过去 → 401 "CI 凭据已过期"
# 3. 随机串        → 401 "CI 凭据无效"
# 4. 用项目 P 的凭据触发项目 Q 的计划 → 403 "无权触发该项目的测试计划"
# 5. plan_id 指向不存在的计划        → 110 "测试计划不存在或已删除"
# 6. 同一计划执行中再次触发           → 110 "该测试计划已有执行在进行中"
# 7. plan_id 省略且凭据未绑定计划     → 110 提示需指定计划
```

**期望**：六种情形 `code`/`msg` 各不相同，且**都不回显任何凭据内容**。

### 场景 F：权限与页面（FR-028 / FR-029）

1. 用普通 `user` 账号访问 `/#/ci` → 集成配置区不可见/不可操作，签发接口返回 403
2. 新项目（无计划、无集成、无记录）→ **G1~G4 四态指引并列**，按「先计划、后凭据」排序，每条都有可点入口
3. 刷新列表 → 完整凭据不再出现（FR-002）

### 场景 G：重启恢复（FR-031）

1. 手工把一条记录 `status` 改成 `1`（模拟中断）
2. 重启后端
3. **期望**：该记录变为 `status = 5`，`error_msg = 平台重启导致执行中断`，不再永久「进行中」

## 4. 验收对照（spec 成功标准）

| SC | 怎么验 |
|---|---|
| SC-001 三步内复制出片段 | 场景 A 步骤 2→4→6 |
| SC-002 十分钟跑通 | 场景 A 全程计时 |
| SC-003 结束后 5 秒内可读 | 场景 A/C 计时 |
| SC-004 一次返回即可判定 | 场景 A 单次 `curl` |
| SC-005 记录完整率 100% | `ci_e2e` 断言每次触发都有记录 + 报告入口 |
| SC-006 未通过 vs 执行失败可区分 | 场景 B vs 场景 G，`status` 与前端文案 |
| SC-007 明文出现次数 0 | `ci_selftest` 源码扫描 + 场景 F 步骤 3 |
| SC-008 拒绝率 100% 且原因可分 | 场景 E 六条 |
| SC-009 历史 1 秒内返回 | 造 1000 条记录后 `ci_e2e` 计时 |
| SC-010 并发重复触发 0 次成功 | `ci_e2e` 并发打同一 `plan_id` |
| SC-011 回归可重复全绿 | §2 三步命令 |
| SC-012 只凭页面示例完成接入 | 场景 A 步骤 5→6 全程不看文档 |

## 5. 已知限制（实现后回填）

- **一期无回调**（决定 Q5）：结果只能等返回或轮询，不会主动推回流水线
- **执行结果不可重放**：测试结论取决于被测系统状态，同一 `plan_id` 两次触发结果可能不同（与既有接口/UI 自动化同源约束）
- **`callback_url` 只存不发**：`ci_selftest` 源码扫描保证一期零出网
- 单进程部署：长耗时等待不占 HTTP 连接（纯 `await`），但执行本身与其它请求共享同一事件循环

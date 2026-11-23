# Data Model: 持续集成（外部 CI 对接）

**Branch**: `004-ci` | **Date**: 2026-11-23 | **Spec**: [spec.md](./spec.md)

## 1. 概览

本特性新增 **2 张表**：`pity_ci_integration`（项目级接入凭据）与 `pity_ci_run`（一次外部触发的完整生命周期）。

**不改动**的既有表：`pity_test_plan`（只读消费其 `state` 做防重）、`pity_report` / `pity_test_result`（只引用其入口）、`pity_project`（只按 `project_id` 归属）。报告链路零改造 —— 与 002 / 003 同款取舍。

**无随机可重放性问题**：本特性不涉及数据生成。唯一的随机源是凭据生成（`secrets.token_hex(16)`），按 constitution 原则 I 的豁免条款**显式标注为不可重放（安全属性，非缺陷）** —— 见 §2.2 不变量。

## 2. 表结构

### 2.1 `pity_ci_integration`（接入凭据）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INT | PK | 平台通用 |
| `project_id` | INT | NOT NULL, index | 归属项目，**凭据作用域边界**（FR-005） |
| `name` | VARCHAR(32) | NOT NULL | 集成名，如 `Jenkins-main`、`GH-Actions-prod` |
| `token_hash` | CHAR(64) | NOT NULL, **unique** | `sha256(明文)` 十六进制小写，64 字符。**绝不存明文**（FR-008） |
| `token_prefix` | VARCHAR(12) | NOT NULL, index | 明文前 12 位，仅用于列表辨识与排障（FR-002） |
| `plan_id` | INT | 可空, index | 绑定的默认测试计划（FR-006）；为空则调用方必须显式指定 |
| `callback_url` | VARCHAR(255) | 可空 | **一期只存不发**（决定 Q5）；二期回调地址，见 §6 |
| `enabled` | BOOLEAN | NOT NULL, 默认 `1` | 停用即吊销，立即生效（FR-003） |
| `expires_at` | TIMESTAMP | 可空 | 为空 = 长期有效（决定 Q4）；默认签发时写 `now + 1 年` |
| `last_used_at` | TIMESTAMP | 可空 | 最近一次**校验通过**的时间（FR-007） |

平台通用字段（`PityBase`）：`created_at` / `updated_at` / `deleted_at`（BIGINT 逻辑删除）/ `create_user`（签发人 = 凭据的执行人）/ `update_user`。

**唯一约束**：
- `token_hash` 全表唯一 —— 兜底防止摘要碰撞导致的凭据混淆（实际碰撞概率可忽略，但约束成本为零）
- `project_id + name + deleted_at` 唯一 —— 同项目下集成名不重复，便于排查（与 `pity_test_plan` 同款）

**索引**：`project_id`（列表按项目查）、`token_hash`（**校验路径的唯一查询**）、`token_prefix`（列表展示排序）

### 2.2 `pity_ci_run`（触发记录）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INT | PK | **执行标识**，即 FR-012「唯一可查询的执行标识」 |
| `integration_id` | INT | NOT NULL, index | 触发所用的集成配置 |
| `project_id` | INT | NOT NULL, index | 冗余自集成配置，**供分页查询免 join**（FR-022） |
| `plan_id` | INT | NOT NULL, index | 实际执行的测试计划 |
| `env` | VARCHAR(64) | NOT NULL | 实际执行的环境 id 列表（逗号分隔，与 `pity_test_plan.env` 同格式） |
| `external_build_id` | VARCHAR(64) | 可空 | 调用方传入的外部构建号（如 Jenkins `$BUILD_NUMBER`）（FR-021） |
| `external_url` | VARCHAR(255) | 可空 | 调用方传入的流水线地址，历史中可跳转（FR-021） |
| `status` | SMALLINT | NOT NULL, index, 默认 `0` | 0 pending / 1 running / 2 success / 3 failed / 4 timeout / 5 error（FR-023） |
| `report_ids` | TEXT | 可空 | 本次产生的 `pity_report.id` 列表（JSON 数组字符串），多环境多条 |
| `success_count` | INT | 默认 0 | 通过用例数 |
| `failed_count` | INT | 默认 0 | 失败用例数 |
| `error_count` | INT | 默认 0 | 异常用例数 |
| `skipped_count` | INT | 默认 0 | 跳过用例数 |
| `pass_rate` | SMALLINT | 默认 0 | `success / total * 100`，整数（total 为 0 时不计算，见 §4） |
| `error_msg` | VARCHAR(500) | 可空 | `status=5` 时的失败原因，**已脱敏**（§5） |
| `started_at` | TIMESTAMP | 可空 | 开始执行时间 |
| `finished_at` | TIMESTAMP | 可空 | 结束时间 |
| `cost` | VARCHAR(8) | 可空 | 耗时秒数，格式与 `pity_report.cost` 一致（`%.2f`） |
| `waited` | BOOLEAN | NOT NULL, 默认 `0` | 本次触发是否使用等待语义（FR-010 排障用） |

平台通用字段同上。

**索引**：`(project_id, created_at)` 复合索引 —— 触发历史按「项目 + 时间」分页是主查询路径（FR-022、SC-009）；`plan_id`（防重判定）；`status`（终态恢复与筛选）

**不设唯一约束**：允许同一 `external_build_id` 被重复触发（Edge Case 已声明各自成条，不覆盖不合并）。

### 2.3 不变量

- `token_hash = sha256(明文token)`，**明文只在签发响应里出现一次**，此后任何读路径都拿不到
- `token_prefix == 明文[:12]`，只作展示，**校验不使用它**（避免「前缀命中即放行」的错误实现）
- `project_id` 是硬边界：`CIPermission` 解析出的 `project_id` 必须等于目标 `plan.project_id`，否则 403（FR-005）
- `status ∈ {0,1}` 的记录表示「可能仍在跑」；进程重启后必须被收敛到终态（§3.2）
- `deleted_at = 0` 的集成配置才参与校验
- `enabled = 1` 且（`expires_at IS NULL` 或 `expires_at > now()`）才通过校验

## 3. 状态流转

### 3.1 `pity_ci_run.status`

```
                     ┌──────────────────────────────────────────┐
                     │                                          │
   POST /ci/run ──▶ 0 pending ──▶ 1 running ──┬──▶ 2 success    │
        (建记录)         │              │      ├──▶ 3 failed     │
                         │              │      └──▶ 5 error      │
                         │              │            (执行异常)   │
                         │              │                         │
                         │              └──▶ 4 timeout            │
                         │                   (等待语义超时,       │
                         │                    任务仍在后台,       │
                         │                    终态由回填步骤写)    │
                         │                                        │
                         └──▶ 5 error ◀── 平台重启(lifespan 第5步) ┘
                              (记录创建后、执行前失败)
```

| 转移 | 触发者 | 说明 |
|---|---|---|
| → `0 pending` | `POST /ci/run` | 记录创建即入队，`wait=false` 下调用方拿到的就是这个 `id` |
| `0` → `1 running` | `ci_runner` | 开始执行前写入 |
| `1` → `2 success` | `ci_runner` | 全部用例通过且至少 1 条用例执行（FR-018） |
| `1` → `3 failed` | `ci_runner` | 存在 `failed > 0` 或 `error > 0`，或总用例数为 0（空计划，**不得判成功**） |
| `1` → `4 timeout` | `ci_runner` | 等待语义超时；**任务继续**，回填步骤最终把结果写进同一条记录（终态仍是 2/3，`4` 只在「超时且后来也没跑完」时保留） |
| `0/1` → `5 error` | `ci_runner` / `lifespan` | 执行抛异常（`raise_on_error=True` 路径），或平台重启时残留的进行中记录 |
| `0` → `5 error` | `ci_runner` | 记录建好但计划校验失败（计划被删等） |

> **`4 timeout` 的语义边界**：它是「调用方等待超时」的中间态，不是终局。若任务随后完成，记录被回填成 `2/3`（并保留 `cost`）；若直到进程退出仍未完成，则由 lifespan 收敛为 `5 error`。**绝不允许记录永久停在 `0/1/4`**（FR-031）。

### 3.2 重启恢复（lifespan 第 5 步）

单进程部署（gunicorn `-w 1`）下，进程重启 = 所有在跑的执行真的消失，没有别的 worker 接手。

```
启动 → create_table() → 【第 5 步】
        UPDATE pity_ci_run SET status=5,
               error_msg='平台重启导致执行中断',
               finished_at=now()
        WHERE status IN (0,1) AND deleted_at=0
```

- 标 `5 error`（平台执行失败）而非 `3 failed`（测试未通过）—— 语义正确，且与 FR-015 一致
- 放在建表**之后**（必须先有表），失败只记日志不抛（同「注册内置 UI 执行节点」的处理方式，不拖垮启动）
- 单进程下「启动时扫一次」即可，**不需要**定时扫描任务

## 4. 通过率与空计划的判定（FR-013 / FR-018）

复用 `executor.py:619` 已有的判定，不另写一套：

```
total = success + failed + error + skipped
通过  ⟺ total > 0  AND  failed == 0  AND  error == 0
```

- `total == 0`（计划一个用例都没有）→ **判为未通过**，`error_msg` 提示「计划为空，无法判定」
- `pass_rate = success * 100 // total`（`total > 0` 时），向下取整；`total == 0` 时保持 0

**多环境**：`run_test_plan` 对每个 env 各产生一条 `pity_report`；`pity_ci_run` 存汇总（各状态计数相加），`report_ids` 存全部报告 id。**整体通过 = 所有环境都通过**（任一环境未通过即整体未通过）。

## 5. 脱敏规则（GATE-SEC）

| 数据 | 落库 | 落日志 | 界面 |
|---|---|---|---|
| 凭据明文 | ❌ 永不 | ❌ 永不（`log_sanitize` + 硬编码禁列） | 仅签发弹窗一次 |
| `token_hash` | ✅ | ❌ 不记 | ❌ 不回显 |
| `token_prefix` | ✅ | ✅ 可记 | ✅ 列表展示 |
| `external_build_id` | ✅ | ✅ 可记（已是调用方自定的公开编号） | ✅ |
| `external_url` | ✅ | ✅ 过 `log_sanitize`（URL path/query 脱敏） | ✅ 可跳转 |
| `error_msg` | ✅（≤500 字符） | ✅ | ✅ |

- 凭据与 `error_msg` 写日志前必须过 `app/utils/log_sanitize.py`（`backend/CLAUDE.md` 日志章节硬规矩 3：AI 日志分析会读这两个日志文件，不脱敏等于把凭据明文存进日志）
- `error_msg` 写入前截断到 500 字符，避免异常堆栈把 `TEXT` 撑爆

## 6. 一期只存不发的 `callback_url`（决定 Q1 + Q5）

- 字段**一期建**（避免二期加列迁移），CRUD 里可存、可读、可展示
- **一期任何代码路径都不读它发送** —— `ci_selftest.py` 源码静态扫描断言：一期源码中不存在对 `callback_url` 的出网调用（无 `aiohttp` / `httpx` / `requests`）
- 二期开工前必须先决策（`proposal.md` §7.2）：内网 Jenkins 与 `ui_security.is_blocked_ip` 的矛盾，取向是「项目级 host 白名单 + 仅管理员配置」，**不做全局放开**

## 7. 四态就地指引（GATE-IV，FR-029）

`/ci` 页面每个区域在缺前置条件时**原地**给出指引与入口，不依赖视野外配置：

| 态 | 触发条件 | 界面行为 |
|---|---|---|
| **G1 未选项目** | 项目选择器为空 | 提示「先选择项目」+ 项目列表入口；**不**展示任何空表格 |
| **G2 无集成配置** | 当前项目下 `pity_ci_integration` 为空 | 展示「新建集成」主按钮 + 一句话说明凭据用途；接入示例区显示占位引导而非残缺片段 |
| **G3 无测试计划** | 当前项目下 `pity_test_plan` 为空 | 就地提示「先创建测试计划」+ 跳 `/apiTest/testplan` 入口（**这是接入的硬前置**，没有计划就没有可触发的对象） |
| **G4 无触发记录** | 当前项目下 `pity_ci_run` 为空 | 展示接入示例 + 「如何触发第一次」三步说明，而不是一片空白 |

G2 与 G3 可同时出现（新项目），此时**两个指引并列展示**，按「先计划、后凭据」的顺序排列 —— 没有计划即使签了凭据也无从触发。

## 8. 关键查询路径

| 场景 | 查询 | 索引 |
|---|---|---|
| 凭据校验（每次调用） | `WHERE token_hash = ? AND deleted_at = 0` | `token_hash` |
| 集成配置列表 | `WHERE project_id = ? AND deleted_at = 0 ORDER BY created_at DESC` | `project_id` |
| 触发历史分页 | `WHERE project_id = ? AND created_at BETWEEN ? AND ? AND deleted_at = 0 ORDER BY created_at DESC LIMIT/OFFSET` | `(project_id, created_at)` |
| 防重判定 | `WHERE plan_id = ? AND status IN (0,1) AND deleted_at = 0` | `plan_id` |
| 重启终态恢复 | `WHERE status IN (0,1) AND deleted_at = 0` | `status` |

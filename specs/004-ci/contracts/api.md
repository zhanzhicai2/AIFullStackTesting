# API Contract: 持续集成（外部 CI 对接）

**Branch**: `004-ci` | **Date**: 2026-11-23 | **Spec**: [spec.md](./spec.md)

> **前后端唯一契约**。改此文件 MUST 同步改两端实现；两端实现与契约冲突时以本文件为准。
> 所有接口响应遵循平台协议：HTTP 恒为 `200`，业务码在 body 里 `{"code": 0, "data": {}, "msg": "操作成功"}`。
> 权威常量定义：后端 `backend/app/enums/CiEnum.py`，前端镜像 `frontend/src/consts/ci.ts`（**改一处 MUST 同步改另一处**）。

## 0. 业务码表（本特性相关）

| code | 含义 | 出现端点 | CI 侧动作 |
|---|---|---|---|
| `0` | 成功，且**测试通过** | 全部 | 继续流水线 |
| `101` | 参数错误（`RequestValidationError` 自动捕获） | 全部 | 阻断，修 CI 配置 |
| `110` | 业务异常（计划不存在 / 重复触发 / 集成配置非法等） | 全部 | 阻断，打印 `msg` |
| `111` | **测试未通过**（FR-014 / 决定 Q2） | `POST /ci/run` | `exit 1` 阻断 |
| `112` | **等待超时**，执行仍在后台继续（FR-011） | `POST /ci/run`（仅 `wait=true`） | 拿 `data.run_id` 轮询，或按自身策略判失败 |
| `401` | 凭据无效 / 已过期 / 已停用 | `CI` 端点 | 阻断，换凭据 |
| `403` | 凭据越权（跨项目）或角色不足 | 全部 | 阻断 |

> **`111` 是决定 Q2 批准的新码**；**`112` 是本契约的必要补充** —— FR-011 要求「等待超时」与「业务异常」可区分，否则 CI 无法决定「再轮询一次」还是「直接放弃」。两者都在 `0 / 101 / 110` 同区段递增，不碰 HTTP 段。**若不同意 `112`**，可改为 `code=0` + `data.wait_timeout=true`，但 CI 脚本必须改成解析 `data` 才能判断，`[ "$code" = "0" ]` 一行判据会失效。

**凭据类拒绝的可区分性**（FR-016）—— 三者都走 `401`，靠 `msg` 区分：

| 情形 | `msg` |
|---|---|
| 摘要不匹配 | `CI 凭据无效` |
| 已过期 | `CI 凭据已过期` |
| 已停用 | `CI 凭据已停用` |

> `msg` 是给脚本打印看的，**不回显任何凭据内容**。

## 1. 鉴权契约

### 1.1 Header

CI 端点读 **`token`** header（与平台既有 `Permission()` 同名，接入示例好抄）：

```bash
curl -X POST "http://localhost:7777/ci/run" \
  -H "token: pity_ci_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"plan_id": 12, "external_build_id": "42", "wait": true}'
```

- 值以 `pity_ci_` 开头 → 走 CI 摘要校验（`CIPermission`）
- 值不以 `pity_ci_` 开头 → 按 JWT 语义（**仅为分流，CI 端点实际只接受 CI 凭据**）
- **`CIPermission()` 的返回结构与 `Permission()` 完全一致**（`user_info` 字典），其中 `id` = 凭据的 `create_user`（签发人），`role` 取签发人的角色

### 1.2 凭据格式

```
明文 = "pity_ci_" + secrets.token_hex(16)     # 总长 8 + 32 = 40 字符
入库 = {"token_hash": sha256(明文), "token_prefix": 明文[:12]}
```

- **明文只在签发响应里出现一次**，此后任何读路径都拿不到（FR-002）
- `token_prefix` = `pity_ci_xxxx`（12 字符），仅列表展示
- **不可重放（安全属性，非缺陷）** —— constitution 原则 I 显式标注

### 1.3 校验链（顺序固定）

```
1. token 以 pity_ci_ 开头              否 → 401 "CI 凭据无效"
2. sha256(token) 查 token_hash 命中      否 → 401 "CI 凭据无效"
3. deleted_at == 0                      否 → 401 "CI 凭据无效"
4. enabled == 1                         否 → 401 "CI 凭据已停用"
5. expires_at IS NULL OR > now()        否 → 401 "CI 凭据已过期"
6. 目标 plan.project_id == 凭据 project_id   否 → 403 "无权触发该项目的测试计划"
7. 通过 → 更新 last_used_at = now()
```

---

## 2. 集成配置管理（前缀 `/ci`，`Depends(Permission(Config.MANAGER))`）

全部按 `project_id` 隔离；`Config.MANAGER = 1`（admin / superAdmin），普通成员拿不到（FR-028）。

### 2.1 列表 `GET /ci/integration/list?project_id=`

**响应 `data`**（`PityResponse.success_with_size`，`total` 在顶层）：

```json
{
  "code": 0, "msg": "操作成功", "total": 2,
  "data": [
    {
      "id": 1, "project_id": 1, "name": "Jenkins-main",
      "token_prefix": "pity_ci_a1b2",
      "plan_id": 12, "callback_url": null,
      "enabled": true, "expires_at": "2027-11-23 18:00:00",
      "last_used_at": "2026-11-23 17:40:11",
      "created_at": "2026-11-23 18:00:00", "create_user": 1
    }
  ]
}
```

> **响应中不存在 `token_hash` 与完整 `token`** —— FR-002 / SC-007。

### 2.2 签发 `POST /ci/integration/insert`

请求体：

| 字段 | 类型 | 必填 | 校验 |
|---|---|---|---|
| `project_id` | int | 是 | 项目存在 |
| `name` | str | 是 | ≤32 字符，同项目内不重复 |
| `plan_id` | int | 否 | 属于 `project_id`，否则 110 |
| `callback_url` | str | 否 | **一期只存不发**；≤255 |
| `expires_at` | str | 否 | ISO 时间；不传 = `now + 1 年`；显式传 `null` = 长期有效（决定 Q4） |

**响应**：

```json
{
  "code": 0, "msg": "操作成功",
  "data": {
    "id": 3,
    "token": "pity_ci_9f2c4e8a1b7d0c3f5e6a8b9c0d1e2f3a",
    "token_prefix": "pity_ci_9f2c"
  }
}
```

> **`token` 字段仅此一次出现**。前端必须用一次性弹窗展示 + 复制按钮，关闭后不可再取（FR-002）。

### 2.3 编辑 `POST /ci/integration/update`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int | 是 | |
| `name` | str | 否 | |
| `plan_id` | int | 否 | 同上归属校验；传 `null` 解绑 |
| `callback_url` | str | 否 | 同上 |
| `expires_at` | str | 否 | 同上 |

> **编辑接口不接受任何凭据字段** —— 凭据不可改，只能「删了重签」。

### 2.4 启停 `GET /ci/integration/switch?id=&status=`

`status`：`true` 启用 / `false` 停用。停用**立即**拒绝新调用（FR-003）；已在跑的执行不受影响（FR-030）。

### 2.5 删除 `GET /ci/integration/delete?id=`

逻辑删除（`deleted_at = now()`）。**不物理删除** —— `pity_ci_run.integration_id` 还要能回溯。

---

## 3. 触发与查询（前缀 `/ci`，`Depends(CIPermission())`）

### 3.1 触发 `POST /ci/run`

> **为什么是 POST 不是 GET**：平台既有 `/testcase/plan/execute` 用 GET 是历史习惯，但触发会**创建一条 `pity_ci_run` 记录**（副作用），语义上是创建资源。CI 场景下 GET 还会被中间层缓存/预取，风险更高。**本端点刻意用 POST**，与既有 GET 不冲突（不同路径）。

请求体（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plan_id` | int | 条件必填 | 凭据未绑定 `plan_id` 时必填；绑定时可省略（用绑定值）；传了则**覆盖**绑定值 |
| `env` | int[] | 否 | 覆盖计划的执行环境；不传 = 按计划配置（FR-019） |
| `wait` | bool | 否 | **默认 `false`**（决定 Q3） |
| `timeout_sec` | int | 否 | 仅 `wait=true` 生效；默认 `300`，上限 `1800`，下限 `1` |
| `external_build_id` | str | 否 | ≤64，如 Jenkins `$BUILD_NUMBER` |
| `external_url` | str | 否 | ≤255，流水线地址，历史中可跳转 |

**响应（`wait=true`，执行完成）**：

```json
{
  "code": 0, "msg": "测试通过",
  "data": {
    "run_id": 88,
    "waited": true, "wait_timeout": false,
    "status": 2,
    "plan_id": 12, "plan_name": "冒烟回归",
    "env": [1, 2],
    "success_count": 10, "failed_count": 0, "error_count": 0, "skipped_count": 0,
    "pass_rate": 100,
    "report_ids": [451, 452],
    "report_url": "http://localhost:8000/#/record/report/451",
    "cost": "12.34",
    "started_at": "2026-11-23 18:00:00", "finished_at": "2026-11-23 18:00:12"
  }
}
```

**同一结构下的其余返回**：

| 情形 | `code` | `msg` | `data.status` | `data.wait_timeout` |
|---|---|---|---|---|
| 测试通过 | `0` | `测试通过` | `2` | `false` |
| 测试未通过 | `111` | `测试未通过（失败 2 / 异常 1）` | `3` | `false` |
| 等待超时 | `112` | `等待超时，执行仍在继续，请轮询 run_id` | `4` | `true` |
| 计划为空 | `111` | `计划为空，无法判定` | `3` | `false` |
| 重复触发 | `110` | `该测试计划已有执行在进行中` | — | — |
| 计划不存在/已删 | `110` | `测试计划不存在或已删除` | — | — |
| 凭据无效/过期/停用 | `401` | 见 §1.3 | — | — |
| 跨项目 | `403` | `无权触发该项目的测试计划` | — | — |

**响应（`wait=false`，立即返回）**：

```json
{
  "code": 0, "msg": "已受理，正在执行",
  "data": {
    "run_id": 89, "waited": false, "wait_timeout": false,
    "status": 0, "plan_id": 12, "plan_name": "冒烟回归", "env": [1]
  }
}
```

> `wait=false` 时 `code` 恒为 `0`（受理成功 ≠ 测试通过）。**判定必须查 `GET /ci/run/{id}`**。

### 3.2 结果查询 `GET /ci/run/{id}`

**响应 `data`**（与 3.1 的 `data` 同构，`waited` / `wait_timeout` 反映**触发时**的语义）：

```json
{
  "code": 0, "msg": "操作成功",
  "data": {
    "run_id": 89, "status": 2,
    "integration_id": 3, "project_id": 1,
    "plan_id": 12, "plan_name": "冒烟回归", "env": [1],
    "external_build_id": "42", "external_url": "https://jenkins/job/x/42/",
    "success_count": 10, "failed_count": 0, "error_count": 0, "skipped_count": 0,
    "pass_rate": 100,
    "report_ids": [453], "report_url": "http://localhost:8000/#/record/report/453",
    "error_msg": null,
    "cost": "12.34",
    "started_at": "2026-11-23 18:01:00", "finished_at": "2026-11-23 18:01:12",
    "created_at": "2026-11-23 18:00:59"
  }
}
```

**`data.status` 枚举**（权威定义 `CiEnum.RunStatus`，前端镜像）：

| 值 | 常量 | 含义 | 前端展示 |
|---|---|---|---|
| `0` | `PENDING` | 已受理，未开始 | 灰 · 进行中 |
| `1` | `RUNNING` | 执行中 | 蓝 · 进行中 |
| `2` | `SUCCESS` | 通过 | 绿 · 通过 |
| `3` | `FAILED` | 测试未通过 | 红 · 未通过 |
| `4` | `TIMEOUT` | 等待超时（可能仍在跑） | 橙 · 超时 |
| `5` | `ERROR` | 平台执行失败 / 重启中断 | 灰 · 执行失败 |

> **`3` 与 `5` 必须可区分**（FR-015 / SC-006）：`3` = 测试红了，`5` = 平台坏了。前端文案与颜色都不同。

### 3.3 触发历史 `GET /ci/run/list?project_id=&page=&size=&plan_id=&status=&start_time=&end_time=`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | int | 是 | **强制按项目隔离**，不传 → 101 |
| `page` / `size` | int | 否 | 默认 1 / 20 |
| `plan_id` | int | 否 | |
| `status` | int | 否 | 按 §3.2 枚举过滤 |
| `start_time` / `end_time` | str | 否 | `YYYY-MM-DD HH:mm:ss`，按 `created_at` |

**响应**：`PityResponse.success_with_size`，`data` 为 §3.2 的 `data` 数组（**不含 `token_hash`**），`total` 在顶层。按 `created_at DESC`。

---

## 4. 跨端常量镜像（GATE-III）

| 后端权威 | 前端镜像 | 内容 |
|---|---|---|
| `backend/app/enums/CiEnum.py` | `frontend/src/consts/ci.ts` | `CI_NOT_PASSED = 111` / `CI_WAIT_TIMEOUT = 112` / `RunStatus` 六态 / `TOKEN_PREFIX = "pity_ci_"` / `TOKEN_DEFAULT_EXPIRE_DAYS = 365` / `WAIT_TIMEOUT_DEFAULT_SEC = 300` / `WAIT_TIMEOUT_MAX_SEC = 1800` |

前端镜像文件头 MUST 注释指认后端权威出处；`backend/CLAUDE.md` 与 `frontend/CLAUDE.md` 各补一条「MUST 同步修改两处」。

---

## 5. 前端接入示例片段（`SnippetsPanel` 渲染，凭据恒为占位符）

**Jenkinsfile**

```groovy
stage('Pity 测试') {
  steps {
    script {
      def resp = httpRequest url: "${PITY_URL}/ci/run",
        httpMode: 'POST',
        contentType: 'APPLICATION_JSON',
        customHeaders: [[name: 'token', value: "${PITY_CI_TOKEN}", maskValue: true]],
        requestBody: '{"plan_id": 12, "external_build_id": "${BUILD_NUMBER}", "wait": true, "timeout_sec": 300}'
      def body = readJSON text: resp.content
      // 0 通过 / 111 未通过 / 112 超时 → 其余一律阻断
      if (body.code != 0) { error("Pity: ${body.msg}") }
    }
  }
}
```

**GitHub Actions**

```yaml
- name: Pity 测试
  run: |
    CODE=$(curl -sS -X POST "${PITY_URL}/ci/run" \
      -H "token: ${PITY_CI_TOKEN}" -H "Content-Type: application/json" \
      -d "{\"plan_id\":12,\"external_build_id\":\"${GITHUB_RUN_NUMBER}\",\"wait\":true,\"timeout_sec\":300}" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["code"])')
    echo "pity code=${CODE}"
    [ "${CODE}" = "0" ] || exit 1
```

**片段规则**（FR-027 / D10）：
- `PITY_URL`、`plan_id`、`plan_name` **自动填当前配置的真实值**
- `PITY_CI_TOKEN` **恒为占位符** —— 粘进 Git 仓库的片段绝不能含真实凭据
- 一键复制，复制内容与页面展示一致

---

## 6. 接口清单汇总

| # | 方法 | 路径 | 鉴权 | 对应 FR |
|---|---|---|---|---|
| 1 | GET | `/ci/integration/list` | `Permission(MANAGER)` | FR-007 |
| 2 | POST | `/ci/integration/insert` | `Permission(MANAGER)` | FR-001/002/004/006 |
| 3 | POST | `/ci/integration/update` | `Permission(MANAGER)` | FR-006 |
| 4 | GET | `/ci/integration/switch` | `Permission(MANAGER)` | FR-003 |
| 5 | GET | `/ci/integration/delete` | `Permission(MANAGER)` | FR-003 |
| 6 | POST | `/ci/run` | `CIPermission` | FR-009~019 |
| 7 | GET | `/ci/run/{id}` | `CIPermission` | FR-012/023 |
| 8 | GET | `/ci/run/list` | `CIPermission` | FR-020~022 |

> 全部经 `main.py` 的 `Depends(request_info)` 记操作日志（FR-026 关联，凭据不入日志见 §data-model 5）。

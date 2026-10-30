# API Contract: Mock 配置

**Branch**: `003-mock-config` | **Date**: 2026-10-30 | **Spec**: [spec.md](./spec.md)

> 前后端唯一契约。改此文件 MUST 同步改两端实现;两端实现与契约冲突时以本文件为准。
> 所有管理接口响应遵循平台协议:`{"code": 0, "data": {...}, "msg": "操作成功"}`;业务码:`0` 成功 / `101` 参数错误 / `110` 业务异常 / `401` 未登录 / `403` 无权限。

## 1. 管理接口(前缀 `/mock`,需鉴权)

全部经 `Depends(Permission())`(登录 + 角色 ≥ MEMBER),DAO 层按 `project_id` 隔离。

### 1.1 规则列表 `GET /mock/rule/list`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | int | 是 | 只返回该项目的规则 |
| `method` | str | 否 | 按方法过滤(不传=全部) |
| `path` | str | 否 | 路径关键字模糊过滤 |
| `status` | int | 否 | 0 停用 / 1 启用 |
| `page` | int | 否 | 默认 1 |
| `size` | int | 否 | 默认 20 |

**响应 `data`**(遵循平台 `PityResponse.success_with_size` 结构:`data` 为数组、`total` 在顶层):

```json
{
  "code": 0, "msg": "操作成功",
  "data": [
    {
      "id": 1, "project_id": 1, "name": "用户详情", "method": "GET",
      "path": "/api/user/:id", "path_type": 1, "priority": 0,
      "status_code": 200, "response_headers": "{\"Content-Type\": \"application/json\"}",
      "response_body": "{\"code\": 0, \"data\": {\"id\": \"$request.path\", \"name\": \"$request.query.name\"}}",
      "delay": 100, "status": 1, "remark": "联调用",
      "created_at": "2026-10-30 10:00:00", "update_user": 1
    }
  ],
  "total": 3
}
```

> `response_headers` 原样返回 JSON 字符串,前端解析展示;`response_body` 原样返回字符串(JSON 或纯文本)。

### 1.2 新建规则 `POST /mock/rule/insert`

请求体(JSON):

| 字段 | 类型 | 必填 | 校验 |
|---|---|---|---|
| `project_id` | int | 是 | 项目存在 |
| `name` | str | 是 | ≤ 50 字 |
| `method` | str | 是 | 在 `MockEnum.METHODS` 内 |
| `path` | str | 是 | ≤ 255,以 `/` 开头,不含空白字符;`*` 只能出现在末尾 |
| `priority` | int | 否 | 默认 0 |
| `status_code` | int | 否 | 默认 200,100~599 |
| `response_headers` | str | 否 | 可空,须为合法 JSON 对象 |
| `response_body` | str | 否 | 可空;含 `$request.*` 的变量名须在合法白名单内 |
| `delay` | int | 否 | 默认 0,0~5000 |
| `status` | int | 否 | 默认 1,0/1 |
| `remark` | str | 否 | ≤ 200 字 |

**响应 `data`**:新建规则对象(同 1.1 列表项)。`msg` 在「同项目同方法同精确路径已存在」时提示:`"已存在相同方法+路径的规则,注意优先级"`(不阻断,FR-007)。

### 1.3 更新规则 `POST /mock/rule/update`

请求体 = 1.2 字段 + `id`(必填)。更新时重新推导 `path_type` 并校验全部字段。**响应 `data`**:更新后规则对象。

### 1.4 删除规则 `GET /mock/rule/delete`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int | 是 | 规则 id |
| `project_id` | int | 是 | 归属项目(防跨项目删除) |

逻辑删除(`deleted_at` 置位)。**响应 `data`**:`true`。

### 1.5 启停规则 `POST /mock/rule/status`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int | 是 | 规则 id |
| `project_id` | int | 是 | 归属项目 |
| `status` | int | 是 | 0 停用 / 1 启用 |

**响应 `data`**:更新后规则对象。停用立即退出对外匹配,启用立即恢复(FR-012)。

### 1.6 规则详情 `GET /mock/rule/detail`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int | 是 | 规则 id |
| `project_id` | int | 是 | 归属项目 |

**响应 `data`**:规则对象。

### 1.7 规则调试 `POST /mock/rule/preview`

就地模拟一次匹配(FR-009,不经过对外服务,不产生真实延迟等待):

请求体(JSON):

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | int | 是 | 归属项目 |
| `method` | str | 是 | 模拟请求方法 |
| `path` | str | 是 | 模拟请求路径(`/mock/{app}` 之后部分,可带 query,如 `/api/user/1?name=tom`) |
| `body` | str | 否 | 模拟请求体(JSON 字符串) |
| `headers` | str | 否 | 模拟请求头(JSON 对象字符串) |

**响应 `data`**:

```json
{
  "matched": true,
  "rule": { "id": 1, "name": "用户详情", "method": "GET", "path": "/api/user/:id", "priority": 0, "status_code": 200 },
  "status_code": 200,
  "response_headers": "{\"Content-Type\": \"application/json\"}",
  "response_body": "{\"code\": 0, \"data\": {\"id\": \"1\"}}",
  "delay": 100
}
```

未命中时:`{"matched": false, "rule": null, "reason": "没有规则会命中该请求"}`,HTTP 仍 200。

## 2. 对外 Mock 服务(前缀 `/mock`,无鉴权)

### 2.1 服务入口 `[GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS] /mock/{app}/**`

- **注册顺序硬约束**:本路由 MUST 在管理路由(`/mock/rule/*`)之后注册 —— 否则 `/mock/rule/list` 被当成 `app=rule` 的对外请求吞掉
- 请求处理:
  1. `app = path_params["app"]`;按 `Project.app == app AND deleted_at == 0` 查项目,按 `id` 升序取第一条(app 重复取最早创建,FR-018)
  2. 项目不存在 / `app` 为空 → 404
  3. 项目内取启用规则(§data-model 匹配算法) → 未命中 → 404
  4. 命中 → `await asyncio.sleep(delay/1000)` → 按规则返回
- **响应**:HTTP 状态码 = `status_code`;响应头 = `response_headers`(JSON 解析,缺 `Content-Type` 时按响应体形态推断:合法 JSON → `application/json`,否则 `text/plain`);响应体 = `response_body` 经白名单变量渲染后的字符串;`HEAD` 请求返回空体(HTTP 语义)
- **未命中响应**(业务 404,HTTP 404):

```json
{ "code": 404, "data": null, "msg": "mock rule not found" }
```

> 不泄露任何项目或规则信息(FR-006)。

## 3. 错误码速查

| 场景 | HTTP | code | msg |
|---|---|---|---|
| 命中规则 | 按规则 | 0 | 操作成功 |
| 未命中 / app 不存在 / app 为空 | 404 | 404 | mock rule not found |
| 管理接口未登录 | 200 | 401 | 用户信息身份认证失败, 请检查 |
| 管理接口无权限 | 200 | 403 | 对不起, 你没有足够的权限 |
| 参数/校验失败 | 200 | 101 | 具体原因 |
| 业务异常(规则不存在、跨项目、状态非法) | 200 | 110 | 具体原因 |

## 4. 常量引用

- 方法集 / 路径类型 / 延迟上限:后端 `app/enums/MockEnum.py` 权威,前端 `src/consts/mock.ts` 镜像(改一处必须改另一处)

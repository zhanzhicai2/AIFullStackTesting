# Research: Mock 配置

**Branch**: `003-mock-config` | **Date**: 2026-10-30 | **Spec**: [spec.md](./spec.md)

## 1. 现状调研

| 项 | 现状 | 结论 |
|---|---|---|
| 前端菜单 | `frontend/config/routes.ts` 已有 `/mock` 一级菜单「Mock 配置」,icon `icon-mockplus_doc`,component 指向 `./Building`(建设中占位页) | 路由与菜单已存在,只需把 component 换成真实页面 |
| 后端实现 | `backend/` 无任何 mock 表、DAO、路由;`grep -ri mock` 只命中 `AsyncHttpClient.py` 的 `Config.MOCK_ON` 代理开关与 `ai_client.py` 注释 | 纯从零设计;`MOCK_ON` 是执行客户端全局代理,与本特性无关,不动它 |
| 上游参考 | 上游 pity / pityWeb 无独立 Mock 模块;`icon-mockplus_doc` 仅暗示参考 MockPlus 类工具 | 按测试平台通用实践(易盘 EasyMock / Yapi / MockPlus 形态)设计 |
| 可复用机制 | `pity_project`(含 `app` 应用名字段)、`pity_environment`、`ProjectRoleDao.read_permission` / `judge_permission`、`Permission()`、`PityBase` 审计字段、`PityResponse`、`@ModelWrapper` DAO 模式、hooks 风格前端 model/service | 全部复用,不新建平行体系(constitution 原则 II) |
| 项目级权限惯例 | 用例/元素/页面: `Permission()`(登录即可写);安全敏感面(允许域名、节点删除): `Permission(role=Config.ADMIN)` | mock 规则是**普通业务数据**(不控制出网、不执行代码),与用例同级,用 `Permission()` |

## 2. 技术决策

### D1. 形态:纯静态 Mock 服务(用户已确认)

平台内置 `GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS /mock/{app}/**` 入口,命中规则返回配置的状态码/头/体(可带延迟),未命中返回 404 业务码。

- **不实现"未命中转发真实后端"**: 避免引入 SSRF 面(002 用了六道拦截才守住,这里没必要为省一次配置把面开回来)
- **不实现代理/记录回放**: MVP 范围外
- mock 服务从机制上排除 SSRF: 命中只读库返回静态内容,未命中即 404,代码中不存在任何出网调用与代码执行位

### D2. 响应变量:请求回显白名单(用户已确认)

响应体支持四类变量,全部**由请求内容决定**,不引入随机源 → 满足 constitution 原则 I(同样输入 MUST 产出完全一致结果):

| 变量 | 语义 |
|---|---|
| `$request.path` | 被测接口原始路径(`/mock/{app}` 之后部分,不含 query) |
| `$request.query.<name>` | 查询参数值(同名多值取第一个,MVP 不支持数组) |
| `$request.body.<key.path>` | JSON 请求体按点分路径取值(数组用数字索引,如 `$request.body.items.0.name`);body 非 JSON 时取不到 → 空串 |
| `$request.header.<name>` / `$request.headers.<name>` | 请求头值(忽略大小写) |

- 合法变量名正则(管理端保存时校验): `^\$request\.(path\|query\.[A-Za-z0-9_.-]+\|body\.[A-Za-z0-9_.-]+\|header(s)?\.[A-Za-z0-9_-]+)$`
- 取不到值(请求未携带)→ **替换为空字符串**,不报错不抛异常,响应结构保持稳定
- **不碰既有 `app/core/render.py`**(裸 `Environment()`,非沙箱,可执行任意表达式): 变量渲染用独立小实现,只做"查字典替换",无表达式求值面
- 不引入 `$timestamp` / `$randomInt`: 与原则 I 冲突;时间戳/随机属后续扩展,须重新过 Gate

### D3. 匹配引擎:确定性排序(纯函数,核心资产)

路径按内容推导类型:`*` 存在 → 通配(2);`:xxx` 存在 → 参数化(1);否则精确(0)。**存储时固化 `path_type`,避免每次匹配重复推导**。

匹配流程(全排序确定,无随机):

```
1. 项目定位: Project.deleted_at==0 AND app=={app} → 按 id asc 取第一条(FR-018: app 重复取最早创建)
2. 候选规则: 该项目下 deleted_at==0 AND status==1(启用)
3. 方法过滤: rule.method == 请求 method OR rule.method == 'ANY'
4. 路径匹配:
   - 精确(0): path 与请求路径完全相等(不含 query)
   - 参数化(1): `/api/user/:id` ↔ `/api/user/123`,`:xxx` 恰好匹配一个路径段(不含 `/`)
   - 通配(2): `/api/*` ↔ `/api/任意/多段/...`(`*` 只在末尾出现时,匹配剩余任意内容,含空)
5. 命中多条 → 排序取第一条: path_type 升序(精确优先) → priority 升序 → id 升序
6. 响应: sleep(delay) → 返回 status_code + response_headers + 变量解析后的 response_body
```

匹配器设计为**纯函数**(入参: method + path + query + body + headers + 规则列表;出参: 命中的规则或 None),便于 selftest 不依赖数据库直接断言。

### D4. Mock 基地址标识:复用 `Project.app`

基地址 `http://{host}/mock/{app}/...`,`app` 即 `pity_project.app`(String(32),前端已有字段)。

- `app` 无唯一约束(项目表只有 name 唯一)→ 重复时取 id 最小者(FR-018),配置页就地提示
- `app` 为空 → 项目规则不可达,配置页就地提示(FR-019)
- 路径约定 `http://{host}:7777/mock/{app}/{被测接口路径}` —— 管理页展示基地址与示例,一键复制

### D5. 鉴权模型

| 面 | 鉴权 | 理由 |
|---|---|---|
| 对外 mock 服务 | **无鉴权** | 被测系统无法携带平台 JWT;半公开入口是设计取舍(spec Assumptions 已声明)。从机制上排除出网与执行,剩余风险仅"知晓 app 即可读取配置的假数据" |
| 规则管理接口 | `Depends(Permission())`(登录 + 角色≥MEMBER) | 与用例/元素同级 —— mock 规则是普通业务数据,不是安全边界;constitution 的"新增写入通道收紧角色"按 `Permission()` 默认级别满足(2 号元素 DAO 同款) |
| 项目隔离 | DAO 层按 `project_id` 过滤 + 私有项目读检查(`ProjectRoleDao.read_permission`) | 列表/详情只返回所属项目的规则,跨项目访问即 404/403 |

### D6. 路由组织(关键: 避免 catch-all 吞管理接口)

两个 `APIRouter`,都挂 `/mock` 前缀:

- **管理路由**(`app/routers/mock/admin.py`): `rule/list` `rule/insert` `rule/update` `rule/delete` `rule/status` `rule/detail` `rule/preview`。**在 main.py 中先于服务路由注册**(Starlette 按注册顺序匹配,先注册的先命中)
- **服务路由**(`app/routers/mock/service.py`): `api_route("/{full_path:path}", methods=[七种])` 的 catch-all,**最后注册**,且 include 时**不带 `request_info` 依赖**(无鉴权、不记操作日志)

`main.py` 变更:

```python
pity.include_router(mock_admin_router, dependencies=[Depends(request_info)])
pity.include_router(mock_service_router)          # 无 request_info
```

> 注意: 若 catch-all 先注册, `/mock/rule/list` 会被当成「app=rule, path=/list」的对外请求吞掉 → 顺序是硬约束,写进 tasks 与注释。

### D7. 变量渲染与请求体读取

- 服务端用 FastAPI `Request` 原生对象:`request.method` / `request.path_params["full_path"]` / `request.query_params` / `request.headers` / `await request.body()`
- 请求体按 `Content-Type` 判断: `application/json` 才做 JSON 解析(变量 `$request.body.*` 可用);否则 body 变量一律空串,响应体照常返回
- 响应头 `response_headers` 以 JSON 存储,解析后逐条写入响应;`Content-Type` 缺省时按响应体形态推断(`application/json` / `text/plain`)
- 响应体若本身就是合法 JSON 且包含变量占位,直接按字符串解析后返回 —— 不做二次 JSON 校验(变量替换后仍保持原始串)

### D8. 延迟模拟

`delay` 0~5000ms 整数,默认 0;服务端 `await asyncio.sleep(delay/1000)`。确定性退避常量,无随机。上限校验放管理端 schema。

### D9. 回归策略(constitution 原则 V)

| 脚本 | 依赖 | 覆盖 |
|---|---|---|
| `backend/scripts/mock_selftest.py` | 无 DB | 匹配引擎纯函数全表(精确/参数化/通配/方法 ANY/优先级/确定性双跑一致/未知 app/停用排除/路径类型推导/变量四类正反例/未知变量拒绝/取不到值空串/响应头解析/延迟边界) + **源码静态扫描**(mock 模块 AST 中无出网调用 `aiohttp|httpx|requests`、无 `eval|exec`) |
| `backend/scripts/mock_e2e.py` | 有 DB | 建规则 → 走对外入口(直接调路由函数,绕 HTTP)→ 校验状态码/头/体/变量回显/延迟;启停生效;删除后 404;管理端点权限;app 重复取最早;app 为空不可达 |
| 前端 | — | `npx tsc --noEmit` 0 错误 + ESLint 0 告警 |

### D10. 前端结构

- `frontend/src/pages/Mock/index.tsx` + `Mock.less`: 项目选择 → 基地址展示区(复制)→ 规则表格(方法标签/路径/名称/延迟/优先级/启停开关/操作)→ 新建/编辑 Modal → 调试 Modal
- `frontend/src/services/mock.ts`: 7 个管理接口封装
- `frontend/src/models/mock.ts`: hooks 风格 model(`@umijs/plugin-model`)
- `frontend/src/consts/mock.ts`: 方法与路径类型的常量(后端权威,前端镜像并指认 —— constitution 原则 III)
- `routes.ts`: `/mock` 的 component 从 `./Building` 改为 `./Mock/index`
- 就地指引(constitution 原则 IV): 未选项目 / 项目 app 为空 / 项目下无规则 三态就地提示

## 3. 否决的备选

| 备选 | 否决理由 |
|---|---|
| **未命中转发真实后端** | 引入 SSRF 面(域名白名单、DNS 后逐 IP、重定向逐跳),复杂度与安全成本不成比例;联调"漏配自动走真实"可用 mock + 真实环境切换代替 |
| **用例执行时拦截 URL**(改 Executor) | 侵入执行引擎,影响面大;且解决不了"前端/被测系统联调"这个主场景;平台用既有 HTTP 用例即可调用 mock 服务 |
| **响应支持 Jinja2 / `Render` 模板** | `app/core/render.py` 是非沙箱裸 `Environment()`,可执行任意表达式 → 配置 mock 响应的用户等于拿到 RCE;独立小渲染器只做字典替换,零表达式面 |
| **引入随机/时间戳变量** | 违反 constitution 原则 I(不可重放);断言场景下随机响应不可测 |
| **按环境(dev/test/prod)再分维度** | `pity_environment` 是全局的,与项目无关联;环境差异让被测系统在基地址上自行区分更简单 |
| **mock 命中统计/日志归因** | MVP 范围外;后续可复用 `pity_sql_history` 的表结构思路扩展,本轮不做 |

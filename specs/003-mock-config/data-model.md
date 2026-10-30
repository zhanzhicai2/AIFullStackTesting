# Data Model: Mock 配置

**Branch**: `003-mock-config` | **Date**: 2026-10-30 | **Spec**: [spec.md](./spec.md)

## 1. 概览

本特性新增 **1 张表**:`pity_mock_rule`(Mock 规则)。规则按 `project_id` 归属项目,复用 `pity_project.app` 作为对外 mock 基地址的项目标识(**不改动项目表**)。匹配引擎为纯函数(确定性),响应变量为封闭白名单(请求回显),无随机源。

## 2. 表结构

### 2.1 `pity_mock_rule`(Mock 规则)

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INT | PK | 平台通用 |
| `project_id` | INT | NOT NULL, index | 归属项目 |
| `name` | VARCHAR(50) | NOT NULL | 规则名 |
| `method` | VARCHAR(10) | NOT NULL, 默认 `ANY` | 请求方法:GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS/**ANY** |
| `path` | VARCHAR(255) | NOT NULL | 被测接口路径,如 `/api/user/:id`;支持 `:xxx` 参数占位与末尾 `*` 通配;以 `/` 开头 |
| `path_type` | INT | NOT NULL, 默认 0 | **存储时由 `path` 推导并固化**:0 精确 / 1 参数化(含 `:`)/ 2 通配(含 `*`) |
| `priority` | INT | NOT NULL, 默认 0 | 匹配优先级,数字越小越优先 |
| `status_code` | INT | NOT NULL, 默认 200 | 响应 HTTP 状态码 |
| `response_headers` | TEXT | 可空 | 响应头,JSON 对象字符串,如 `{"Content-Type": "application/json"}` |
| `response_body` | TEXT | 可空 | 响应体:JSON 或纯文本;可含回显变量 |
| `delay` | INT | NOT NULL, 默认 0 | 模拟延迟(毫秒),0~5000 整数,超界在 schema 层拦截 |
| `status` | INT | NOT NULL, 默认 1 | 0 停用 / 1 启用(与 UI 元素同款命名,不引入第二套) |
| `remark` | VARCHAR(200) | 可空 | 备注 |

平台通用字段(PityBase):`created_at` / `updated_at` / `deleted_at`(BIGINT,逻辑删除)/ `create_user` / `update_user`。

**唯一约束**:不设 DB 级唯一 —— 允许同「项目+方法+精确路径」存在多条规则(靠优先级区分返回),但新建精确路径规则时**就地提示已存在**(FR-007,后端返回 warning 文案,不阻断)。

### 2.2 不变量

- `path_type` 必须与 `path` 内容一致:`path` 含 `*` → 2;含 `:`(无 `*`)→ 1;否则 0(DAO 创建/更新时重新推导,防止手工写库造成漂移)
- `status = 1` 且 `deleted_at = 0` 的规则才参与对外匹配
- 对外匹配按「app 定位项目 → 项目内过滤」,**不存在跨项目匹配**
- `method` 只在 `MockEnum.METHODS` 内,否则 schema 拦截

## 3. 匹配算法(确定性,核心资产)

纯函数 `match_rule(method, full_path, rules) -> Optional[rule]`,输入除规则列表外均为请求快照;输出唯一确定。

```
1. 路径清洗: full_path 去掉末尾与首部多余的 `/`,不含 query
2. 候选集: rules 中 deleted_at==0 AND status==1
3. 方法过滤: rule.method == method OR rule.method == 'ANY'
4. 路径匹配(按 path_type):
   - 精确(0): rule.path == full_path
   - 参数化(1): rule.path 按 `/` 分段,段数与 full_path 相同;
     段含 `:` 前缀(`:xxx`)匹配任意单段(不含 `/`);其余段逐段相等
   - 通配(2): rule.path 形如 `/api/*`,星号必须在末尾;
     full_path 以 `/api/` 开头即命中(星号匹配剩余任意内容,含空)
5. 命中多条 → 排序取第一条(全排序确定):
   path_type 升序(精确 > 参数化 > 通配)
   → priority 升序(数字小优先)
   → id 升序(创建早优先)
```

**确定性声明**:同一请求快照 + 同一规则集,重复调用 MUST 命中同一条规则。回归脚本 `mock_selftest.py` 对全表用例做「双跑一致」断言。

**路径类型推导**(DAO 侧,与匹配器共用同一函数,防漂移):

```python
def derive_path_type(path: str) -> int:
    if "*" in path: return 2
    if ":" in path: return 1
    return 0
```

## 4. 变量规范(响应体白名单)

| 变量 | 语义 | 取值规则 |
|---|---|---|
| `$request.path` | 被测接口原始路径 | `/mock/{app}` 之后的部分,不含 query,不含末尾多余 `/` |
| `$request.query.<name>` | 查询参数 | 同名多值取第一个;不存在 → 空串 |
| `$request.body.<key.path>` | JSON 请求体字段 | 点分路径逐层取,数组用数字索引(如 `$request.body.items.0.name`);body 非 JSON 或取不到 → 空串 |
| `$request.header.<name>` / `$request.headers.<name>` | 请求头 | 忽略大小写;不存在 → 空串 |

- **合法变量名**(管理端保存时校验):`^\$request\.(path|query\.[A-Za-z0-9_.-]+|body\.[A-Za-z0-9_.-]+|header(s)?\.[A-Za-z0-9_-]+)$`
- 未携带的参数 → **替换为空字符串**,不报错、不抛异常,响应结构保持稳定
- 渲染器是**字典替换**:扫描 `$request.*` 模式并查表替换,零表达式求值、零函数调用 —— 源码 AST 静态扫描保证无 `eval`/`exec`/`getattr` 动态调用
- **不使用**既有 `app/core/render.py`(裸 `Environment()`,非沙箱,可执行任意表达式 —— 那是 RCE 面)

## 5. 就地指引(constitution 原则 IV)

| 编号 | 前置条件缺失 | 界面动作 |
|---|---|---|
| G1 | 未选择项目 | 页面顶部项目选择为空 → 就地提示「请先选择项目」,并提供前往项目列表的入口 |
| G2 | 项目 `app` 为空 | 选中项目后 → 就地提示「该项目未配置应用名(app),mock 基地址不可用,被测系统无法访问其规则」,指明去项目设置补全 |
| G3 | 项目下无规则 | 列表空态 → 展示「如何让被测系统调用 mock 服务」:基地址格式 + 一条示例 curl + 「新建第一条规则」按钮 |
| G4 | app 被多个项目占用 | 选中该 app 的任一项目 → 就地提示「app `{app}` 已被多个项目使用,mock 基地址将命中最早创建的项目」 |

## 6. 跨端契约

| 常量 | 权威位置 | 镜像位置 |
|---|---|---|
| 请求方法集(`METHODS`)/ 路径类型(`PATH_TYPE`)/ 延迟上限(`MAX_DELAY=5000`) | `backend/app/enums/MockEnum.py` | `frontend/src/consts/mock.ts`(指认 + `backend/CLAUDE.md` 声明同步) |
| 接口路径与字段 | `contracts/api.md` | `frontend/src/services/mock.ts` 按契约实现 |
| 响应协议 `{code,data,msg}` | 平台既有 `PityResponse` | — |

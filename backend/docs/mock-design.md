# Mock 配置 · 深设计附录

> 状态:**已实现并验证**(2026-10-30)。契约与权威定义见 `specs/003-mock-config/`。

## 1. 模块拆分

```
backend/app/
├── enums/MockEnum.py            # 跨端常量的后端权威定义(METHODS / PATH_TYPE / MAX_DELAY)
├── models/mock.py               # pity_mock_rule 表 Model
├── core/mock_engine.py          # 纯函数匹配引擎(derive_path_type / normalize_path / match_rule)
├── core/mock_render.py          # 白名单回显变量渲染器(字典替换, 零表达式)
├── schema/mock.py               # Pydantic v1 表单 + 变量白名单校验(引用 mock_render 的正则)
├── crud/mock/MockRuleDao.py     # 规则 CRUD + 查重提示 + 对外匹配查询 + app 定位项目
└── routers/mock/
    ├── admin.py                 # 7 个管理接口(Depends(Permission()) + read_permission)
    └── service.py               # 对外 catch-all(无鉴权, 零出网零执行)
```

## 2. 匹配算法(确定性, constitution 原则 I)

请求进入 `/mock/{app}/...`:

1. `app` 定位项目:`Project.app == app AND deleted_at == 0`,按 `id` 升序取第一条
   (app 重复时取最早创建 —— FR-018)
2. 项目内取候选:`deleted_at == 0 AND status == 1`(启用)
3. 方法过滤:`rule.method == 请求方法 OR rule.method == 'ANY'`
4. 路径匹配(`full_path` 已 normalize:去 query、合并 `/`、去末尾 `/`):
   - 精确(0):`rule.path == full_path`
   - 参数化(1):按 `/` 分段,段数一致;`:xxx` 段匹配任意单段(不含 `/`)
   - 通配(2):`*` 只在末尾,`full_path` 以去掉星号的前缀开头
5. 命中多条 → 全排序取第一条:**路径精确度 → 方法具体度(具体 0 > ANY 1) → priority → id**

纯函数、无随机源、无 IO —— `match_rule` 的输入仅请求快照 + 规则集,重复调用结果一致
(selftest「双跑一致」断言)。

## 3. 响应变量(封闭白名单)

| 变量 | 语义 |
|---|---|
| `$request.path` | 被测接口原始路径(normalize 后, 不含 query) |
| `$request.query.<name>` | 查询参数(同名多值取第一个) |
| `$request.body.<key.path>` | JSON 请求体字段(点分路径, 数组数字索引, 段间非空) |
| `$request.header(s).<name>` | 请求头(忽略大小写) |

- **权威正则定义在 `mock_render.VARIABLE_PATTERN`**,schema 派生锚定版做保存校验 —— 单一出处
- 取不到值 → 空串;bool → `true/false`;数字 → str;dict/list → JSON
- 任何「`$` + 字母开头」token 非 `$request.*` 白名单(如 `$randomInt`/`$timestamp`)→ 保存被拒;
  `$5`(数字)与 `${...}`(非系统语法)→ 原样输出
- **不引入随机源/时间戳** —— 与原则 I 冲突,后续扩展须重新过 Gate

## 4. 安全边界(本特性最关键)

| 面 | 保证 | 机器验证 |
|---|---|---|
| 零出网 | 命中只读库返回静态内容, 未命中 404, 无转发 | `mock_selftest.py` AST 扫描: mock 模块无 `aiohttp/httpx/requests/socket/urllib` |
| 零执行 | 渲染器只做字典替换, 无表达式求值 | AST 扫描无 `eval/exec`; `$request.body.__class__` 等形态取不到值(不执行) |
| 不碰既有 `render.py` | 非沙箱裸 `Environment()` 是 RCE 面, 禁用 | 代码评审 + 注释声明 |
| 写权限 | 管理接口 `Permission()`(与用例/元素同级) + 私有项目 `read_permission` | e2e: 私有项目非成员被拒、超管放行 |
| 半公开入口 | 对外服务无鉴权(设计取舍), 使用说明标注"勿放真实凭据" | 文档 |

## 5. 状态流转

```
新建(status=1, deleted_at=0)  --停用--> status=0  (立即退出对外匹配, 规则保留)
status=0 --启用--> status=1   (立即恢复匹配)
任何状态 --删除--> deleted_at 置位(逻辑删除, 立即 404)
```

唯一约束:不设 DB 级唯一 —— 同「项目+方法+精确路径」允许多条,靠优先级区分;
新建精确路径规则时 DAO 返回 warning 文案(FR-007)。

## 6. 测试跑法

```bash
cd backend
.venv/bin/python scripts/mock_selftest.py   # 不依赖数据库: 107 项断言
.venv/bin/python scripts/mock_e2e.py        # 需要数据库: 33 项断言
```

**selftest**(107 项):匹配全表正反例 + 双跑一致 + 变量四类正反例 + 未知变量拒绝 +
延迟/状态码边界 + **AST 静态扫描(零出网零执行)** + 跨端常量核对。

**e2e**(33 项):管理链路(建/查重/列表/启停)+ 对外服务(命中/变量回显/404 矩阵/
启停生效/app 边界)+ preview + 权限(私有项目隔离)+ 删除即失效。

## 7. 已知限制

- 对外 mock 服务无鉴权(半公开):勿放真实凭据;已知即可调用
- `app` 重复时命中最早创建的项目(配置页就地提示)
- 同名 query 参数只取第一个;body 变量仅 JSON 请求体
- 不做命中统计/限流(MVP 范围外)
- mock 响应是字符串渲染,不做结构化 JSON 类型保持(bool/数字会文本化)

## 8. 实现记录(与设计的偏差/完善)

| # | 事项 | 决策 |
|---|---|---|
| 1 | 匹配排序补「方法具体度」 | 原设计排序只有 path_type → priority → id;实测发现 ANY 与具体方法同命中时无确定性语义。补 key:`具体方法(0) > ANY(1)`,全排序仍确定。`data-model.md` §3 同步更新 |
| 2 | 变量正则收紧 body 段间非空 | 原 `body\.[A-Za-z0-9_.-]+` 允许 `a..b` 空段;收紧为 `[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*`。query 键名保留点(字面量) |
| 3 | 未知变量校验覆盖 `$randomInt`/`$timestamp` | 原只查 `$request.*` 形态,`$randomInt` 漏网;改为扫描所有「`$` + 字母开头」token,非白名单一律拒绝;`$5`/`${...}` 放行 |
| 4 | 渲染值类型归一 | `re.sub` 回调须返回 str;bool→`true/false`(保持 JSON 字面量)、数字→str、dict/list→JSON |
| 5 | 分页契约结构 | 契约初稿写 `{total, list}`,实际平台 `success_with_size` 是 `{data: [], total}`;契约 §1.1 已修正 |
| 6 | e2e 建表 | 直接调路由函数不触发启动 `create_all`;e2e 开头 `Base.metadata.create_all`(async_engine) |
| 7 | e2e 项目名长度 | `pity_project.name` 是 String(16),`mock-e2e-{13位时间戳}` 超长;改用 `me2e-{6位}` |
| 8 | e2e 调用 `mock_entry` 的 full_path | 直接调函数时 full_path 必须含 app 前缀(`app/api/user/1`,与 `/mock/{full_path:path}` 路由语义一致) |

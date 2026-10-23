# 数据工厂 · 技术设计

> 状态：已实现（v1）
> 目标平台：AIFullStackTesting backend（FastAPI + SQLAlchemy）
> 前端：`frontend/src/pages/datafactory/`
> 入口文档：[`backend/CLAUDE.md` § 数据工厂](../CLAUDE.md)（只保留硬约束，细节在本文）

---

## 0. 一句话

给一组**字段生成规则**，批量产出测试数据，然后落到三个出口之一：**写进目标数据库**、**导出成文件**、**绑定成用例的测试数据跑数据驱动**。

---

## 1. 定位与边界

数据工厂有三种常见定位，v1 只做第一种：

| 定位 | v1 |
|---|---|
| 造数工厂（规则 → 数据 → 落地） | ✅ |
| 数据资产治理（导入/清洗/脱敏/版本） | ❌ v2 |
| Mock 工厂（按契约动态返回响应） | ❌ v2（`/mock` 路由本身也还没实现） |

**明确不做的**：生成批次记录表、写库回滚、场景市场（收藏/最热/最赞）、MongoDB 落地、CSV/Excel 导出、`case_type=2` 数据工厂用例。

---

## 2. 现状调研：复用了什么

数据工厂最大的设计红利是平台已有这些能力，所以 **v1 没有引入新的执行机制，只新增了"数据的来源"**。

### 2.1 `pity_testcase_data` + `Executor.run_single` — 现成的数据驱动

`backend/app/core/executor.py` 的 `run_single`：

```python
test_data = await PityTestcaseDataDao.list_testcase_data_by_env(env, case_id)
if not test_data:
    # 没绑数据 → 跑一次"默认数据"
else:
    # 每条数据跑一次, 并发
    await asyncio.gather(*(Executor.run_with_test_data(..., Executor.get_dict(x.json_data), ...) for x in test_data))
```

每条 `json_data`（扁平 dict）经 `case_params.update(req_params)` 注入用例参数池，然后由 `Render`（Jinja2，`${变量}` 语法）渲染进 `body` / `url` / `request_headers`。

**结论**：数据工厂只要产出「N 行 key-value」，写进 `pity_testcase_data` 就自动接上数据驱动，不需要碰执行引擎。

### 2.2 其他复用

| 能力 | 复用点 |
|---|---|
| 数据库连接池 | `app.models.db_helper`（`DatabaseHelper`，按 host:port:库 缓存 AsyncEngine） |
| 反射目标表结构 | `DbConfigDao.load_table` 提供了 `run_sync` + `MetaData` 的写法参照 |
| 变量渲染 | `app/core/render.py` 的 `Render`（`${...}` 语法），`PityFunction` 的 `now()` / `uuid()` / `random_int()` |
| AI 对话 | `app/core/ai_client.py`（OpenAI 兼容，厂商/模型来自 `pity_ai_vendor` / `pity_ai_model`） |
| 文件下载 | `PityResponse.file()`（自带 `BackgroundTask` 删临时文件） |
| 操作日志 | `Mapper.insert_log` + 模型的 `__tag__` / `__fields__` / `__alias__` |

---

## 3. 核心设计决策

### 3.1 不自造"用例联动"，直接产出数据驱动的输入

没有做"数据工厂用例 → 产出变量 → 下游用例消费"这条新链路，而是让数据工厂写 `pity_testcase_data`。

**理由**：执行引擎已有的 `run_single` 就是这个语义，再造一套等于维护两份执行逻辑。**代价**是 `pity_testcase_data` 变成了双写方（原有 UI 只有 insert/update/delete 且没页面在用，见 §11）。

### 3.2 不建"生成批次表"

规则 + seed 唯一确定一批数据，所以"重放"不需要落库。写库/导出/绑定时后端按 `dataset_id + count + seed` **重新生成一遍**，得到的和预览完全一致。

**收益**：零状态、零缓存，不用把上万行塞进请求体。**代价**：`PityFunction.now()` 这类取真实时间的函数无法重放（见 §5.3）。

### 3.3 AI 只翻译规则，不生成数据

AI 的产出是**结构化的字段规则 JSON**，真正的数据由确定性内核生成。

**理由**：让 AI 直接吐数据会有幻觉（格式错、值不合理、无法保证唯一性），而且每跑一次成本都不同。规则是可审阅、可重放的。

### 3.4 seed 确定性怎么保证

所有随机源必须收敛到同一个带种子的实例：

- `DataGenerator.__init__` 里 `self.faker = Faker(locale)` + `faker.seed_instance(seed)`，然后 `self.rng = self.faker.random`
- `random` / `template` / `regex` / `date` 的随机全部走 `self.rng`
- **`PityFunction.uuid()` 和 `random_int()` 走的是 OS 熵和全局 `random`，不随 seed 重放** —— 所以在 Jinja2 渲染上下文里用带种子的版本遮蔽它们（Jinja2 上下文优先于 globals）：

```python
self._render_globals = {'uuid': self._next_uuid, 'random_int': self._random_int}
```

`PityFunction.now()` 依然取真实时间，文档里明确标注为不可重放。

---

## 4. 数据模型

`pity_data_factory`（`app/models/data_factory.py`，继承 `PityBase`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | String(64) | 数据集名，`(env, name, deleted_at)` 唯一 |
| `env` | INT | 环境 id |
| `project_id` | INT | 所属项目，可空 |
| `database_id` | INT | 目标库配置 id → `pity_database_info.id` |
| `table_name` | String(64) | 目标表名 |
| `columns` | TEXT | **字段规则 JSON**（见 §5） |
| `count` | INT | 默认生成条数 |
| `seed` | INT | 随机种子，`0` 表示每次随机 |
| `remark` / `status` | — | 备注 / 启用状态 |

> 用 `database_id` 而不是「环境 + 库名」定位目标库：库名是用户自定义的描述名，可能重名或被改名，主键唯一。

**为什么不建批次表**：见 §3.2。

---

## 5. 字段规则 JSON 规范（前后端契约）

`columns` 字段存的就是这个结构，**这是前后端唯一的契约**，两端常量必须同步：

- 后端：`app/core/data_factory/generator.py` 的 `DATA_FACTORY_KINDS` / `FAKER_PROVIDERS`
- 前端：`frontend/src/consts/datafactory.ts` 的 `RULE_KINDS` / `FAKER_PROVIDERS`

```json
{
  "columns": [
    { "name": "user_id", "type": "int",
      "rule": { "kind": "sequence", "start": 1, "step": 1 },
      "unique": true, "nullable": false, "default": null, "comment": "用户ID" }
  ]
}
```

### 5.1 约束

- `name` 必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`（要能被 `${字段名}` 引用）
- `type` ∈ `string` / `int` / `float` / `bool`
- `unique` 只在字段本身随机、确实要求不重复时设 `true`；**引用了 `${}` 的字段不要设 unique**，让被引用的字段 unique 即可

### 5.2 `rule.kind` 全集（11 种）

| kind | 参数 | 说明 |
|---|---|---|
| `fixed` | `value` | 固定值 |
| `random` | `min`, `max`, `decimals` | 随机区间；`decimals` 只对 float 有意义 |
| `enum` | `values[]` | 枚举，逐行轮转 |
| `sequence` | `start`, `step` | 序列递增 |
| `uuid` | `prefix` | 带种子的 UUID |
| `template` | `template` | 字符模板：`#` 数字、`?` 字母、`*` 数字或字母 |
| `regex` | `pattern` | 轻量正则生成（见 §8.2） |
| `reference` | `from` | 引用同一批次里另一个字段的值 |
| `faker` | `provider`, `args` | Faker provider，**白名单 57 个**，防止 AI 翻译出不存在的名字 |
| `func` | `expr` | 内置函数，如 `${random_int(1,100)}`、`${uuid()}` |
| `date` | `start`, `end`, `format` | 随机日期，`start`/`end` 支持 `now`、`-30d`、`+2h`、`2024-01-01` |

### 5.3 变量引用

统一复用平台既有的 `${...}`（Jinja2），不另造一套：

- `${字段名}` —— 引用**本行**已生成的字段
- `${函数()}` —— 调 `PityFunction`（`now()` / `uuid()` / `random_int()` / `time_before()` …）

引用会让字段产生依赖，生成前会做**拓扑排序**，引用成环直接报错。

---

## 6. 模块拆分与数据流

```
app/core/data_factory/
├── generator.py   生成内核: rules + seed → N 行 dict
├── regex_gen.py   轻量正则生成器(不引 exrex)
├── writer.py      写库通道: reflection → 参数化批量 insert
├── exporter.py    导出 JSON / SQL 临时文件
└── ai_parser.py   自然语言 → 字段规则(含 prompt 与 JSON 解析)

app/crud/data_factory/DataFactoryDao.py   数据集 CRUD + bind_case
app/routers/datafactory/dataset.py        12 个接口
app/schema/data_factory.py                Pydantic 表单
```

**取数入口 `_resolve_rows(form, dataset)`** 是四个动作（生成/导出/写库/绑定）的公共前菜：

1. 前端直传 `rows`（用户在预览表格里手动改过）→ 原样用
2. 否则按 `dataset_id + count + seed` 重新生成（seed 可重放，所以结果与预览一致）

---

## 7. API 设计

前缀 `/datafactory`，全部走 `PityResponse` 的 `{code, data, msg}`，`code=0` 成功。

| 方法 | 路径 | 权限 |
|---|---|---|
| GET | `/dataset/list` | `Permission()` |
| GET | `/dataset/detail` | `Permission()` |
| POST | `/dataset/insert` | `Permission()` |
| POST | `/dataset/update` | `Permission()` |
| GET | `/dataset/delete` | `Permission()` |
| POST | `/generate` | `Permission()` |
| POST | `/export` | `Permission()` |
| POST | `/write-db` | `Permission(Config.MANAGER)` |
| POST | `/bind-case` | `Permission()` |
| POST | `/ai/parse` | `Permission()` |
| GET | `/table/list` | `Permission()` |
| GET | `/table/columns` | `Permission()` |

`/write-db` 提到 MANAGER：它能往任意已配置的库写数据，比其余动作风险高。

**表结构接口不复用 `/online/tables/list`**：那个返回「环境 → 库 → 表 → 列」的嵌套树，前端解析别扭。数据工厂的接口返回**扁平**的表名列表 / 列清单。

---

## 8. 落地通道细节

### 8.1 写库

复用 `db_helper.get_connection(sql_type, host, port, user, pwd, db)` 拿 `AsyncEngine`。

**两个坑**（都在 `writer.py`）：

1. **AsyncEngine 不能直接 reflection**，必须走 `run_sync` 绿桥：
   ```python
   async with engine.connect() as conn:
       def _reflect(sync_conn, meta):
           meta.reflect(bind=sync_conn)     # 不传 bind 会抛 "MetaData object is not bound"
           return [t.name for t in meta.sorted_tables]
       tables = await conn.run_sync(_reflect, MetaData())
   ```
2. **`column.autoincrement` 是三态**：`True` / `False` / `'auto'`。`'auto'` 是"交给 SQLAlchemy 自己判"，**不是"是自增"**。判定逻辑见 `writer.is_autoincrement()`（单列整数主键才算自增）。写成 `in (True, 'auto')` 会把 VARCHAR/TIMESTAMP 全判成自增。

写入用 SQLAlchemy Core 的参数化 `insert()`（不拼 SQL 字符串），按 `BATCH_SIZE = 500` 分批，一个事务提交。

规则里的字段名与数据库真实列名做**不区分大小写匹配**，匹配不上的列会被跳过并在响应里回报 `skipped` 列表。

**只支持 MySQL / PostgreSQL** —— `DatabaseEnum` 目前只有这两个，`PityDatabase.sql_type` 注释里的 mongo 从未实现（`get_jdbc_url` 遇到就抛异常，requirements 里也没有 pymongo）。

### 8.2 正则生成器

`regex_gen.py` 自研，不引入 `exrex`。支持：字面量、`\d \D \w \W \s \S`、`.`、字符类 `[0-9]` / `[^0-9]`、分组 `(?:...)`、或分支 `|`、量词 `* + ? {n} {n,m}`。`^` `$` 生成时忽略。

量词重复次数上限 `MAX_REPEAT = 20`（防止 `{0,1000000}` 打爆内存），嵌套深度上限 `MAX_DEPTH = 10`。

### 8.3 唯一性约束

**去重必须做在「解析完 `${}` 之后的最终值」上**。

曾经的 bug：去重放在解析前，`email = ${mobile}@qq.com` 每行产出的都是同一个字面量 `"${mobile}@qq.com"`，第 2 行就判重失败，且重试永远得到同一个值 → 100 次后报错。AI 生成的规则直接跑不起来。

修复后额外做了「重试是否有意义」的判定（`DataGenerator._can_retry`）：`fixed` / `reference`、以及引用了本行其他字段的 `template` / `func`，重试换不出新值，只试 1 次就给出可操作的报错，而不是空跑 100 次。

---

## 9. AI 规则翻译

`ai_parser.py` 的职责是把用户的一句话变成 §5 的 JSON。

- `SYSTEM_PROMPT` 里给出 11 种 kind 的完整参数说明 + 示例，并要求**只输出 JSON**
- 解析：先剥 ```` ```json ```` 包裹 → `json.loads`；失败则用括号计数法提取第一个完整 `{...}` 块
- 校验：逐字段过 `DataFactoryColumn`，**非法字段丢弃并作为 `warnings` 返回**，不整批失败
- 调用走 `ai_client.complete_chat()`（非流式，`COMPLETE_TIMEOUT = 120s`），因为要的是完整 JSON，流式增量没用
- 厂商/模型选择复用 `/ai/chat/models` 返回的聚合列表，不在数据工厂里另做一套

---

## 10. 回归与测试

后端没有 pytest 框架，验证走独立脚本：

```bash
cd backend
.venv/bin/python scripts/datafactory_selftest.py     # 内核单测, 不需要起后端
.venv/bin/python scripts/datafactory_e2e.py          # 端到端, 默认连 127.0.0.1:7777
```

| 脚本 | 断言数 | 覆盖 |
|---|---|---|
| `selftest` | 49 | 生成内核、seed 重放、唯一性约束、错误处理、导出器、AI 规则解析、自增列判定 |
| `e2e` | 51 | 数据集 CRUD、生成与 seed 重放、导出、写库、绑定用例、AI 规则翻译、权限、**数据驱动端到端** |

**前置条件**：`selftest` 只需 MySQL 能连（import `app.models` 会触发建库）；`e2e` 需要后端在跑。

**数据驱动端到端**那一段是整条链路的验收点：绑 4 条 → `/request/run` 跑 4 次 → 校验每次请求 body 里的 `${变量}` 都被替换成**对应行**的值，且 4 次请求值互不相同。

**测试残留**：`e2e` 每轮注册一个 `e2e_*` 账号（写库那段会临时提权为 MANAGER）、建一张 `e2e_datafactory` 临时表，两者都不清理；数据集和临时用例会在结束时删掉。

---

## 11. 已知缺口与 v2 待办

### 11.1 既有平台缺口（不是数据工厂引入的，但会挡住使用）

1. **`pity_testcase_data` 没有列表接口** —— 后端只有 insert/update/delete，前端 service 也定义了但没有任何页面在用。所以「绑定到用例」之后**看不到绑了什么**，`e2e` 是直接查库验证的。加一个 `GET /testcase/data/list?case_id=&env=` 即可补齐。
2. **`Card bordered` 已废弃**（antd 5.29 警告）—— 数据工厂沿用了既有写法：仓库里 9 个既有文件用了 `bordered=`（`Dashboard/Workspace.jsx`、`ApiTest/TestCaseDirectory.jsx`、`BuildHistory/ReportDetail.jsx`、`components/Postman/PostmanForm.jsx`、`components/Online/SqlOnline.jsx` 等），属于全站 antd 升级项，不在本模块单独改。
3. **前端 `tsc --noEmit` 失效** —— 详见 `frontend/CLAUDE.md`「TypeScript 检查当前是失效的」。改数据工厂前端时要用 `npx -y -p typescript@5.9.2 tsc -p tsconfig.json --noEmit` 验收。

### 11.2 本模块自身的待办

- 生成批次记录表 + 写库回滚（当前写库无审计、不可撤销）
- 场景市场：收藏 / 最热 / 最赞 / 团队共享（占位页原本画了这套 UI，需要成员权限模型支撑）
- MongoDB 落地（需引入 pymongo 或 motor，并补 `DatabaseEnum`）
- CSV / Excel 导出（当前只有 JSON / SQL）
- `case_type=2` 数据工厂用例（用例本身作为数据生产节点，需改执行引擎）
- Mock 工厂（`/mock` 路由本身也还没实现）

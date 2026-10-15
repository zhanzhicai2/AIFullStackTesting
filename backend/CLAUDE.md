# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 启动命令

```bash
# 一次性创建 venv(首次)
uv venv --python 3.10
source .venv/bin/activate

# 启动后端服务（主流本机方式;由 pity.py 调 uvicorn.run("main:pity")）
uv pip install -r requirements.txt    # 首次或依赖变更后
python pity.py

# 开发模式热重载（代码改动自动重启;与 python pity.py 二选一）
uvicorn main:pity --reload

# Alembic 迁移
alembic revision --autogenerate -m "描述"          # 生成数据库迁移
alembic upgrade head                              # 执行迁移
```

环境变量 `pity_env=dev`（默认）读 `conf/dev.env`，`pity_env=pro` 读 `conf/pro.env`。

**Python 环境**：用 `uv venv` 创建独立虚拟环境（`backend/.venv/`），不要用 conda，详见 [`DEV_SETUP.md`](./DEV_SETUP.md)。首个注册用户自动成为超管。

## 项目结构

```
backend/
├── main.py                 # 模块定义：路由注册 + startup 钩子 + WebSocket 端点（被 pity.py 加载）
├── pity.py                 # 启动器：uvicorn.run("main:pity", host=Config.SERVER_HOST, port=Config.SERVER_PORT)
├── config.py               # 配置类（BaseConfig + DevConfig/ProConfig）
├── proxy.py                # mitmproxy 启动入口（PROXY_ON=True 时由 main.py 调用）
├── alembic.ini             # Alembic 迁移配置
├── requirements.txt        # Python 依赖
├── conf/                   # 环境配置
│   ├── dev.env             # 开发环境（MySQL、Redis、OAuth 等）
│   └── pro.env             # 生产环境
├── pity_proxy/             # mitmproxy 录制 / Mock 服务模块（PROXY_ON / MOCK_ON 开关）
│   ├── mock.py             # PityMock：内置 Mock 服务（main.py 在 MOCK_ON=True 时启动）
│   └── record.py           # PityRecorder：HAR / mitmproxy 用例录制（PROXY_ON=True 时启动）
├── app/
│   ├── routers/            # API 路由（按模块目录组织）
│   │   ├── auth/           # 认证（注册、登录、GitHub OAuth）
│   │   ├── project/        # 项目管理
│   │   ├── testcase/       # 测试用例
│   │   ├── config/         # 配置管理
│   │   ├── online/         # 在线工具（SQL、Redis）
│   │   ├── workspace/      # 工作空间
│   │   ├── oss/            # 对象存储
│   │   ├── notification/   # 消息通知
│   │   ├── operation/      # 操作日志
│   │   └── request/        # HTTP 请求 / Mock 录制
│   ├── models/             # SQLAlchemy 数据模型（继承 PityBase）
│   ├── crud/               # DAO 层（@ModelWrapper + @connect 模式）
│   ├── schema/             # Pydantic v1 验证模型（注意不是 schemas）
│   ├── core/               # 核心业务逻辑（用例执行引擎、参数解析）
│   ├── middleware/          # 中间件（CORS、错误处理、请求日志）
│   ├── utils/              # 工具函数（JWT、Redis、通知等）
│   ├── enums/              # 枚举类型
│   ├── exception/          # 自定义异常
│   └── handler/            # 处理器
├── statics/                # 前端构建产物（生产部署）
├── templates/              # HTML 模板（测试报告）
├── logs/                   # 日志文件
└── alembic/                # 数据库迁移脚本
```

## 架构概览

应用入口 `main.py` 注册路由并启动 Redis、APScheduler 定时任务、数据库自动建表三个 startup 事件。

### 请求处理链

```
Request → CORS Middleware → Error Middleware → Router → DAO (connect装饰器管理session) → Response
```

### 数据库层

- **Model**：所有模型继承 `PityBase`（`app/models/basic.py`），自动提供 `id`、`created_at`、`updated_at`、`deleted_at`（软删除，BIGINT 时间戳）、`create_user`、`update_user`
- **DAO**：`app/crud/__init__.py` 中的 `Mapper` 基类提供通用 CRUD，子类通过 `@ModelWrapper(Model)` 装饰器绑定模型
- **Session 管理**：`@connect` 装饰器自动获取/复用 `AsyncSession`，支持事务参数 `@connect(True)`
- **缓存**：`@RedisHelper.cache("dao")` 自动缓存查询结果，`@RedisHelper.up_cache("dao")` 写操作后自动清缓存

### 路由层

- 路由按模块组织在 `app/routers/` 下，每个模块的 `__init__.py` 汇聚子路由导出 `router`
- 认证：`Depends(Permission())` 从 `Authorization` Header 解析 JWT，`Permission(role=Config.ADMIN)` 可限定角色
- 响应统一通过 `PityResponse.success()` / `PityResponse.failed()` 返回 `{code, msg, data}` 格式

### 测试用例执行引擎

`app/core/executor.py` 是核心执行器，支持 5 种构造器类型（映射在 `construct_type` 字典中）：
- **HTTP** — `HttpConstructor`：发送 HTTP 请求
- **SQL** — `SqlConstructor`：执行数据库查询
- **Redis** — `RedisConstructor`：执行 Redis 命令
- **Python 脚本** — `PythonConstructor`：执行自定义 Python
- **测试用例** — `TestcaseConstructor`：嵌套调用其他用例

参数提取通过 `app/core/paramters/` 下的解析器（JSONPath、正则、状态码、KV）实现，全局配置解析通过 `app/utils/gconfig_parser.py`（String/JSON/YAML）。

### 配置（`config.py`）

`BaseConfig` 继承 pydantic `BaseSettings`，从 `.env` 文件加载。关键配置：
- MySQL/Redis 连接信息
- `REDIS_ON`：关闭 Redis 后定时任务可能重复执行
- `MOCK_ON` / `PROXY_ON`：Mock 服务器和代理开关

## 新增 API 标准流程

1. **Model** — `app/models/` 创建模型类，继承 `PityBase`
2. **DAO** — `app/crud/` 下对应子目录创建 DAO 类，用 `@ModelWrapper(YourModel)` 装饰，继承 `Mapper`
3. **Schema** — `app/schema/` 创建 Pydantic 验证模型
4. **Router** — `app/routers/` 创建路由，用 `APIRouter` 定义端点
5. **Register** — 在 `main.py` 中 `pity.include_router()` 注册

## 响应格式

```json
{"code": 0, "data": {}, "msg": "操作成功"}
```

| code | 含义 |
|------|------|
| 0 | 成功 |
| 101 | 参数错误（RequestValidationError 自动处理） |
| 110 | 业务异常 |
| 401 | 未登录（AuthException） |
| 403 | 无权限（PermissionException） |

> 成功码沿用 `0`（中文 API 常见约定，如 Java R / 阿里部分开放平台），不是 HTTP 200 的镜像。码表是业务码表，不是 HTTP 风格 —— `101` / `110` 是平台自定义编号，仅 `401` / `403` 数值上与 HTTP 重合。如果有人提议把成功码改成 `200` 来"对齐 HTTP"，请拒绝：
>
> - 前端 service / dva model 全量依赖 `code === 0` 判定，改动面大、易漏；
> - HTTP 状态码固定 200，body 再来 `code: 200` 反而要区分是哪一层；
> - 其他码未与 HTTP 对齐，"半对齐"反而引入新混乱。
>
> 任何新增业务码遵循同一张表（递增、与现有 0 / 101 / 110 同区段），不要混入 200/300/500 这类 HTTP 段。

## 日志

使用 Loguru，通过 `logger.bind(name=Config.PITY_INFO)` / `Config.PITY_ERROR` 分流：
- `logs/pity_info.log` — DEBUG 及以上
- `logs/pity_error.log` — WARNING 及以上

## 数据库迁移

项目配置了 Alembic（`alembic.ini` + `alembic/`），但启动时也会通过 `Base.metadata.create_all` 自动建表。Model 的 `__fields__`、`__tag__`、`__alias__`、`__show__` 类属性控制操作日志的展示字段和关联关系。

## 关键约定

- DAO 文件命名 `XxxDao.py`，放在 `app/crud/` 对应子目录下
- 前端 `localStorage` 中 JWT token 的 key 为 `pityToken`
- 所有 HTTP 响应 code 都在 200，业务错误通过 body 的 `code` 字段区分
- `app/crud/__init__.py` 启动时通过 `importlib` 动态导入所有 DAO 模块
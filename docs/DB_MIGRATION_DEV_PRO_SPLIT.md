# Dev=MySQL / Pro=SQLite 数据库后端切分

> 一句话:**让本地开发继续用 MySQL,服务器生产用 SQLite**,省 400-500MB 内存。改动只动配置层 + 容器 env,业务代码 0 改动。
>
> 本文档对应 `DEPLOY_RUNBOOK.md` 的"后续优化"里"内存优化"那一条 — 它是替代性方案(用 `Base.metadata.create_all` + 不同 URI 注入,而不是保留 MySQL 但调连接池)。

---

## 1. 调研结果(3 个文件的发现)

### 1.1 `app/models/__init__.py`(Base + async_engine 源头)

发现的实际代码:

| 行 | 内容 | 影响 |
|---|---|---|
| 13-26 | `create_database()` 用 `mysql+mysqlconnector://` 同步建库 | **MySQL-only**,SQLite 不需要 |
| 26 | `create_database()` 在模块顶层 import 时立即执行 | Pro 模式也会触发,需要早退 |
| 31 | `async_engine = create_async_engine(Config.ASYNC_SQLALCHEMY_URI, ...)` | 取决于 URI 字段值 |
| 36-43 | `async_session` 工厂 | 不受 driver 影响 |
| 80 | `await session.execute("select 1")` | 字符串字面,SQLite OK |
| 86 | `get_jdbc_url` 里的 `mysql+aiomysql://` | 这是**在线 SQL 工具**(用户连外部 DB),跟后端自己的 DB 无关 |

**关键改造**:`create_database()` 顶层调用在 pro / sqlite 模式必须早退。

### 1.2 `backend/main.py`(startup events)

| startup hook | 内容 | 影响 |
|---|---|---|
| `init_redis`(104-119)| `await RedisHelper.ping()`,失败 raise;有 `Config.REDIS_ON` fallback | 如果 REDIS_ON=False 只 warn — pro 配置 Redis 容器就保留,不动 |
| `init_scheduler`(122-137)| `SQLAlchemyJobStore(url=Config.SQLALCHEMY_DATABASE_URI)` | **SQLAlchemyJobStore 跨后端 OK**,URI 切对就行,代码不动 |
| `init_database`(140-151)| `await create_table()` — 来自 `app.crud`,是 `Base.metadata.create_all` 的封装 | SQLite 支持,无问题 |

**关键发现**:`init_scheduler` 用同一个 SQLALCHEMY_DATABASE_URI — 也就是说 dev MySQL 的 job 和 pro SQLite 的 job 各自走自己的存储。**不需要单独 scheduler 配置**。

### 1.3 `backend/requirements.txt`

| 行 | 包 | 用途 | 改后 |
|---|---|---|---|
| 2 | `mysql-connector-python==8.0.26` | 同步 mysql + `create_database` | **dev 用,保留** |
| 12 | `aiomysql` | 异步 mysql | **dev 用,保留** |
| 14 | `psycopg2-binary` | 同步 postgres(在线工具用) | 保留 |
| 27 | `asyncpg` | 异步 postgres(在线工具用) | 保留 |
| 28 | `pymysql` | 看着没用 — 保留安全点 | 不动 |
| - | **`aiosqlite`**(未在)| **新增** — pro SQLite 异步 driver | **加进去** |

---

## 2. 改动 spec(完整文件清单)

### 2.1 改: `backend/requirements.txt`

```diff
 pyjwt==2.1.0
 mysql-connector-python==8.0.26
+aiosqlite>=0.18.0
 requests~=2.23.0
 sqlalchemy==1.4.47
 ...
```

> 不要因为"用不上"删 `mysql-connector-python` / `aiomysql` — dev 模式仍然用 MySQL。

### 2.2 改: `backend/config.py`

把硬拼装的 URI 改成**直接读 env 字段**(dev/pro 各 env 自带):

```diff
 class BaseConfig(BaseSettings):
     LOG_DIR = ...
     SERVER_HOST: str = "0.0.0.0"
     SERVER_PORT: int

     HEARTBEAT: int = 48

     MOCK_ON: bool
     PROXY_ON: bool
     PROXY_PORT: int
-    MYSQL_HOST: str
-    MYSQL_PORT: int
-    MYSQL_USER: str
-    MYSQL_PWD: str
-    DBNAME: str
+    MYSQL_HOST: str = None       # 给 DevConfig 可选保留
+    MYSQL_PORT: int = None
+    MYSQL_USER: str = None
+    MYSQL_PWD: str = None
+    DBNAME: str = None
     # URI 由 env 直接提供(dev 给 mysql-*, pro 给 sqlite)
+    SQLALCHEMY_DATABASE_URI: str
+    ASYNC_SQLALCHEMY_URI: str
     ...
```

底部的 **拼装逻辑直接删除**:

```diff
-# init sqlalchemy (used by apscheduler)
-Config.SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://{}:{}@{}:{}/{}'.format(
-    Config.MYSQL_USER, Config.MYSQL_PWD, Config.MYSQL_HOST, Config.MYSQL_PORT, Config.DBNAME)
-
-# init async sqlalchemy
-Config.ASYNC_SQLALCHEMY_URI = f'mysql+aiomysql://{Config.MYSQL_USER}:{Config.MYSQL_PWD}' \
-                              f'@{Config.MYSQL_HOST}:{Config.MYSQL_PORT}/{Config.DBNAME}'
```

> 现在 URI 字段必填 — pydantic 启动时如果 env 没读到,直接报错(`ValidationError`)。这是好事:dev/pro 任何一个缺字段都会被启动直接发现。

### 2.3 改: `backend/app/models/__init__.py`

在 `create_database()` 顶部加 driver 早退:

```diff
 def create_database():
     """
     当db不存在时，自动创建db
+    SQLite 是文件型数据库,不需要 "create database" 这步(只要路径父目录存在即可)
     """
+    # pro 环境是 SQLite URI,跳过;dev 环境是 mysql URI,正常执行
+    if 'sqlite' in Config.ASYNC_SQLALCHEMY_URI:
+        return
     engine = create_engine('mysql+mysqlconnector://{}:{}@{}:{}'.format(
         Config.MYSQL_USER, Config.MYSQL_PWD, Config.MYSQL_HOST, Config.MYSQL_PORT), echo=True)
     with engine.connect() as conn:
         conn.execute("CREATE DATABASE IF NOT EXISTS pity default character set utf8mb4 collate utf8mb4_unicode_ci")
     engine.dispose()
```

> 比 `if PITY_ENV == 'pro'` 更稳 — 不依赖 PITY_ENV 当前是模块顶部还是已经求值。

### 2.4 改: `backend/conf/dev.env`

dev 模式**字段值跟原来一样**,只是多 2 行明确写入 URI:

```diff
 # MySQL config
 MYSQL_HOST="127.0.0.1"
 MYSQL_PORT=3306
 MYSQL_USER="root"
 MYSQL_PWD="12345678"
 DBNAME="pity"

+# --- SQLAlchemy URIs(dev 用 mysql) ---
+SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://root:12345678@127.0.0.1:3306/pity"
+ASYNC_SQLALCHEMY_URI="mysql+aiomysql://root:12345678@127.0.0.1:3306/pity"
+
 # Redis config
 REDIS_ON=True
 ...
```

### 2.5 改: `backend/conf/pro.env`

pro **删 5 行 MYSQL_*,改用 SQLite**(这里我把 pro.env 也列一下,具体基于你自己现有的 pro.env 微调):

```diff
-# MySQL config
-MYSQL_HOST="127.0.0.1"
-MYSQL_PORT=3306
-MYSQL_USER="root"
-MYSQL_PWD="12345678"
-DBNAME="pity"
+# --- pro 改用 SQLite(本地 pro 测用 ./pity.db,容器 pro 用 /data/pity.db) ---
+SQLITE_PATH="/data/pity.db"
+SQLALCHEMY_DATABASE_URI="sqlite:////data/pity.db"
+ASYNC_SQLALCHEMY_URI="sqlite+aiosqlite:////data/pity.db"

 # Redis config
 REDIS_ON=True
 ...
```

> SQLite URI 三斜杠绝对路径:
> - `sqlite:////data/pity.db` = 文件路径 `/data/pity.db`
> - 末尾是 `/sqlite+aiosqlite:` 模式,正确语法
>
> 注意路径前缀 — 三斜杠(`sqlite:///`)+ 绝对路径(`/data/pity.db`) = 四斜杠。`sqlite:///./pity.db` 则相对当前目录。

### 2.6 改: `backend/ops/dev.env.ops`(容器用的版本)

跟 `dev.env` 改动一致,只是文件路径在容器里:

```diff
 MYSQL_HOST="mysql"               # docker compose service name
 MYSQL_PORT=3306
 MYSQL_USER="root"
 MYSQL_PWD="Pitytester666666"
 DBNAME="pity"

+SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://root:Pitytester666666@mysql:3306/pity"
+ASYNC_SQLALCHEMY_URI="mysql+aiomysql://root:Pitytester666666@mysql:3306/pity"
```

### 2.7 改: `backend/ops/pro.env.ops`(新增文件,同样改)

```bash
SQLITE_PATH="/data/pity.db"
SQLALCHEMY_DATABASE_URI="sqlite:////data/pity.db"
ASYNC_SQLALCHEMY_URI="sqlite+aiosqlite:////data/pity.db"

pity_env=pro

# 保留 Redis / Mock / Proxy 配置(pro 容器继续跑 Redis)
REDIS_ON=True
REDIS_HOST="redis"
REDIS_PORT=6379
REDIS_PASSWORD="123456"
MOCK_ON=False
PROXY_ON=False
PROXY_PORT=7777

# 鉴权
CLIENT_ID="..."
SECRET_KEY="..."

# Server
SERVER_HOST="0.0.0.0"
SERVER_PORT=7777

# ETCD
ETCD_ENDPOINT=etcd:2379
```

> 注:`ETCD_ENDPOINT` 容器化后还得有 etcd 服务跑在 compose 里 — 如果你不去掉 etcd,容器编排继续保留该容器。

### 2.8 不动: 业务代码 / Alembic / 路由

| 类别 | 文件 | 为什么不动 |
|---|---|---|
| ORM models | `app/models/*` | SQLAlchemy 类型抽象 |
| DAO | `app/crud/**` | 取决于 Session 工厂,Session 工厂换 URI 不需要 DAOs 知道 |
| Router | `app/routers/**` | 业务逻辑零 DB 切换痕迹 |
| Redis 缓存 | `app/middleware/RedisManager.py` | Redis 保留不动 |
| APScheduler | `main.py` `init_scheduler` | URI 切对就行,SQLAlchemyJobStore 跨后端通用 |
| Alembic | `backend/alembic/**` | **只在本 dev 跑**,pro 走 `Base.metadata.create_all` |

### 2.9 不动的副作用(`mysql_collate`、`mysql_default_charset` 等)

你之前扫到的 2 个 alembic migration(`5ac10ab42c29`、`18e3b2701a47`)有 `mysql.VARCHAR` / `mysql_collate` 等 MySQL-only 调用 —— 这些 migration **只在 dev MySQL 跑**,pro SQLite 不跑 alembic,**完全规避这个坑**。

---

## 3. 改动顺序建议(3 个独立 commit)

### Commit 1:`chore(backend): 引入 SQLALCHEMY/ASYNC_URI 字段由 env 注入`

```diff
# backend/config.py
-    MYSQL_HOST: str
-    MYSQL_PORT: int
-    MYSQL_USER: str
-    MYSQL_PWD: str
-    DBNAME: str
+    MYSQL_HOST: str = None
+    MYSQL_PORT: int = None
+    MYSQL_USER: str = None
+    MYSQL_PWD: str = None
+    DBNAME: str = None
+    SQLALCHEMY_DATABASE_URI: str
+    ASYNC_SQLALCHEMY_URI: str
...
-Config.SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://...'
-Config.ASYNC_SQLALCHEMY_URI = 'mysql+aiomysql://...'
+Config.SQLALCHEMY_DATABASE_URI  # 从 env 读
+Config.ASYNC_SQLALCHEMY_URI     # 从 env 读

# backend/conf/dev.env
+SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://root:12345678@127.0.0.1:3306/pity"
+ASYNC_SQLALCHEMY_URI="mysql+aiomysql://root:12345678@127.0.0.1:3306/pity"
```

> **验证**:本地 `PITY_ENV=dev python main.py`,应该跟之前完全一样;断网 / mysql 启不来的话,会报清晰错误而不是奇怪的 default。

### Commit 2:`chore(backend): pro env 切 SQLite URI;create_database 在 sqlite 早退`

```diff
# backend/conf/pro.env
+SQLITE_PATH="/data/pity.db"
+SQLALCHEMY_DATABASE_URI="sqlite:////data/pity.db"
+ASYNC_SQLALCHEMY_URI="sqlite+aiosqlite:////data/pity.db"
-MYSQL_HOST=...
...     # 删 5 行 MYSQL_*

# backend/app/models/__init__.py
 def create_database():
+    if 'sqlite' in Config.ASYNC_SQLALCHEMY_URI:
+        return
     ...
```

> **验证**:`PITY_ENV=pro python main.py`,本地起来用 `./pity.db` — 启动日志能看到 `database and tables created success. ✔`。

### Commit 3:`chore(backend): aiosqlite 加入 requirements`

```diff
 pyjwt==2.1.0
 mysql-connector-python==8.0.26
+aiosqlite>=0.18.0
```

> **验证**:本地 `pip install -r requirements.txt`,pro 模式启动不再 ImportError。

> 注:这一步**单独 commit**,因为它跟应用代码无关,改 requirements 后立即生效。
> 也可以跟 Commit 2 合并:commit 2 是 "create_database 早退 + pro.env",commit 3 是 "aiosqlite 入依赖"。二选一。

### Commit 4:`chore(ops): pro.env.ops / dev.env.ops 同步配置`

容器 env 文件同步:

```diff
# backend/ops/dev.env.ops
+SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://root:Pitytester666666@mysql:3306/pity"
+ASYNC_SQLALCHEMY_URI="mysql+aiomysql://root:Pitytester666666@mysql:3306/pity"

# backend/ops/pro.env.ops (新文件)
+SQLITE_PATH=/data/pity.db
+SQLALCHEMY_DATABASE_URI=sqlite:////data/pity.db
+ASYNC_SQLALCHEMY_URI=sqlite+aiosqlite:////data/pity.db
+pity_env=pro
...
```

> 这一步是给容器化的部署 compose.deploy.yaml 用的,**可以晚到部署时再做**。

---

## 4. 验证清单

### 4.1 本地 dev 模式跑通(MySQL 路径不变)

```bash
cd backend
# 让 dev env 读到(默认就是 dev)
PITY_ENV=dev python main.py
```

预期:
- `create_database` 创建 mysql db(若不存在)
- `init_database` 建表
- 后端起来了

### 4.2 本地 pro 模式跑通(SQLite 路径)

```bash
cd backend
PITY_ENV=pro python main.py
```

预期:
- `create_database` 早退(不调 mysql)
- `init_database` 用 SQLite 在 `/path/to/pity.db` 建表
- 启动无 import error

### 4.3 写一个最简的 SQL 路径验证

```bash
# pro 模式
PITY_ENV=pro python -c "
import asyncio
from app.crud import UserDao

async def test():
    # 看你 DAO 有什么公共方法,试一个最简单的 select
    # 例如 users.id == 1 的 query
    result = await UserDao.get_user_by_id(1)
    print('OK', result)

asyncio.run(test())
"
```

> 这步确认 AsyncSession 链路(dao → async_engine → sqlite+aiosqlite)通。

### 4.4 服务器容器跑通(SWR 部署后)

```bash
# 服务器上
docker exec -it pity-backend sh -c 'sqlite3 /data/pity.db ".tables"'
# 应该看到 list of 创建出来的 table names
```

### 4.5 Redis 仍要工作(因为保留)

```bash
PITY_ENV=pro python main.py
# 预期:启动 log 显示 "redis connected success. ✔"
```

---

## 5. 回滚路径

每个 commit 独立,任一段可 `git revert`:

| Commit | 回滚指令 | 后果 |
|---|---|---|
| 1 (URIs 注入)| `git revert <sha>` | dev env 没 URI 字段会启动 fail,需要补 env 或恢复拼装逻辑 |
| 2 (pro env + create_database)| `git revert <sha>` | pro 不能用了(URI 字段必填),dev 仍 OK |
| 3 (aiosqlite)| `git revert <sha>` | pro 跑不起来 ImportError |

完整回滚:

```bash
git revert --no-commit HEAD~3..HEAD
# 调整后再提交
git commit -m "revert: pro DB 切回原方案"
```

或粗暴:

```bash
git reset --hard <sha of last good commit>
# 注意:会丢中间所有 commit;仅当回滚全部有效
```

---

## 6. 风险点

### 6.1 pro 容器 `sqlite` 路径需要保证父目录存在

- 容器内 `mkdir -p /data` 必须在启动前发生
- 当前 `backend/ops/dockerfile` 用 `WORKDIR /pity`,没显式建 `/data`
- 改造 dockefile 步骤:**在 `RUN` 段加 `RUN mkdir -p /data`**(且 chmod 777 / `chown` 给运行用户)

或者:用相对路径如 `/pity/data/pity.db`,把 `WORKDIR /pity/data` 跟 `/pity/data` bind mount。

### 6.2 多 worker 共享 SQLite 文件

- 当前 `gunicorn -w 2` 在容器里跑
- SQLite 文件锁 + 多 worker 并发写会冲突
- 解决:`PRAGMA journal_mode=WAL`(每个 connection 加)— 让多 reader 单 writer
- 实际生产用法:开 `-w 2` 时也得接受**写请求会串行化**,SQLite 仍然 OK(demo 阶段)
- 如果想避免:跑 `-w 1` 单 worker — demo 上完全够

### 6.3 APScheduler 跟 SQLite 互斥

- 容器启动时,APScheduler 会创建自己的表(`apscheduler_jobs` 在 SQLite 下)
- 跟业务表共享一个 .db 文件没问题
- **但是**:`SQLAlchemyJobStore` 创建表的 engine 用 `Config.SQLALCHEMY_DATABASE_URI` — 注意它是同步 URL(`mysql+mysqlconnector` / `sqlite:////...`)。SQLite 上 SQLAlchemyJobStore 是支持的,代码无需改。

### 6.4 `pymysql` 在 requirements.txt 里(没用上)

- 不确定是否 MySQL-only 同步链某处 import 它
- 安全起见保留:dev 模式如果某个旧 DAO 用 `pymysql` 直接驱动,就会报错
- 这次不动

---

## 7. 跟主部署路线的衔接

当你从零启动 GitHub Actions + SWR 部署(见 `docs/DEPLOY_RUNBOOK.md`),**容器内 `pity_env` 环境变量必须设为 pro**:

```yaml
# .github/workflows/deploy-frontend.yml(以及 backend)里
- name: Build image
  ...
- name: SSH remote
  script: |
    cd /home/tester/pity-deploy
    export pity_env=pro
    docker compose -f backend/ops/docker-compose.deploy.yaml pull backend
    docker compose -f backend/ops/docker-compose.deploy.yaml up -d backend
```

或者在 `backend/ops/pro.env.ops` 中写 `pity_env=pro`(见 2.7),再让 compose 用 env_file。

`backend/ops/docker-compose.deploy.yaml` 里:

```yaml
backend:
  image: ${SWR_REGISTRY}/${SWR_ORG}/pity-backend:${TAG:-latest}
  env_file: pro.env.ops       # <-- 用 pro 文件
  networks: [appnet]
  ...
```

dev 模式本地开发不需要这套,继续读 `conf/dev.env`。

---

## 8. 总结

| 项 | 改前 | 改后 |
|---|---|---|
| **本地 dev** | MySQL | MySQL(无变化) |
| **服务器 pro** | MySQL(占 500MB+)| **SQLite(占 <10MB)** |
| **业务代码** | 全部支持 | 全部支持 |
| **Alembic 用法** | dev 跑,pro 不跑(本来如此) | 同 |
| **依赖** | +aiomysql, +mysql-connector | +aiosqlite 增加 |
| **改动的文件数** | - | **5-7 个文件**(config + env + models + 两个 ops env)|
| **内存节省** | - | **~400-500MB** |

> 文档配套:`DEPLOY_DOCKER_MIGRATION.md` / `DEPLOY_RUNBOOK.md`(主部署路线)+ 本文档(DB 后端选择)。

**下一步**(你拍板后):

- 我按 Commit 1-4 的 diff 顺序挨个落地
- 中途任意一步你想中止(比如不想 SQLite 只想 MySQL 优化)就停下,我们就只跑 Commit 1 + 3 缩小改动面

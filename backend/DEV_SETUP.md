# 本地开发启动指南

> 配套 [`README.md`](./README.md):README 介绍项目,本文件记录**手把手跑起来**的具体步骤,以及这次跑通过程中踩过的坑。

适用环境:macOS(Darwin),Python 用 Miniconda,Node 用 nvm。

---

## 1. 前置条件

| 工具 | 版本 | 安装方式 |
|------|------|----------|
| Miniconda | 最新 | `brew install --cask miniconda` 或官网安装包 |
| nvm | 最新 | `brew install nvm`(可选,前端用) |
| MySQL | 8.0+ | `brew install mysql`,本地服务,root 密码见 §3 |
| Redis | 6.x+ | `brew install redis`,本地服务,无密码 |
| Docker | 可选 | **本项目用不到 Docker**,仅 `ops/` 目录留给服务器部署 |

---

## 2. Python 环境(conda + Python 3.10)

⚠️ **必须用 Python 3.10,不能用 3.11+**。原因见 §7 踩坑记录。

```bash
# 建环境
conda create -n pity-backend python=3.10 -y
conda activate pity-backend

# 验证版本
python --version   # 应输出 Python 3.10.x
```

---

## 3. MySQL 配置

**默认连接信息**(写在 `conf/dev.env`):

| 字段 | 值 |
|------|-----|
| 主机 | `127.0.0.1` |
| 端口 | `3306` |
| 用户 | `root` |
| 密码 | `12345678` |
| 库名 | `pity` |

如果你的 root 密码**不是** `12345678`,先编辑 `backend/conf/dev.env` 把 `MYSQL_PWD` 改成你的密码。

建库(项目不会自动建库,首次必须手动):

```bash
mysql -uroot -p12345678 -e \
  "CREATE DATABASE IF NOT EXISTS pity DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 验证
mysql -uroot -p12345678 -e "SHOW DATABASES LIKE 'pity';"
# 应输出: +---------------------+ | Database            |
#        +---------------------+ | pity                |
#        +---------------------+
```

启动服务:

```bash
brew services start mysql
lsof -iTCP:3306 -sTCP:LISTEN    # 应看到 mysqld 在监听
```

---

## 4. Redis 配置

**默认配置**(`conf/dev.env` 里 `REDIS_PASSWORD` 留空):

| 字段 | 值 |
|------|-----|
| 主机 | `127.0.0.1` |
| 端口 | `6379` |
| DB | `0` |
| 密码 | 无 |

```bash
brew services start redis
lsof -iTCP:6379 -sTCP:LISTEN    # 应看到 redis-server 在监听

# 简单 ping
redis-cli ping                  # 应输出 PONG
```

如果你的 Redis 设了密码,改 `conf/dev.env` 的 `REDIS_PASSWORD="你的密码"`。

---

## 5. 安装依赖

```bash
cd backend
conda activate pity-backend
pip install -r requirements.txt

# 装完核对关键版本(Pydantic 不能升到 2.x)
pip show sqlalchemy pydantic fastapi | grep -E '^(Name|Version)'
# 期望:
#   Name: fastapi    Version: 0.75.0
#   Name: pydantic   Version: 1.8.x   ← 不能是 2.x
#   Name: sqlalchemy Version: 1.4.47
```

---

## 6. 启动后端

```bash
cd backend
conda activate pity-backend

# 开发启动(默认读 conf/dev.env)
python pity.py
```

成功启动的标志——日志末尾出现:

```
Application startup complete.
Uvicorn running on http://0.0.0.0:7777 (Press CTRL+C to quit)
```

服务监听在 **7777 端口**。

### 验证

```bash
# OpenAPI 文档
open http://localhost:7777/docs

# 健康检查(任选一个不需要鉴权的端点)
curl -i http://localhost:7777/api/auth/captcha
```

第一个注册的用户**自动成为 superAdmin**,可以直接在 `/api/auth/register` 注册。

### 热重载(可选)

```bash
uvicorn main:pity --reload --host 0.0.0.0 --port 7777
```

---

## 7. 启动前端(简要)

```bash
cd ../frontend
nvm use                # 锁到项目要求的 node 版本
npm install
npm run start:dev      # 起在 localhost:8000
```

前端 dev server 通过代理把 `/api/*` 转发到 `http://localhost:7777`,所以**后端必须保持运行**。

---

## 踩坑记录

### ❌ Python 3.11 + pydantic 1.8.x 启动报错

**现象**:

```
File ".../pydantic/utils.py", line 231, in generate_model_signature
    merged_params[param_name] = Parameter(
                                ^^^^^^^^^^
ValueError: 'not' is not a valid parameter name
```

**原因**:Python 3.11 收紧了 `inspect.Parameter` 的参数名校验,保留字 `not` 不能作为参数名。pydantic 1.8.x 的 `utils.generate_model_signature` 没做过滤,撞到了。

**解决**:Python 降到 **3.10**(`requirements.txt` 写的是 `pydantic~=1.8.1`,整个 1.8 系列对 3.11 都不兼容)。

### ⚠️ 不要升级 Pydantic 到 2.x

CLAUDE.md 明确写死 v1,且全栈 FastAPI/Pydantic 都被钉在 v1 风格:
- `BaseSettings` 来自 `pydantic` 而非 `pydantic-settings`
- 模型用 v1 的 `Config` 类
- `validator` / `root_validator` 装饰器

升 Pydantic 2 = 全栈迁移,不划算。

### ⚠️ MySQL 库不会自动建

`Base.metadata.create_all` 只建表,**不建库**。首次启动前必须手动 `CREATE DATABASE pity`。

### ⚠️ `pip install` 可能微调 `requirements.txt`

实测 pip 在某些场景会自动改写 `requirements.txt`(例如把 `aiohttp==3.8.1` 改成 `3.8.2`)。如果发现 `git status` 里有 `requirements.txt` 改动,正常 commit 即可,版本差异是 patch 级,不影响行为。

---

## 端口速查

| 服务 | 端口 | 备注 |
|------|------|------|
| 后端 FastAPI | 7777 | dev/pro 都是这个 |
| 前端 UmiJS dev | 8000 | 仅开发模式 |
| MySQL | 3306 | 本地默认 |
| Redis | 6379 | 本地默认 |

端口撞了的话,后端改 `conf/dev.env` 的 `SERVER_PORT`,前端改 `.umirc.ts` 的 `proxy` 目标端口。

---

## 常见报错速查

| 现象 | 处理 |
|------|------|
| `redis connect failed` | Redis 没起,或密码不匹配(`lsof -iTCP:6379` 验证) |
| `Access denied for user 'root'@'localhost'` | `dev.env` 里的 `MYSQL_PWD` 跟实际不符 |
| `Unknown database 'pity'` | 没建库,回 §3 跑 `CREATE DATABASE` |
| `ImportError: BaseSettings` | pydantic 升到 2.x,降到 `pip install "pydantic~=1.8.1"` |
| `ModuleNotFoundError: aiomysql/apscheduler` | 没激活 conda,或 pip 没装完 |
| `ModuleNotFoundError: yagmail/oss2/qiniu/...` | `pip install -r requirements.txt` 完整跑一遍 |

---

## 相关文件

- [`conf/dev.env`](./conf/dev.env) — 本地开发环境变量
- [`conf/pro.env`](./conf/pro.env) — 生产环境变量
- [`requirements.txt`](./requirements.txt) — Python 依赖
- [`main.py`](./main.py) — 开发启动入口(自动建表 + APScheduler + Redis 初始化)
- [`pity.py`](./pity.py) — 另一启动入口,跟 main.py 等价
- [`CLAUDE.md`](./CLAUDE.md) — 项目架构、约定、新增 API 流程
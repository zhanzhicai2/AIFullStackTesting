# 本地开发启动指南

> 配套 [`README.md`](./README.md):README 介绍项目,本文件记录**手把手跑起来**的具体步骤,以及这次跑通过程中踩过的坑。

适用环境:macOS(Darwin),Python 用 uv(取代原 Miniconda 路线),Node 用 nvm。

---

## 1. 前置条件

| 工具 | 版本 | 安装方式 |
|------|------|----------|
| uv | ≥0.4 | `brew install uv` 或 `curl -LsSf https://astral.sh/uv/install.sh \| sh`(项目用 0.13.0 验证过) |
| nvm | 最新 | `brew install nvm`(可选,前端用) |
| MySQL | 8.0+ | `brew install mysql`,本地服务,root 密码见 §3 |
| Redis | 6.x+ | `brew install redis`,本地服务,无密码 |
| Docker | 可选 | **本项目用不到 Docker**,仅 `ops/` 目录留给服务器部署 |

---

## 2. Python 环境(uv venv + Python 3.10)

⚠️ **必须用 Python 3.10,不能用 3.11+**。原因见 §7 踩坑记录(历史问题,现在 Pydantic 已升 1.10)。

```bash
# 进入后端目录
cd backend

# 创建独立 venv(uv 会下载 cpython-3.10.22 macOS wheel,约 24MB)
uv venv --python 3.10

# 激活
source .venv/bin/activate

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

建库(项目不会自动建库,首次必须手动)，本次提前下载mysql和创建了pity，提前启动:

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

## 4. Redis 配置，提前启动

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
source .venv/bin/activate   # 复用 §2 创建的 venv

# uv 装依赖(走 PyPI 镜像,速度 10-100x 快于 pip)
uv pip install -r requirements.txt

# 装完核对关键版本
uv pip list | grep -iE '^(fastapi|pydantic |pydantic-|starlette|sqlalchemy|aiohttp |pyjwt|redis |pyyaml|jinja2|loguru|requests |pycryptodome)'
# 期望:
#   fastapi     0.115.x
#   pydantic    1.10.x
#   sqlalchemy  1.4.47
#   starlette   0.41.x
#   aiohttp     3.9+
#   redis       5.x
```

---

## 6. 启动后端

```bash
cd backend
source .venv/bin/activate

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

## 7. 启动前端

### 7.1 前置

- Node 20(已写在 `frontend/.nvmrc`)+ npm ≥ 9
- 用 nvm 管理 Node,国内网要设镜像源(见 §7.6 踩坑)

### 7.2 完整步骤

```bash
cd ../frontend

# 1) 如果没装 Node 20,设镜像后装
NVM_NODEJS_ORG_MIRROR=https://npmmirror.com/mirrors/node nvm install 20
nvm use    # 自动切到 .nvmrc 锁的版本

# 2) 清理旧产物(首次或之前失败时)
rm -rf node_modules package-lock.json

# 3) 装包(monorepo 子目录跑 npm install 会卡在 husky install,见 §7.6)
npm install --ignore-scripts

# 4) 启动
npm run start:dev
```

成功标志:日志末尾出现 `http://localhost:8000`,浏览器打开自动跳到登录页(未注册用户去注册)。**第一个注册用户自动成为 superAdmin**。

### 7.3 已锁的配置文件

| 文件 | 内容 | 作用 |
|------|------|------|
| `frontend/.nvmrc` | `20` | 锁 Node 版本,`nvm use` 自动切 |
| `frontend/.npmrc` | `legacy-peer-deps=true` | 应对 `@ant-design/charts@1.x` 与 `antd@5` 的 peer 冲突 |

### 7.4 前端 ↔ 后端

`config/proxy.ts` 在开发模式把以下 11 个前缀代理到 `http://localhost:7777`:

```
/api/ /auth/ /testcase/ /config/ /project/ /operation/
/workspace/ /oss/ /notification/ /online/ /request/
```

所以**后端必须保持运行**,否则前端任何接口调用都会报跨域或 502。

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

**解决**:Python 降到 **3.10**(`requirements.txt` 锁的是 `pydantic~=1.10.13`,整个 1.10 系列对 3.11 都不兼容)。Pydantic 升 2.x 也可,但需要全栈迁移(见 §7 后续计划)。

### ❌ `nvm install 20` 报 "Version '20' not found"

**现象**:

```
$ nvm install 20
Version '20' not found - try `nvm ls-remote` to browse available versions.
```

**原因**:nvm 默认从 `nodejs.org` 拉版本索引,国内网络经常超时/失败。

**解决**:

```bash
# 方法 A:环境变量(只对此次 install 生效)
NVM_NODEJS_ORG_MIRROR=https://npmmirror.com/mirrors/node nvm install 20

# 方法 B:写到 ~/.zshrc(永久)
echo 'export NVM_NODEJS_ORG_MIRROR=https://npmmirror.com/mirrors/node' >> ~/.zshrc
source ~/.zshrc
```

### ❌ `npm install` 卡在 `husky install`: ".git can't be found"

**现象**:

```
> husky install
.git can't be found (see https://git.io/Jc3F9)
npm error code 1
```

**原因**:`frontend/package.json` 里 `"prepare": "husky install"` 是 Pity 上游模板(单 git 仓库)留下来的写法。**monorepo 子目录跑 npm install 时,`husky@7` 只查 cwd 的 `.git`,不向上递归到仓库根**,所以失败。这本身是个反模式 — 项目仓库根的 `.husky/` 目录也不存在,husky 钩子从未真正生效过。

**解决**:

- 临时:`npm install --ignore-scripts`(跳过 husky,`max setup` 已经在前一步跑完了所以不丢东西)
- 永久:把 `frontend/package.json` 的 `"prepare": "husky install"` 改成 `"prepare": "echo \"skipping husky install in monorepo subdir\""`

### ❌ `npm install` 报 ERESOLVE peer 冲突

**现象**:

```
npm error ERESOLVE unable to resolve dependency tree
npm error peer antd@"^4.6.3" from @ant-design/charts@1.4.3
```

**原因**:`@ant-design/charts@1.x` 锁了 `antd@^4`,但项目用的是 `antd@5`。npm 7+ 严格 peer 检查直接拒装。

**解决**:`frontend/.npmrc` 已设 `legacy-peer-deps=true`,下次 `npm install` 自动放宽。如果锁文件被旧状态污染,先 `rm -rf node_modules package-lock.json` 再装。

### ⚠️ 不要升级 Pydantic 到 2.x

CLAUDE.md 明确写死 v1,且全栈 FastAPI/Pydantic 都被钉在 v1 风格:
- `BaseSettings` 来自 `pydantic` 而非 `pydantic-settings`
- 模型用 v1 的 `Config` 类
- `validator` / `root_validator` 装饰器

升 Pydantic 2 = 全栈迁移,不划算。

### ⚠️ MySQL 库不会自动建

`Base.metadata.create_all` 只建表,**不建库**。首次启动前必须手动 `CREATE DATABASE pity`。

### ⚠️ setuptools 版本约束

`requirements.txt` 锁了 `setuptools<81`,因为 setuptools 81+ 正式移除了 `pkg_resources` 模块,而 `APScheduler 3.8.0` 和 `mitmproxy 8.0.0` 仍在用它。`uv pip install` 装到 84.x 时启动会报 `ModuleNotFoundError: No module named 'pkg_resources'`,降到 80.x 即可。后续如果把 APScheduler / mitmproxy 都升到大版本,可以放开这个约束。

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
| `ImportError: BaseSettings` | pydantic 升到 2.x,降到 `uv pip install "pydantic~=1.10.13"` |
| `ModuleNotFoundError: aiomysql/apscheduler` | 没 `source .venv/bin/activate`,或 `uv pip install` 没跑完 |
| `ModuleNotFoundError: No module named 'pkg_resources'` | setuptools ≥81,降到 `uv pip install "setuptools<81"` |
| `ModuleNotFoundError: yagmail/oss2/qiniu/...` | `uv pip install -r requirements.txt` 完整跑一遍 |
| `cannot import name 'ClusterConnectionPool' from 'redis.cluster'` | redis-py-cluster 没卸干净,`uv pip uninstall redis-py-cluster rediscluster` |
| `npm error ... husky install ... .git can't be found` | 见 §7.6:`npm install --ignore-scripts` |
| `npm error ERESOLVE ... antd@"^4.6.3"` | 见 §7.6:`legacy-peer-deps=true` 已配 |
| `nvm install 20` 报 Version '20' not found | 见 §7.6:`NVM_NODEJS_ORG_MIRROR=...` |

---

## 相关文件

- [`conf/dev.env`](./conf/dev.env) — 本地开发环境变量
- [`conf/pro.env`](./conf/pro.env) — 生产环境变量
- [`requirements.txt`](./requirements.txt) — Python 依赖
- [`main.py`](./main.py) — 开发启动入口(自动建表 + APScheduler + Redis 初始化)
- [`pity.py`](./pity.py) — 另一启动入口,跟 main.py 等价
- [`CLAUDE.md`](./CLAUDE.md) — 项目架构、约定、新增 API 流程
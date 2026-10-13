# Pity 单机 Docker 部署方案(2026-10-14 实施记录)

> 文档定位:把今天所有决策、文件改动、踩坑、最终可运行步骤全部归一化,供后续维护和 onboarding 用。
> 旧版本(2026-10-13 那份)被覆盖;以前的 git 历史保留,需要时 `git log --follow docs/DEPLOY_DOCKER_MIGRATION.md` 看演进。
>
> 目标机:**华为云 Flexus `ahf.large.1.40g.2m`**,2 核 2G 内存 / **仅 40G 系统盘,无独立数据盘** / 2M 带宽
> 部署栈:docker compose v2 + 5 服务 + SWR 拉自建镜像 + docker.io 拉 mysql/redis 公开镜像

---

## 0. TL;DR

| 决策点 | 选择 | 原因 |
|---|---|---|
| 前后端镜像 | **都做镜像 + nginx 反代** | 老 Pity "前端 dist 塞 backend/statics" 在 docker 化里不适应,前后端解耦才合理 |
| 镜像数 | 3 自建 + 2 公开 | 后端 / 前端 / nginx 各自独立 rebuild,缓存命中好 |
| 数据盘 | **无,所有数据落系统盘 40G** | 服务器只有系统盘 |
| Docker Compose 单机方案 | 走 | demo 不上 k8s |
| 镜像推送工具 | **skopeo**(非 docker push) | SWR + docker CLI 的 manifest 协议 bug(详见 §7.1) |
| 后端 Python 基础镜像 | python:3.10-slim | 与本地 conda 3.10.18 对齐(原 3.9 可能掩盖 PEP 604 语法错误) |
| 前端 Node 基础镜像(dev + 部署) | node:20-alpine | 与本地 v20.20.2 对齐(原 18.18.2 EOL) |
| GitHub Actions 自动化 | **延后** | 优先保证手动流程跑通 |

最终 image tag:**SWR 上** `pity-backend:v0.2` / `pity-frontend:v0.2` / `pity-nginx:v0.3`(nginx 比后两者多迭代一次,因为 fix 了一个 nginx 转发规则 bug,详见 §5.4)

---

## 1. 资源现实

### 1.1 硬件

- 2 核 CPU
- 2G 内存
- **40G 系统盘(无独立数据盘)**
- 2M 带宽

### 1.2 操作系统 & 镜像来源

- **server OS**:Ubuntu 22.04 (Huawei Cloud Flexus)
- **Docker Engine**:Docker 29.1.3(Ubuntu backport 装的是 `docker.io`,没带 compose plugin,见 §7.2)
- **Docker Compose**:v2.x(需手动装)
- **本机 OS**:macOS(MacBook Pro,Intel x86_64)
- **本机 Docker**:Docker Desktop,内置 docker compose v2

### 1.3 内存分配(每容器 `deploy.resources.limits.memory`)

| 服务 | 限额 |
|---|---|
| backend (gunicorn 2 workers + uvicorn) | 600M |
| mysql 8.0 | 700M |
| redis 7-alpine | 80M |
| frontend (nginx:alpine serves dist/) | 30M |
| nginx (反代) | 30M |
| **合计** | **~1.44G / 2G** → OS + buffer 留 ~560M |

---

## 2. 单盘 40G 容量预算

40G 系统盘的可用空间按下面口径切;**留 8–10G buffer** 给 OS + apt 缓存 + Docker 引擎自身增长,**不要让数据落满到 90% 以上**,否则 apt/docker/journald 都开始报错。

| 类别 | 路径 | 预算上限 | 回收策略 |
|---|---|---|---|
| 镜像层(含 builder cache) | `/var/lib/docker` + `/tmp`(builder) | ~6G | `docker builder prune -af --filter "until=72h"` 每周 cron |
| MySQL 数据 | `/home/tester/pity-data/mysql` | ~8G | `expire_logs_days=3`、`innodb_file_per_table`、`max_binlog_size=100M` |
| Redis 数据 | `/home/tester/pity-data/redis` | ~500M | AOF only、`appendfsync everysec`、`auto-aof-rewrite-min-size 64mb` |
| 应用日志(gunicorn + nginx) | `/home/tester/pity-data/logs/{pity,nginx}` | ~2G | logrotate 按天切,保留 14 天,`copytruncate` 不停服 |
| MySQL binlog + slow log | `/home/tester/pity-data/logs/mysql` | ~1G | `expire_logs_days=3` |
| 部署包 + 临时上传 | `/home/tester/pity-deploy` | ~2G | `rm /tmp/pity-deploy.tgz` 后留 release 目录 |
| 系统自身 | `/`、`/var/log/journal`、`/var/cache/apt` | ~10G | journald `SystemMaxUse=200M`、apt `clean` 周期 |
| **Buffer (headroom)** | — | **~10G** | 任何单类别超过预算先报警 |

**磁盘监控(必装):** systemd timer 或 cron 跑:

```bash
USAGE=$(df -P / | awk 'NR==2 {print $5}' | tr -d '%')
[ "$USAGE" -ge 70 ] && logger -t pity-disk "WARN rootfs ${USAGE}%"
[ "$USAGE" -ge 85 ] && logger -t pity-disk "CRIT rootfs ${USAGE}%"
```

`logger` 走 journald,`SystemMaxUse=200M` 兜底不让日志也吃满。

---

## 3. 架构

```
外部用户 (浏览器)
   │ :80
   ▼
┌─────────────────────┐
│  nginx (容器)       │
│  - /api/*, /auth/* │
│    /testcase/* 等   │
│    11 前缀 → backend│
│  - 其他 → frontend  │
└──┬──────────┬──────┘
   │          │
┌──▼──────┐ ┌─▼─────────────┐
│ backend │ │ frontend      │
│  gunicorn│ │  nginx:alpine │
│  -w 2   │ │  serves dist/ │
└──┬──────┘ └───────────────┘
   │
┌──▼────┐ ┌─▼────┐
│ MySQL │ │Redis │
└───────┘ └──────┘
```

所有数据卷 bind mount 到 `/home/tester/pity-data/*`(全部系统盘,无独立数据盘)。

### 3.1 服务清单

| 服务 | 镜像来源 | 镜像名 / tag | 端口(对外) | 内存上限 | 数据卷 / env |
|---|---|---|---|---|---|
| nginx | 自建(SWR) | `pity-nginx:v0.3` | **80** | 30M | 无 |
| frontend | 自建(SWR) | `pity-frontend:v0.2` | 仅内网 | 30M | 无 |
| backend | 自建(SWR) | `pity-backend:v0.2` | 仅内网 | 600M | env_file: `./dev.env.ops` |
| mysql | docker.io 公开 | `mysql:8.0` | 仅内网 | 700M | bind mount 到 `/home/tester/pity-data/mysql` |
| redis | docker.io 公开 | `redis:7-alpine` | 仅内网 | 80M | bind mount 到 `/home/tester/pity-data/redis` |

**端口只对外暴露 80**。其余服务都在 `appnet` bridge 网络内,通过服务名互访。

---

## 4. 文件清单 / 仓库布局

```
AIFullStackTesting/
├── backend/
│   ├── ops/
│   │   ├── dockerfile                  # python:3.10-slim + builder(2026-10-14 升级)
│   │   ├── docker-compose.yaml         # dev 3 服务 compose(legacy,留着)
│   │   ├── docker-compose.deploy.yaml  # ★ 5 服务生产 compose(2026-10-14 新增 + 修订)
│   │   ├── dev.env.ops                 # dev env,被 deploy compose 作 env_file 引入
│   │   └── supervisor.conf             # [program: pity] (gunicorn)
│   └── ... # 同原 Pity
├── frontend/
│   ├── Dockerfile                      # dev 用(node:20-alpine + npm ci)
│   ├── Dockerfile.production           # ★ 多阶段:node:20-alpine build → nginx:alpine serve dist/
│   ├── .dockerignore                   # ★ 配套 .dockerignore
│   └── ... # 同原 Pity
├── nginx/
│   ├── Dockerfile                      # ★ nginx:alpine + COPY nginx.conf
│   └── nginx.conf                      # ★ 11 前缀正则(详见 §5.4)
├── scripts/
│   ├── build-images.sh                 # ★ Step 1:本地 build 3 镜像
│   └── push-to-swr.sh                  # ★ Step 2:skopeo 推 SWR(不用 docker push)
├── docs/
│   └── DEPLOY_DOCKER_MIGRATION.md      # 本文档(2026-10-14 覆盖旧版)
└── ...
```

★ 标注是今天(2026-10-14)新增 / 重写的文件。

---

## 5. 关键改动记录(2026-10-14)

### 5.1 backend dockerfile 升 3.9 → 3.10

老 dockerfile 用 `python:3.9-slim` + builder 阶段,有 wait-for-it.sh 下载 + apt install wget。**两个问题**:

1. **基础镜像版本与本地 `pity-backend` conda (3.10.18) 不一致** —— 如果本地用 PEP 604(`int | None`)或 PEP 634(`match/case`)语法,docker 容器里 3.9 解释器会 `SyntaxError`,本地 debug 看不出来
2. **`wait-for-it.sh` 全仓 grep 后确认没有任何 .sh / .py / 配置引用它**,supervisor.conf 只启 gunicorn,是上游 Pity 历史残留

修法:

- 两 stage 基础镜像 `python:3.9-slim` → `python:3.10-slim`
- 顺手修 lint:`FROM python:3.10-slim as builder` → `FROM python:3.10-slim AS builder`
- 删除 `apt install -y wget` + `wget https://github.com/vishnubob/wait-for-it/...`
- 删除 final stage 的 `COPY --from=builder /pity/wait-for-it.sh` + `RUN ... && chmod +x /pity/ops/wait-for-it.sh`

净效果:build 加速 ~30 秒(少 wget 一行),镜像层不再带死文件,跳过 GnuTLS 失败点。

### 5.2 frontend dev Dockerfile 升 Node 18.18.2 → 20-alpine + 去 cnpm 老黄历

老 Dockerfile:`node:18.18.2` + `npm install -g cnpm` + `cnpm install`。Node 18 已 EOL(2025-04),cnpm 是 npm 时代的过渡工具,2018 后已经被 registry flag + npm ci 取代。

新 Dockerfile:

- `node:18.18.2` → `node:20-alpine`
- 删除 `npm install -g cnpm`
- `cnpm install` → `npm ci --no-audit --prefer-offline --registry=https://registry.npmmirror.com`
- 加 COPY 分层:先 `package.json` + `package-lock.json` 装依赖,再 `COPY . .`,改源码不重装依赖
- 国内 npm 镜像(`registry.npmmirror.com`),2M 带宽下拉得动

### 5.3 frontend 生产 Dockerfile(`Dockerfile.production`)

**多阶段**:

```dockerfile
# Stage 1: build
FROM node:20-alpine AS builder
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --prefer-offline \
        --legacy-peer-deps \
        --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

# Stage 2: serve(只拷 dist/)
FROM nginx:1.27-alpine
COPY --from=builder /build/dist/ /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

要点:

- **`--legacy-peer-deps`**:UmiJS v4 + Ant Design v5 之间的 peer dep 冲突(`@ant-design/charts@1.4.3` 要 antd@^4,实际装的是 antd@5),npm 7+ 严格模式会 ERESOLVE,这个 flag 切回 npm 6 宽松解析(详见 §7.6)
- **多阶段**:final stage 只剩 nginx + dist/,镜像体积 ~25MB 压缩(不是 ~200MB,后者说明多阶段没生效)

配套 `.dockerignore` 排除 `node_modules`、`dist`、`.umi`、`tests`、`mock`、`.git` 等。

### 5.4 nginx 反代:11 前缀正则

**老版本**(2026-10-14 之前写的):

```nginx
location /api/ {
    proxy_pass http://backend:7777/;  # 末尾有 / = strip prefix
}
```

**两个问题**:

1. 只接 `/api/` 前缀,但前端代码(看 `frontend/CLAUDE.md` 和 `frontend/config/proxy.ts`)实际调 `/auth/`、`/testcase/` 等 11 个前缀 → 落到 `location /` → 转给前端 nginx → 404
2. `proxy_pass http://backend:7777/` 带末尾 `/` = **strip prefix**(`/api/foo` → backend `/foo`),但后端 FastAPI router 是 `APIRouter(prefix="/auth")` + `@router.post("/register")`,strip 后 `/register` 不命中 `/auth/register` → 也是 404

**新版本**:

```nginx
location ~ ^/(api|auth|testcase|config|project|operation|workspace|oss|notification|online|request)/ {
    proxy_pass http://backend:7777;          # 无末尾 / = 保留 URI
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 60s;
    proxy_send_timeout 60s;
}

location / {
    proxy_pass http://frontend:80;
    # (header 同上)
}
```

要点:

- 用正则 location 一次匹配 11 个 dev proxy 前缀
- `proxy_pass` **不带末尾 `/`** = 完整 URI 转发,FastAPI router prefix 才能命中

11 个前缀来自 `frontend/config/proxy.ts` 里 dev proxy 的声明。

### 5.5 docker-compose.deploy.yaml 修订

#### 5.5.1 顶层 `version: "3.8"` → 删

Compose v2+ 已经忽略 `version` 字段,留着会报警 `the attribute version is obsolete, it will be ignored`。**删**。

#### 5.5.2 backend bind mount → `env_file`

老:

```yaml
volumes:
  - ./dev.env.ops:/pity/conf/dev.env
```

**问题**:server 端 `./dev.env.ops` 文件不存在时,docker engine **会自动建空目录**当作 bind source,后续 mount 时 `MS_REC` 当目录挂载到文件 `/pity/conf/dev.env` 失败(详见 §7.4)。

修法,用 `env_file:`:

```yaml
env_file:
  - ./dev.env.ops

environment:
  TZ: Asia/Shanghai
  pity_env: dev   # 暂用 dev 配置路径,等 backend/conf/pro.env 落地后改 pro
  MYSQL_HOST: mysql         # 覆盖 dev.env.ops 里的 MYSQL_HOST="pity"
  REDIS_HOST: redis
  MYSQL_PWD: ${MYSQL_ROOT_PASSWORD}
  REDIS_PASSWORD: ${REDIS_PASSWORD}
```

`env_file:` 让 docker compose 把文件内容读出来作为 ENV vars 注入容器,pydantic Settings 直接消费,**不涉及 bind mount**,也就不会触发空目录坑。

#### 5.5.3 nginx image tag 硬编码 v0.3

nginx:v0.3 是持久化 forward fix 的版本,server 上镜像 tag 钉死 v0.3,其他服务(v0.2)不变。Compose 里 nginx 那行:

```yaml
nginx:
  image: ${SWR_REGISTRY}/${SWR_ORG}/pity-nginx:v0.3    # 硬编码,不跟 TAG 变量
  ...
```

其他 backend/frontend 用 `${TAG:-v0.2}`(默认),不传 TAG 也不会去找 `:latest`(避免又踩 §7.1 类似的 not-found 错误)。

### 5.6 push-to-swr.sh:docker push → skopeo

**问题**:docker CLI 推 SWR 时反复报 `error from registry: Invalid image, fail to parse 'manifest.json'`。所有 layer 都成功传输(`Layer already exists`),只有最后写 manifest 时挂。**不是 image 坏**,是 docker CLI 的 manifest v2.2 跟 SWR 解析器协议层有兼容性 bug。换 tag 重推、删除 SWR 仓库重推都无用(详见 §7.1)。

**修法**:用 skopeo 替代,直发 OCI distribution-spec HTTP。验证 `pity-backend:v0.2` 一次成功。

新 `scripts/push-to-swr.sh` 改动:

- 用 `mktemp + trap` 装 `docker save` 的 tar 文件
- `docker save` 出来 → `skopeo copy docker-archive:<tar> docker://<dest>`,不走 `docker-daemon:`(Mac 上找不到 `/var/run/docker.sock`)
- 自动创建 `~/.config/containers/policy.json`(Mac 上 brew 装的 skopeo 缺它就拒启动)
- 检测 `skopeo` 命令是否存在,缺则报错退出

---

## 6. 部署 4 步(手动流程,Actions 延后)

### Step 1 — 本地构建 3 镜像

```bash
cd /Users/zhanzhicai/Desktop/py/AIFullStackTesting
./scripts/build-images.sh           # 默认 tag = dev
./scripts/build-images.sh v0.2      # 或者指定 tag
```

期望输出:

```
pity-backend   v0.2   540MB       # Python 3.10 + venv deps
pity-frontend  v0.2   ~25MB       # ← 多阶段成功标志(>200MB 说明没生效)
pity-nginx     v0.2   ~25MB
```

### Step 2 — 推 SWR(skopeo)

需要从华为云 SWR 控制台 → 我的凭证 → 临时登录指令 → 生成,有效期 12h:

```bash
export SWR_REGISTRY='swr.cn-south-1.myhuaweicloud.com'   # cn-south-1 是这台 Flexus 的 region
export SWR_ORG='pity'
export SWR_USER='cn-south-1@HST3WO1ORTGZ66FN9G1K'        # 默认格式 cn-<region>@<org>
export SWR_PASS='<临时凭证密码,12h 过期>'                  # 单次生成

cd /Users/zhanzhicai/Desktop/py/AIFullStackTesting
./scripts/push-to-swr.sh v0.2
```

skopeo 的输出是 `Copying blob ... Copying config ... Writing manifest`,**出现 `FATA` 就是失败**;成功时 SWR 控制台 → 我的镜像 → 应有 3 个仓库各带 `:v0.2` tag。

### Step 3 — 服务器 pull + up

#### A. Pre-flight(ssh 进 server 后)

```bash
ssh root@124.71.69.165
docker --version                     # ≥ 20.10
docker compose version               # ≥ v2(华为云 Ubuntu backport 没带,见 §7.2 修法)
df -h /                              # Available ≥ 25G
```

#### B. 装 docker compose v2(华为云 backport 缺这个)

```bash
# 方案 A:apt(优先)
apt install -y docker-compose-plugin
docker compose version

# 方案 B:GitHub release 二进制直接装
curl -fsSL "https://mirror.ghproxy.com/https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
docker compose version               # 期望 ≥ v2.20
```

#### C. 部署目录

```bash
mkdir -p /home/tester/pity-deploy
mkdir -p /home/tester/pity-data/{mysql,redis,logs/{pity,nginx,mysql}}
```

#### D. 配置文件(Mac 上 scp 上 server)

```bash
# Mac 上
scp /Users/zhanzhicai/Desktop/py/AIFullStackTesting/backend/ops/docker-compose.deploy.yaml \
    root@124.71.69.165:/home/tester/pity-deploy/
scp /Users/zhanzhicai/Desktop/py/AIFullStackTesting/backend/ops/dev.env.ops \
    root@124.71.69.165:/home/tester/pity-deploy/

cat > /tmp/pity-deploy-env <<'EOF'
MYSQL_ROOT_PASSWORD=DemoMysql-2026!
REDIS_PASSWORD=DemoRedis-2026!
SWR_REGISTRY=swr.cn-south-1.myhuaweicloud.com
SWR_ORG=pity
TAG=v0.2
EOF
scp /tmp/pity-deploy-env root@124.71.69.165:/home/tester/pity-deploy/.env
```

#### E. SWR login + pull + up(server ssh)

```bash
ssh root@124.71.69.165
cd /home/tester/pity-deploy

docker login -u "$SWR_USER" -p "$SWR_PASS" "$SWR_REGISTRY"

# pull(底层会拉 mysql:8.0 + redis:7-alpine from docker.io,以及 3 个自建 from SWR)
docker compose -f docker-compose.deploy.yaml --env-file .env pull

# up -d:5 容器都起
docker compose -f docker-compose.deploy.yaml --env-file .env up -d
```

#### F. 验证

```bash
docker compose -f docker-compose.deploy.yaml ps
# 期望 5 服务全 Up:
#   pity_mysql_deploy / pity_redis_deploy / pity_backend_deploy / 
#   pity_frontend_deploy / pity_nginx_deploy

curl -s -o /dev/null -w "backend_direct: %{http_code}\n" http://localhost:7777/
curl -s -o /dev/null -w "nginx→api:      %{http_code}\n" http://localhost/api/auth/register
curl -s -o /dev/null -w "frontend:      %{http_code}\n" http://localhost/

df -h /
docker stats --no-stream
```

#### G. Mac 浏览器开

如果服务器**公网 IP 的 80 端口允许入站**(Flexus 控制台安全组规则):

```bash
open http://124.71.69.165/
```

应该看到 Pity 登录页。

### Step 4 — GitHub Actions 自动 push/deploy

⏸ **延后**。等手动流程跑稳、确认 demo 真的"work",再讨论自动化。届时从新写一个 `.github/workflows/deploy-docker.yml`,保留 §10.4 的草稿作参考。

---

## 7. 失败教训(踩过的坑,几乎全是要躲着的)

### 7.1 SWR + docker CLI manifest 解析 bug ⭐

**现象**:`docker push` 反复 `error from registry: Invalid image, fail to parse 'manifest.json'`,所有 layer 都传完(`Layer already exists`)。

**根因**:docker CLI 推 manifest v2.2 跟 SWR 解析器协议层有 bug。同一份 image,本地 docker save/inspect 都正常,只有最后 PUT manifest.json 那一步 SWR 解不出来。

**无效尝试**:换 tag (`dev` → `v0.1`)、SWR 控制台删整个仓库重推。

**最终修法**:**换 skopeo**,直发 OCI distribution-spec HTTP。验证 `pity-backend:v0.2` 一次成功。

**适用范围**:华为云 SWR、阿里云 ACR、腾讯云 TCR 都有类似问题。**docker CLI 推国产 registry 普遍不可靠**,推之前先 `skopeo copy` 试试。

### 7.2 docker compose plugin 缺失(server)

**现象**:`docker compose version` 报 `unknown command: docker compose`。

**根因**:华为云 Ubuntu 22.04 `docker.io` 包(版本 `29.1.3-0ubuntu3~22.04.2`)不带 compose plugin。Docker 官方仓库才会打包 `docker-compose-plugin`。

**修法**:见 §6 步骤 B,要么 `apt install docker-compose-plugin`,要么下 GitHub 二进制。

### 7.3 DaoCloud mirror 拉 buildkit 失败(被绕开)

**现象**:`docker buildx` 报 `dial tcp: lookup docker.m.daocloud.io: no such host`。

**根因**:`docker buildx` 用的 `docker-container` driver 要先拉 `moby/buildkit:buildx-stable-1`,DaoCloud mirror 在我们网络下 DNS 不通。

**影响范围**:**零**。这台 Mac 是 **Intel(x86_64)**,`docker build` 默认就是 `linux/amd64`,不需要 cross-build,`buildx` 完全用不到。如果以后切到 M 系列 Mac,得换 mirror(`daemon.json` 里 `registry-mirrors: ["https://hub-mirror.c.163.com"]`),或者用 buildx。

### 7.4 server 上 dev.env.ops 缺失 → bind mount 失败

**现象**:`docker compose up -d backend` 报 `mount src=.../dev.env.ops, dst=/pity/conf/dev.env, ... not a directory: Are you trying to mount a directory onto a file`。

**根因**:bind mount 的 host 路径 `./dev.env.ops` 不存在,docker engine **自动建空目录**(`drwxr-xr-x` 4096 字节)当作 bind source,后续 mount 时用 `MS_REC`(mount subtree recursively,目录专用)挂到文件位置失败。

**修法**:compose 里用 `env_file: ./dev.env.ops` 替代 bind mount。env_file 把文件内容当 ENV 变量注入容器,pydantic Settings 直接消费,**不涉及 bind mount**。

### 7.5 nginx 单一 /api/ 前缀不匹配前端

**现象**:前端点 Register 报 `Request failed with status code 404`,response body 是 nginx 默认 404 HTML(`<title>404 Not Found</title>`)。

**根因**:
- `frontend/config/proxy.ts` 配了 11 个前缀的代理(`/api/`, `/auth/`, `/testcase/`, `/config/`, `/project/`, `/operation/`, `/workspace/`, `/oss/`, `/notification/`, `/online/`, `/request/`),但 nginx 只接 `/api/`
- 其余 10 个落到 `location /` → 转给 frontend nginx → frontend 没这静态资源 → 404

**修法**:nginx.conf 改成正则一次覆盖 11 个前缀,`proxy_pass http://backend:7777;`(无末尾 /,保留 URI)。

### 7.6 Dockerfile.production ERESOLVE(peer dep 冲突)

**现象**:`npm ci` exit 1,日志里 `npm error code ERESOLVE`、`@ant-design/charts@1.4.3` 要 `antd@^4.6.3`,实际装 `antd@5.29.3`。

**根因**:UmiJS v4 + Ant Design v5 之间 peer dep 不兼容。`@ant-design/charts` v1.x 是给 antd 4.x 设计的,**根本不支持 antd 5**。npm 7+ 严格 peer dep 检查 fail。

**修法**:加 `--legacy-peer-deps`(切回 npm 6 宽松解析)。这只 install 时通过,运行时 charts 渲染用 antd 5 实际 API,有可能有问题。如果运行时炸,就得换 `@ant-design/charts` 到 v2.x。

### 7.7 GnuTLS `non-properly terminated`(死代码间接引发)

**现象**:`wget https://github.com/vishnubob/wait-for-it/...` 报 `GnuTLS: The TLS connection was non-properly terminated`。

**根因**:wait-for-it.sh 是 2015 年的等"MySQL TCP listen 之前不起 gunicorn"的脚本,**全仓 grep 后确认无人引用**,supervisor.conf 只起 gunicorn。这段 wget 跟证书不兼容是次要问题,**根本不需要修**.

**修法**:删死代码(`apt install -y wget` + `wget ... wait-for-it` + final stage 的 COPY + chmod)。真正的"等 MySQL 就绪"由 docker compose `depends_on.condition: service_healthy` + 服务 healthcheck 处理(见 §9 后续)。

---

## 8. 验证清单(部署完成后必过)

- [ ] 主机 `:80` 能打开 web 前端(Pity 登录页)
- [ ] 主机 `:80/api/auth/register` 返回 200 / 422(到达后端,不是 404)
- [ ] 前端走完整注册流程,后端入库成功
- [ ] MySQL 数据落盘到 `/home/tester/pity-data/mysql`,`docker compose restart mysql` 后数据仍在
- [ ] Redis 数据落盘到 `/home/tester/pity-data/redis`
- [ ] **`/`(根分区)使用率 < 80%**,且 `du -sh /home/tester/pity-data/*` 各子目录未超过 §2 预算
- [ ] docker system 干净:`docker image ls` 中无用 `<none>` 镜像已 `docker image prune` 清理
- [ ] `docker stats` 各容器内存均不超过 limits(backend 600M / mysql 700M / redis 80M / frontend+nginx 各 30M)
- [ ] 重启某容器(`docker compose restart <service>`)后,5 个服务自动回到 healthy
- [ ] `df -h /` 在重启后仍 < 80%

---

## 9. 已知未做(TODO 列表)

### 文档同步

- [ ] `docs/DEPLOY_RUNBOOK.md` 还是用 `/data/mysql` / `/data/redis` 旧假设,需要按本文 §2 单盘 + §7.4 env_file 同步
- [ ] `docs/DB_MIGRATION_DEV_PRO_SPLIT.md` 用了 `/data/pity.db` 旧假设,需要同步

### 持久化收尾

- [ ] `push-to-swr.sh` 已支持 skopeo;`scripts/deploy.sh`(Mac 一键:本地 build + skopeo push + ssh pull & up)还没写,下次补
- [ ] server 上的 `docker-compose.deploy.yaml` 本地同步(nginx 钉 v0.3 + 其他 `${TAG:-v0.2}` 默认)
- [ ] nginx:v0.4 时(下次有 fix),server 上 nginx image tag 也要同步升

### 运维

- [ ] 系统盘使用率监控 cron / systemd timer(§2 给了脚本)
- [ ] logrotate 落地(目前 docker 自己轮转,中间会丢几行;推荐 `copytruncate`)
- [ ] 华为云 Flexus 控制台 → 云备份 → 凌晨 02:00 全量快照
- [ ] SWR 临时凭证自动续期(目前 12h 手贴)

### 后端

- [ ] `backend/conf/pro.env` 生成(目前 deploy 用 `pity_env=dev` + dev.env.ops,真正 pro env 时切)
- [ ] `depends_on.condition: service_healthy` + mysql/redis 健康检查(替代当年 wait-for-it.sh 的用途,见 §7.7)

### 安全

- [ ] HTTPS(Caddy 一键反向代理 + Let's Encrypt)
- [ ] MYSQL/REDIS 密码轮换(目前 demo 密码是 `DemoMysql-2026!`)

### GitHub Actions

- [ ] 自动 build + push SWR(原 §10.4 草稿保留,可参考)
- [ ] 自动部署到 server(`appleboy/ssh-action` + `docker compose pull && up`)

---

## 10. Commit 索引(2026-10-14 当日改动)

```bash
git log --oneline -10 main
# 倒序(今天的 commit,晚上一并 git push):
#   d28d4c7 fix(deploy): 持久化 nginx 11-prefix 转发规则 + 修 dev.env.ops 脆弱的 bind mount
#   c881b07 fix(scripts): push-to-swr.sh 改走 skopeo,绕开 docker push 的 SWR manifest bug
#   56950e3 chore(backend): 切换 pip 镜像源至华为云(SWR 加速)        ← 用户中间插的 commit
#   c47bed7 fix(frontend): Dockerfile.production 加 --legacy-peer-deps
#   b708acb chore(backend): 去掉 wait-for-it.sh 死代码 + 修 lint as → AS
#   297e3d2 chore(frontend): dev Dockerfile 升 Node 20 + 去 cnpm 老黄历 + 改用 npm ci
#   981d741 fix(backend): 对齐后端 dockerfile 基础镜像到 python:3.10-slim(本地 conda 同版本)
#   0e433b2 feat(deploy): 新增 docker 部署资产(nginx 反代 + 多阶段前端镜像 + 5 服务 compose)
#   71647f5 docs(deploy): 改单盘 40G 假设,补 §2.6 容量预算与 MySQL/Redis 限大小参数
```

老文档被此 commit 覆盖;旧 git 历史里 `docs/DEPLOY_DOCKER_MIGRATION.md` 还有 2026-10-13 那份,要回看跑 `git log --follow docs/DEPLOY_DOCKER_MIGRATION.md`。

---

## 11. 给接手人的话

- 服务器密码、SWR 凭证等敏感信息**绝对不要 commit**;`.env` 后缀的文件已在 root `.gitignore` 范围内
- 每次部署完跑一次 `df -h /` 确认 40G 余量;docker image 自带 layer cache,5G 以内 build 一次不爆
- 想重新做架构 / 选型,看 §0 决策树 + §3 资源,每个选择都有 rationale
- 踩过的坑:**先看 §7 失败教训**,80% 的问题那里都有
- 部署流程:严格走 §6,别跳步骤(尤其 §6.B 装 compose plugin、§6.E pull + up 都得 set env)

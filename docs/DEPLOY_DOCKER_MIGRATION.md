# 前端 + 后端 Docker 化部署迁移计划

> 目标:把 `.github/workflows/` 里 SCP + gunicorn + PM2 的"老办法"换成**单机 Docker Compose 部署**,让前端(nginx 静态)与后端(FastAPI/Pity)共享一套编排,在 1 台 2 核 2G 华为云 Flexus 上跑通个人 demo。
>
> 状态:**诊断已出,待用户拍板**。本文档只描述现状 / 目标 / 路线,不动现有 workflow。

---

## 1. 部署目标(用户原话)

- 单台华为云 Flexus `ahf.large.1.40g.2m`,2 核 2G 内存 / **仅 40G 系统盘,无独立数据盘** / 2M 带宽
- 个人 demo,不要求 7×24 / 不要求 HA
- 前端 + 后端**全部走 Docker**,跟开发环境隔离,跟 demo 部署流程统一
- 系统盘是**唯一**磁盘 → MySQL 数据、Redis 持久化、应用日志、Docker 镜像层全部挤在这里,容量预算见 §2.6

---

## 2. 现状盘点

### 2.1 现有部署链路(`.github/workflows/`)

| workflow | 触发 | 动作 |
|---|---|---|
| `deploy-backend.yml` | push 到 main 且 `backend/**` 变更 | SCP `backend/` 到 `/home/tester/pity/` → 主机 `pip3 install -r requirements.txt --user` → `pkill gunicorn` |
| `deploy-frontend.yml` | push 到 main 且 `frontend/**` 变更 | CI 跑 `npm run build` → SCP `frontend/dist/` 到 `/home/tester/pityWeb/` → `pm2 delete web \|\| true && pm2 start web.sh` |

需要的 GitHub Secrets:`HOST`、`USERNAME`、`PASSWORD`(都用密码登录,SSH Key 方式更安全但当前不是)。

### 2.2 现有 Docker 资产

- `backend/ops/dockerfile` — 多阶段 `python:3.9-slim + builder`,镜像内部用 `supervisord` 起 `gunicorn main:pity -b 0.0.0.0:7777 -w 8`。
- `backend/ops/docker-compose.yaml` — dev 用三件套(`mysql:8.0` / `redis` / `pity` 后端),**没有前端容器**。
- `backend/ops/supervisor.conf` — 容器内的 supervisord 配置文件,启动 1 个 gunicorn 进程(8 worker)。
- `backend/ops/dev.env.ops` — 当前 dev 用的环境文件(被 mount 进容器当 `/pity/conf/dev.env`)。

### 2.3 现有前端 docker 资产

**没有**。前端的部署链路完全在主机(`/home/tester/pityWeb/`),靠 PM2 起 `web.sh`,没有 Dockerfile,也没有 nginx。

### 2.4 现有的"反模式"或不一致

| 项 | 不一致点 |
|---|---|
| `deploy-backend.yml` 主机路径 | 假设主机已经"裸机 Python + gunicorn + supervisord",如果未来切到容器,这条链路完全用不上 |
| `docker-compose.yaml` 只跑 backend | dev 是开发用,但生产部署 plan 没覆盖前端 → 一台机器要两套并存 |
| gunicorn `-w 8` | 8 worker 在 2G 内存下风险:每个 worker 内存常驻 80–150MB,叠起来轻松 OOM |
| MySQL 密码明文 `Pitytester666666` 写在 yml | 推到 git 即泄,即使 demo 也建议用 `.env` 或 Vault |
| 端口分散 | 前端走 PM2(端口待确认 `web.sh`)+ 后端 7777 + MySQL 3306 + Redis 6379,没有统一入口,不发证书 |
| 没有 nginx 反代 | 前端静态产物的访问、后端 `/api` 路由、CORS 配置都得在 nginx 层处理,目前散在前后端 |
| `frontend/deploy.sh` 把 dist 复制到 `backend/statics/` | 老 Pity 的"前后端同进程"思路,Docker 化以后不必再这么干 — 前端走独立 nginx 容器 |

### 2.5 资源现实

| 资源 | 评估 |
|---|---|
| 2 核 CPU | 单容器进程够用,但 8 worker gunicorn 在请求突发时容易双核跑满 |
| 2G 内存 | MySQL 8.0 idle ~500-700MB、Redis ~50MB、backend gunicorn `-w 2` ~250MB、nginx ~20MB,合计 ~1GB,可挤但要小心 |
| 系统盘 40G(**唯一磁盘**) | 镜像、容器运行时、MySQL 数据、Redis 持久化、应用日志**全**在此盘。MySQL/Redis 路径从原 `/data/...` 改到 `/home/tester/pity-data/...`(也在系统盘);**必须**做容量预算 + 日志/binglog/AOF 回收 + 监控,详见 §2.6 |
| 2M 带宽 | `docker pull` 速度慢,镜像尽量本地 build 或提前拉取;scp 上传中小 frontend dist(<5M) 没压力 |

---

### 2.6 单盘 40G 容量预算(必读,基于"只有系统盘"前提)

40G 系统盘的可用空间,按以下口径切;**留 8–10G buffer** 给 OS + apt 缓存 + Docker 引擎自身增长,**不要让数据落满到 90% 以上**,否则 apt/docker/journald 都开始报错。

| 类别 | 路径 | 预算上限 | 回收策略 |
|---|---|---|---|
| 镜像层(含 builder cache) | `/var/lib/docker` + `/tmp`(builder) | ~6G | `docker builder prune -af --filter "until=72h"` 每周 cron;`docker system prune` 手敲 |
| MySQL 数据 | `/home/tester/pity-data/mysql` | ~8G | `expire_logs_days=3`、`innodb_file_per_table`、`max_binlog_size=100M` |
| Redis 数据 | `/home/tester/pity-data/redis` | ~500M | AOF only、`appendfsync everysec`、`auto-aof-rewrite-min-size 64mb` |
| 应用日志(gunicorn + nginx) | `/home/tester/pity-data/logs/{pity,nginx}` | ~2G | logrotate 按天切,保留 14 天,`copytruncate` 不停服 |
| MySQL binlog + slow log | `/home/tester/pity-data/logs/mysql` | ~1G | `expire_logs_days=3`,slow log 用 logrotate |
| 部署包 + 临时上传 | `/home/tester/pity-deploy` | ~2G | `rm /tmp/pity-deploy.tgz` 后留 release 目录 |
| 系统自身 | `/`、`/var/log/journal`、`/var/cache/apt` | ~10G | journald `SystemMaxUse=200M`、apt `clean` 周期 |
| **Buffer(headroom)** | — | **~10G** | 任何单类别超过预算要先报警 |

**磁盘占用监控(必装):** systemd timer 或 cron 跑:

```bash
USAGE=$(df -P / | awk 'NR==2 {print $5}' | tr -d '%')
[ "$USAGE" -ge 70 ] && logger -t pity-disk "WARN rootfs ${USAGE}%"
[ "$USAGE" -ge 85 ] && logger -t pity-disk "CRIT rootfs ${USAGE}%"
```

`logger` 走 journald,`SystemMaxUse=200M` 兜底不让日志也吃满。

**Docker 引擎建议:** Docker data-root 默认就在 `/var/lib/docker`(系统盘),不动;如果以后真撑不住再考虑 `/home/tester/docker` 软链接(这次不做)。

---

## 3. 目标架构

```
                        ┌──────────────────────┐
                        │   外部用户访问        │
                        │ (浏览器/HTTP/HTTPS)  │
                        └──────────┬───────────┘
                                   │ :80
                          ┌────────▼────────┐
                          │  nginx (容器)   │
                          │  - /api/* → backend:7777
                          │  - 其他 → frontend:80
                          └────┬─────────┬──┘
                               │         │
                  /api/*       │         │  /
                               │         │
                  ┌────────────▼─┐    ┌──▼────────────┐
                  │  backend     │    │  frontend     │
                  │  (pity 容器) │    │  (nginx 静态   │
                  │  gunicorn -w2│    │   容器,纯 dist)│
                  └─┬──────────┬─┘    └───────────────┘
                    │          │
                    │          │
              ┌─────▼──┐   ┌───▼────┐
              │ MySQL 8│   │ Redis  │
              └────────┘   └────────┘
              ↓ bind mount 到系统盘
        /home/tester/pity-data/mysql
        /home/tester/pity-data/redis
        /home/tester/pity-data/logs/{pity,nginx,mysql}
```

### 3.1 服务清单(单机 Docker Compose)

| 服务 | 镜像 | 端口(对外) | 内存预估 | 数据卷 |
|---|---|---|---|---|
| `nginx` | 自建(`nginx:1.27-alpine` + 自定义 `nginx.conf`) | 80 (→ host 80) | ~20MB | 只读挂 `dist/` 也可省 |
| `frontend` | 自建(`nginx:alpine` + COPY dist/) | 仅内网 | ~20MB | 无 |
| `backend` (`pity`) | 自建(`backend/ops/dockerfile` 改 `-w 2`) | 仅内网 | ~250MB | `/home/tester/pity-data/logs/pity` |
| `mysql` | `mysql:8.0` | 仅内网 | ~500-700MB | `/home/tester/pity-data/mysql` |
| `redis` | `redis:7-alpine` | 仅内网 | ~50MB | `/home/tester/pity-data/redis` |

**端口只对外暴露 80(或 443)**。MySQL / Redis / backend / frontend 全部走 docker network 内网通信。

### 3.2 资源限制(防止 OOM)

每条 service 加 `deploy.resources.limits`:

```yaml
deploy:
  resources:
    limits:
      memory: 600M    # backend
    reservations:
      memory: 200M
```

具体每个服务的限额在下节给出。

---

## 4. 实施路线(分三阶段)

### 阶段 1:新增 Docker 部署资产(不动现有 dev 链路)

放在新文件,跟 `backend/ops/` 已有的 dev compose 区分:

```
backend/ops/
├── dockerfile                    # 已有,需要把 -w 8 改成 -w 2
├── docker-compose.yaml           # 已有,dev 用,不动
├── docker-compose.deploy.yaml    # 新增,单机生产 / demo 用
├── supervisor.conf               # 已有,跟随 dockerfile 调整
├── dev.env.ops                   # 已有,给容器用
└── pro.env.ops                   # 新增(从 backend/conf/pro.env 复制一份,容器挂载用)

frontend/
├── Dockerfile                    # 新增(nginx:alpine + COPY dist)
├── .dockerignore                 # 新增(排除 node_modules / dist)
└── deploy.sh                     # 已有,旧版"塞到 backend/statics"模式,Docker 化后不再需要

nginx/
├── Dockerfile                    # 新增(nginx:1.27-alpine + COPY nginx.conf)
└── nginx.conf                    # 新增(/api/* 反代 + 默认静态)

deploy.sh                         # 仓库根,新增(本地构建 + scp 推送 + 远端 up)
```

#### 1.1 调整 `backend/ops/dockerfile`(降 worker)

把 supervisor.conf 里的 `-w 8` 改成 `-w 2`,再观察一段时间再调。

#### 1.2 新增 `frontend/Dockerfile`

```dockerfile
FROM nginx:1.27-alpine
COPY dist/ /usr/share/nginx/html/
EXPOSE 80
```

加 `.dockerignore` 排除 `node_modules` 和 `dist`。

#### 1.3 新增 `nginx/nginx.conf`

```nginx
server {
    listen 80;
    server_name _;

    # 后端反代
    location /api/ {
        proxy_pass http://backend:7777/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    # 前端静态
    location / {
        proxy_pass http://frontend:80;
    }
}
```

> 严格起见,前端也可以直出:`root /usr/share/nginx/html`,这里用反代是为了后续加 HTTPS / 静态资源缓存策略更顺手。

#### 1.4 新增 `backend/ops/docker-compose.deploy.yaml`

```yaml
version: "3.8"
services:
  mysql:
    image: mysql:8.0
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: pity
    command:
      - --expire_logs_days=3
      - --max_binlog_size=104857600
      - --innodb_file_per_table=1
    volumes:
      - /home/tester/pity-data/mysql:/var/lib/mysql
      - /home/tester/pity-data/logs/mysql:/var/log/mysql
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 700M }

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --appendonly yes
      --appendfsync everysec
      --save ""
      --auto-aof-rewrite-min-size 64mb
      --auto-aof-rewrite-percentage 100
    volumes:
      - /home/tester/pity-data/redis:/data
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 80M }

  backend:
    build:
      context: ../
      dockerfile: ops/dockerfile
    restart: unless-stopped
    env_file: pro.env.ops
    depends_on: [mysql, redis]
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 600M }

  frontend:
    build: ../frontend
    restart: unless-stopped
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 30M }

  nginx:
    build: ../nginx
    restart: unless-stopped
    ports:
      - "80:80"
    depends_on: [backend, frontend]
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 30M }

networks:
  appnet:
    driver: bridge
```

`.env`(或实际注入方式)放 `MYSQL_ROOT_PASSWORD` / `REDIS_PASSWORD`,**不再明文写在 yml 里**。

### 阶段 2:写 `deploy.sh`(本地推送)

仓库根新增 `deploy.sh`(可执行):

```bash
#!/usr/bin/env bash
set -euo pipefail
HOST="$1"   # ssh 目标,如 test@1.2.3.4
REMOTE_DIR="/home/tester/pity-deploy"

# 1. 本地 build(任何改了前端/后端代码的提交)
( cd frontend && npm ci && npm run build )

# 2. 打包要 scp 的内容(排除大文件/不必要)
tar czf /tmp/pity-deploy.tgz \
  --exclude=node_modules \
  --exclude=.git \
  --exclude=__pycache__ \
  --exclude=logs \
  backend frontend nginx deploy.sh docker-compose.deploy.yaml pro.env.ops

# 3. 推送到服务器
ssh "$HOST" "mkdir -p $REMOTE_DIR"
scp /tmp/pity-deploy.tgz "$HOST:$REMOTE_DIR/"

# 4. 远端:解压 + up
ssh "$HOST" <<'REMOTE'
  cd /home/tester/pity-deploy
  tar xzf pity-deploy.tgz
  cd backend/ops
  docker compose -f docker-compose.deploy.yaml --env-file .env up -d --build
REMOTE
```

### 阶段 3:GitHub Actions(可选)

两个方案二选一,**看用户偏好**:

- **方案 A**:保留现有两个 yml,在 workflow 里调 `deploy.sh`(把 secrets 转给脚本)。最小改动。
- **方案 B**:重写为 `deploy.yml`,在 CI 里只 build image,推到服务器(用 `appleboy/scp-action` 上传 tarball),再 ssh 上去 `docker compose up`。结构清晰,跟 dockerfile 一致。

> 暂时推荐方案 A,改动最小,可以逐步切到方案 B。

---

## 5. 风险与备选

| 风险 | 影响 | 应对 |
|---|---|---|
| 2G 内存紧张 | 4 容器同时跑可能 OOM | 加 `deploy.resources.limits.memory`;预留 200-400MB 给 OS / buffer |
| MySQL 8 默认有 `caching_sha2_password` 鉴权 | 后端 pymysql / sqlalchemy 需兼容(已 OK) | 启动后建库,不要用 root 业务连接 |
| 镜像 build 慢 | 2M 带宽拉 `python:3.9-slim` 镜像 60-100MB 首次拉取 ~5-10 分钟 | 国内服务器换 `registry.cn-hangzhou.aliyuncs.com/library/python:3.9-slim` 或 `swr.cn-north-4.myhuaweicloud.com` |
| 没有 HTTPS | 个人 demo 浏览器会拦 mixed content | 阶段 2 先 HTTP,以后挂 CDN / Let's Encrypt |
| gunicorn 单 worker 处理静态慢 | 后端 `/` 返回 simple html | 不影响 demo 演示 |
| `deploy.sh` 的密码明文 | `USERNAME` `PASSWORD` 直接写在 Actions secrets 里可以,但脚本里 `ssh` 也用密码 | 改成 SSH Key 部署更安全(个人 demo 可缓) |
| MySQL 数据迁移 | 第一次 up 时数据库是空的 | 启动后跑 `alembic upgrade head` 或用 `Base.metadata.create_all`(main.py 已自动建表) |
| docker-compose 旧版 / v2 兼容性 | 华为云默认 docker 大概率是 19+ | 用 `version: "3.8"` + `docker compose`(v2 CLI) |
| `deploy-backend.yml` / `deploy-frontend.yml` 与新部署共存 | 老链路可能跟新链路争同一个 `:7777` | 老 yml 不要重复触发;可以先手动 disable 老 workflow |

### 备选部署方案(供选择)

| 方案 | 优点 | 缺点 | 适合 |
|---|---|---|---|
| **A: 腾讯云/华为云镜像仓库(SWR/CCR)** | 镜像版本化、CI 推 / 服务器 pull,跟 GitHub Actions 协作好 | 多一个镜像仓库配置;2M 带宽 push 也慢 | 团队协作 |
| **B: 阿里云 ACR 个人版** | 中国访问快 | 个人版有额度上限 | 国内 demo |
| **C: 本地 build + scp tgz** | 不需要镜像仓库、流程简单 | image 不能跨机复用;每次 build 浪费 | **个人单台 demo(推荐)** |
| **D: 服务器上跑 CI runner(自建 GitHub Actions Runner)** | push 即触发,不需要 secrets 暴露 | runner 自身要维护;2G 内存紧张 | 长期项目 |

---

## 6. 验收清单

部署完以后,以下必须可验证:

- [ ] 主机 `:80` 能打开 web 前端
- [ ] 主机 `:80/api/...` 接口能返回 `{"code": 0, ...}` 风格的数据(任选一个接口)
- [ ] MySQL 数据落盘到 `/home/tester/pity-data/mysql`,服务器重启后数据仍在
- [ ] Redis 数据落盘到 `/home/tester/pity-data/redis`
- [ ] **`/` (根分区) 使用率 < 80%**,且 `du -sh /home/tester/pity-data/*` 各子目录未超过 §2.6 预算
- [ ] docker system 干净:`docker image ls` 中无用 `<none>` 镜像已 `docker image prune` 清理
- [ ] `docker stats` 各容器内存均不超过 limits
- [ ] 重启某容器(down && up)后,5 个服务自动回到 healthy
- [ ] (可选)GitHub push backend/** 自动触发部署

---

## 7. 回滚方案

- 老 yml 文件**保留不动**(不删 `.github/workflows/deploy-{backend,frontend}.yml`)
- 主机上 `/home/tester/pity/` 老目录不动,docker 部署在同一机器的另一目录(`/home/tester/pity-deploy` 或类似)
- 如果新部署出问题,回退只改 nginx 端口或停止新部署即可
- 真正回滚:把 docker compose down,再手动 `pm2 start` 老 web.sh(或者 `pkill gunicorn && nohup gunicorn ... &`)

---

## 8. 后续可选优化

- [ ] 切 HTTPS(Caddy 自动证书最省事)
- [ ] 加 `healthcheck` 到 docker-compose 让 `docker compose ps` 真实反映状态
- [ ] `frontend/Dockerfile` 改成多阶段 build:`node:20` build dist → `nginx:alpine` 部署,镜像更小
- [ ] ~~数据盘 LVM / 快照备份~~ → **改**:基于单盘的系统盘 in-place 备份(`mysqldump` + `redis-cli BGSAVE` → `/home/tester/pity-data/backup/`),周期同步到对象存储(华为云 OBS / 阿里云 OSS / 腾讯云 COS);Flexus 单盘快照由控制台负责
- [ ] 老 workflow yml 删除
- [ ] 把 `frontend/deploy.sh`(老版"塞到 backend/statics")删掉

---

## 9. 待用户拍板的项

| # | 项 | 状态 | 备注 |
|---|---|---|---|
| 1 | Docker Compose 单机方案 | ✅ 已选 B | 前后端都做镜像 + nginx 反代,见 §11 |
| 2 | HTTPS | ❓ 暂不挂 | demo 阶段不上,后续 Caddy 一行加 |
| 3 | 数据库密码处理 | ❓ `.env` 优先 | `.env` 不入库,本地可临时硬编码 |
| 4 | GitHub Actions 迁移 | ⏸ **延后** | 见 §11.4,先把手动 4 步跑顺再接 actions |
| 5 | 旧 yml 处置 | ❓ 暂保留 | 作为"老部署方式归档"留底,不动 |
| 6 | MySQL 初始数据 | ❓ 首次空 | `docker compose up` 后空库,需手工灌或 scp 老 dump |
| 7 | 单盘布局路径 | ✅ bind mount | `/home/tester/pity-data/...` 已在 §2.6 + §11.3 落实 |
| 8 | 日志回收 logrotate | ❓ 推荐 copytruncate | gunicorn/nginx/MySQL slow log 走 logrotate `copytruncate` |
| 9 | 系统盘云备份 | ❓ 推荐凌晨 02:00 | Flexus 控制台定时快照兜底 |

---

## 10. 决策记录(2026-10-13)

**已选定方案 A:华为云 SWR + GitHub Actions**(原"## 5 风险与备选"中的方案 A)。

### 10.1 路线差异(与本文档原阶段 2 / 阶段 3 的区别)

| 阶段 | 原方案 | 调整后 |
|---|---|---|
| 阶段 1:docker 资产 | 不变 | 不变 |
| **阶段 2:构建产物** | 本地 `deploy.sh` scp tgz | **CI 构建 → push 到 SWR**(由 GitHub Actions 完成) |
| **阶段 3:服务器部署** | 主机 `docker compose up --build` | 主机 `docker compose pull && up -d`(从 SWR 拉) |
| **触发方式** | push 触发,Actions 内部 scp 上传 | push 触发,Actions 内部 `docker push` 到 SWR + `ssh` 远端 `pull && up` |
| **方案 C(scp tgz)** | 已降级为 fallback(临时调试用) | 不在主流程里 |

### 10.2 镜像拆分(3 个独立镜像)

| 镜像 | Dockerfile 来源 | SWR 命名(示例)|
|---|---|---|
| `pity-backend` | `backend/ops/dockerfile`(改 `-w 2`)| `swr.<region>.myhuaweicloud.com/<org>/pity-backend:<sha>` |
| `pity-frontend` | 新增 `frontend/Dockerfile`(`nginx:alpine + COPY dist/`,多阶段更佳)| `swr.<region>.myhuaweicloud.com/<org>/pity-frontend:<sha>` |
| `pity-nginx` | 新增 `nginx/Dockerfile + nginx.conf`(反代 `/api/`) | `swr.<region>.myhuaweicloud.com/<org>/pity-nginx:<sha>` |

> 选 3 个独立镜像而不是 1 个合并大镜像,改动频率不均(前端 CSS 改动不应触发后端 mirror 重 build)。

### 10.3 GitHub Secrets(从 3 个扩到 5 个)

| Secret | 旧 | 新增 |
|---|---|---|
| `HOST` | ✅ | — |
| `USERNAME` | ✅ | — |
| `PASSWORD`(或 `SSH_KEY`) | ✅ | — |
| `SWR_USER` | — | ✅ SWR 临时登录凭证用户名(默认是 organization 路径,如 `cn-north-4@<org>`)|
| `SWR_PASS` | — | ✅ SWR 临时登录凭证密码(12 小时过期,每次 Action 任务运行时新生成一个)|

### 10.4 GitHub Actions 草稿

`deploy-backend.yml`(改写为 SWR push):

```yaml
name: Build & Push pity-backend (SWR)

on:
  push:
    branches: [main]
    paths: ['backend/**']
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Login to SWR
        uses: docker/login-action@v3
        with:
          registry: ${{ vars.SWR_REGISTRY }}      # 仓库变量,例如 swr.cn-north-4.myhuaweicloud.com
          username: ${{ secrets.SWR_USER }}
          password: ${{ secrets.SWR_PASS }}

      - name: Build & push
        uses: docker/build-push-action@v5
        with:
          context: ./backend
          file: ./backend/ops/dockerfile
          push: true
          tags: |
            ${{ vars.SWR_REGISTRY }}/${{ vars.SWR_ORG }}/pity-backend:${{ github.sha }}
            ${{ vars.SWR_REGISTRY }}/${{ vars.SWR_ORG }}/pity-backend:latest

      - name: Trigger remote pull & up
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.HOST }}
          username: ${{ secrets.USERNAME }}
          password: ${{ secrets.PASSWORD }}
          script: |
            cd /home/tester/pity-deploy
            docker login -u "$SWR_USER" -p "$SWR_PASS" $SWR_REGISTRY
            docker compose -f docker-compose.deploy.yaml --env-file .env pull backend
            docker compose -f docker-compose.deploy.yaml --env-file .env up -d backend
          envs: SWR_REGISTRY,SWR_USER,SWR_PASS
```

`deploy-frontend.yml`(改写为 SWR push,先 build 后端 npm dist 再打前端镜像):

```yaml
name: Build & Push pity-frontend (SWR)

on:
  push:
    branches: [main]
    paths: ['frontend/**']
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }

      - name: Build frontend dist
        working-directory: frontend
        run: |
          npm ci || npm install
          npm run build

      - name: Login to SWR
        uses: docker/login-action@v3
        with:
          registry: ${{ vars.SWR_REGISTRY }}
          username: ${{ secrets.SWR_USER }}
          password: ${{ secrets.SWR_PASS }}

      - name: Build & push pity-frontend image
        uses: docker/build-push-action@v5
        with:
          context: ./frontend
          push: true
          tags: |
            ${{ vars.SWR_REGISTRY }}/${{ vars.SWR_ORG }}/pity-frontend:${{ github.sha }}
            ${{ vars.SWR_REGISTRY }}/${{ vars.SWR_ORG }}/pity-frontend:latest

      - name: Trigger remote pull & up
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.HOST }}
          username: ${{ secrets.USERNAME }}
          password: ${{ secrets.PASSWORD }}
          script: |
            cd /home/tester/pity-deploy
            docker login -u "$SWR_USER" -p "$SWR_PASS" $SWR_REGISTRY
            docker compose -f docker-compose.deploy.yaml --env-file .env pull frontend nginx
            docker compose -f docker-compose.deploy.yaml --env-file .env up -d frontend nginx
```

> 用 GitHub **Vars**(仓库变量)而不是 Secrets 放 `SWR_REGISTRY` 和 `SWR_ORG`,因为这些不是机密。SWR_USER / SWR_PASS 才进 Secrets。

### 10.5 `docker-compose.deploy.yaml` 调整为 pull-based

把 `build:` 改成 `image:`,从 SWR 拉预构建镜像:

```yaml
services:
  backend:
    image: ${SWR_REGISTRY}/${SWR_ORG}/pity-backend:${TAG:-latest}
    restart: unless-stopped
    env_file: pro.env.ops
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 600M }

  frontend:
    image: ${SWR_REGISTRY}/${SWR_ORG}/pity-frontend:${TAG:-latest}
    restart: unless-stopped
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 30M }

  nginx:
    image: ${SWR_REGISTRY}/${SWR_ORG}/pity-nginx:${TAG:-latest}
    restart: unless-stopped
    ports: ["80:80"]
    depends_on: [backend, frontend]
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 30M }

  mysql:    # 仍用 docker hub 公开镜像;volumes / command 与 §1.4 一致(/home/tester/pity-data/mysql 等)
    image: mysql:8.0
    # ...
  redis:    # volumes / command 与 §1.4 一致(/home/tester/pity-data/redis;AOF 限大小参数同 §1.4)
    image: redis:7-alpine
    # ...
```

> 主机上 `/home/tester/pity-deploy/.env` 应包含:
> ```
> SWR_REGISTRY=swr.cn-north-4.myhuaweicloud.com
> SWR_ORG=<你的组织名>
> TAG=latest    # 或 specific sha
> MYSQL_ROOT_PASSWORD=...
> REDIS_PASSWORD=...
> ```

### 10.6 待用户补充(还没定)

- [ ] **Flexus region**(决定 `SWR_REGISTRY` 前缀;常见 `cn-north-4` / `cn-east-3` / `cn-south-1`)
- [ ] **SWR 组织名**(`${{ vars.SWR_ORG }}`)
- [ ] **服务器上是否已 `docker login swr...`**(首次需要,我可以在 deploy 时一并做;或先在主机手动 docker login 一次)
- [x] **3 个镜像 vs 1 个大镜像** → **3 个已选定**(§11.3 落实),理由见 §10.2
- [x] **旧 workflow yml 是否删除** → **本次不动**,归档留底;以后 actions 上线时另开新 yml(见 §11.4)
- [ ] **SWR 临时凭证生成策略**:用 `obs ObsClient` 在 GitHub Actions 里现生成,还是手动提前生成 12 小时过期的密码贴到 Secrets?后者过期需手动续 → **本次走手动方案**(12h 凭证 export 到环境变量);actions 阶段再讨论

---

## 11. 决策记录 2026-10-14(选 B:前后端都做镜像 + nginx 反代;先手动 4 步,Actions 延后)

**用户决定(2026-10-14 AskUserQuestion):** 选 **B. 前后端都做镜像 + nginx 反代**。
**理由:** 原 Pity "前端 dist 塞 backend/statics" 在 monorepo + docker 化里已经不合理;前端拆独立镜像、nginx 反代统一入口,改动隔离干净,HTTPS 一行加。

### 11.1 本次新增文件清单

| 文件 | 用途 |
|---|---|
| `nginx/Dockerfile` | 反代镜像(`nginx:1.27-alpine`,COPY `nginx.conf`) |
| `nginx/nginx.conf` | `/api/*` → `backend:7777`,其余 → `frontend:80` |
| `frontend/Dockerfile.production` | 多阶段:`node:20-alpine` 跑 `max build` → `nginx:1.27-alpine` serve `dist/` |
| `frontend/.dockerignore` | 排除 `node_modules` / `dist` / `.umi` / `tests` / `mock` / `.git` 等 |
| `backend/ops/docker-compose.deploy.yaml` | 5 服务 pull-based compose,镜像从 SWR 拉,数据卷按 §2.6 单盘约定 |
| `scripts/build-images.sh` | Step 1:本地构建 3 个自建镜像 |
| `scripts/push-to-swr.sh` | Step 2:3 镜像 `tag + docker login + push` 到 SWR |

> 现有 `frontend/Dockerfile`(`node:18 + npm start`,dev 用)**保留不动**;新加 `Dockerfile.production` 对应 prod。
> 现有 `backend/ops/docker-compose.yaml`(dev,3 服务 + 老 `pity_net`)也保留不动;dev 与 deploy 并存可用。

### 11.2 手动 4 步流程(取代 GitHub Actions 自动路径)

| 步骤 | 操作 | 工具 |
|---|---|---|
| Step 1 | 本地构建 3 个自建镜像 | `./scripts/build-images.sh <tag>`(默认 tag = dev) |
| Step 2 | 推到华为云 SWR | `./scripts/push-to-swr.sh <tag>`,环境变量提供 `SWR_REGISTRY` / `SWR_ORG` / `SWR_USER` / `SWR_PASS`(12h 凭证) |
| Step 3 | 服务器 pull + up | scp 上 `docker-compose.deploy.yaml` + `.env`;服务器:`docker compose pull && docker compose up -d` |
| Step 4 | GitHub Actions 自动 push/deploy | ⏸ **延后**,见 §11.4 |

> `mysql:8.0` / `redis:7-alpine` 是 docker.io 公开镜像,**不需要本地 build 也不需要手动 push**,server 上 `docker compose pull` 时自动从 docker.io 拉(国内可能需换镜像源,见 §5 已列风险)。

### 11.3 关键设计决定

| 项 | 决定 | 备注 |
|---|---|---|
| 镜像数 | 3(`pity-backend` / `pity-frontend` / `pity-nginx`) | 沿用 §10.2,改动隔离 |
| 数据卷布局 | bind mount 到 `/home/tester/pity-data/...` | 沿用 §2.6 单盘 40G 约定 |
| backend 环境文件 | 复用 `dev.env.ops`(host bind mount),设 `pity_env=dev` | 等 `backend/conf/pro.env` 真正落地后再切 pro;`MYSQL_HOST=mysql` / `REDIS_HOST=redis` 在 compose 中显式覆盖 |
| MySQL 凭证 | `.env` 提供 `MYSQL_ROOT_PASSWORD`,compose 用 `${MYSQL_ROOT_PASSWORD}` 同步到容器内 `MYSQL_PWD` | `${VAR:?required}` 强制要求,缺变量直接报错 |
| 容器名后缀 | `_deploy`(`pity_mysql_deploy` 等) | 跟 dev compose 的同名容器(`pity_mysql`)区分,两套可并存 |
| 前端 npm 镜像 | `--registry=https://registry.npmmirror.com` | 2M 带宽下拉得动 |
| redis 启动参数 | `--appendonly yes --appendfsync everysec --save "" --auto-aof-rewrite-min-size 64mb --auto-aof-rewrite-percentage 100` | §2.6 单盘容量约定派生,AOF 限大小 |
| mysql 启动参数 | `--expire_logs_days=3 --max_binlog_size=104857600 --innodb_file_per_table=1` | 同上,binlog 限大小 |
| 网络 | 单 bridge `appnet` | 5 容器全在同一网络,通过服务名互访 |
| 资源限制(每容器 `deploy.resources.limits.memory`) | backend 600M / mysql 700M / redis 80M / frontend 30M / nginx 30M | 合计 ~1.44G,2G 主机余量 ~500M 给 OS + buffer |

### 11.4 归档:§10.4 GitHub Actions 草稿(本次未启用)

保留 §10.4 的 Actions yml 草稿作为历史参考,**不实际启用**:
- 理由:用户体感"乱",先把手动 4 步跑顺再讨论自动化
- 启用 Actions 时建议**另起文件**(如 `.github/workflows/deploy-docker.yml`)而不是覆盖 §10.4 那份草稿,以便后续对比演进
- 当前 `.github/workflows/deploy-{backend,frontend}.yml` 文件**未改动**,继续以原 SCP + gunicorn + PM2 触发(但当前 deploy 已切到 docker,老 workflow 实际是 no-op)

### 11.5 §10.6 部分回答对账

按本次 commit 落地的口径,§10.6 中:

- ✅ **3 个镜像 vs 1 个** — 3 个,见 §11.3
- ✅ **旧 workflow yml** — 保留不动,见 §11.4
- ✅ **SWR 凭证策略** — 本次走手动 12h 凭证(`SWR_USER` / `SWR_PASS` export 到环境变量,actions 阶段再切换 ObsClient 自动生成)
- ❓ **Flexus region / SWR org** — 待用户填 `SWR_REGISTRY` / `SWR_ORG` 后才能跑 Step 2 / Step 3
- ❓ **服务器首次 docker login** — 待确认服务器上是否已 `docker login swr...`,首次需手动 login 一次


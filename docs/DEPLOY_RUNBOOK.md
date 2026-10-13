# 部署实施手册(SWR + GitHub Actions 路线)

> 这是一份**用户主导**的实施手册。文档不替你执行任何文件改动 — 每一步都标了"做什么 / 为什么 / 怎么做 / 风险 / 验证 / 决策点",你在每一节都要做自己的判断,然后再手动落地。
>
> 上一份 `DEPLOY_DOCKER_MIGRATION.md` 是"为什么这样做 + 备选方案对比"——这一份是"具体怎么做"。两份配合用。

---

## 0. 总览

### 0.1 一句话目标

把当前仓库(后端 pity + 前端 pityWeb 合并)在华为云单台 2 核 2G Flexus 上,改成**前后端 3 个独立镜像 + GitHub Actions 推 SWR + 服务器 `pull && up`** 的标准 Docker 部署。

### 0.2 起点 / 终点

| | 起点 | 终点 |
|---|---|---|
| 部署链路 | `scp + pip --user + gunicorn + pm2` | `docker push to SWR + ssh pull && up` |
| 前端运行方式 | 主机 PM2 起 `web.sh`(Node 进程) | nginx 容器,纯静态出 |
| 前端产物归属 | 复制到 `backend/statics/`(反模式) | 前端独立 nginx 容器 |
| 后端 worker 数 | 8 | 2(2G 内存上限) |
| 数据库 | docker-compose dev 用 | docker-compose deploy 用,数据卷 `/data/mysql` |
| 入口 | 散落端口:7777 + 8000 + 3306 + 6379 | 单一 `nginx:80` 暴露 |

### 0.3 涉及的文件(先看,后改)

**改**(原文件存在,改造):

```
backend/ops/dockerfile                       ← gunicorn -w 8 → -w 2
backend/ops/supervisor.conf                  ← 跟随 dockerfile
backend/ops/pro.env.ops                      ← 新增(从 backend/conf/pro.env 复制)
backend/ops/.env.example                     ← 新增(.env 模板,不入库)
.github/workflows/deploy-backend.yml         ← 完全重写(SWR 推送)
.github/workflows/deploy-frontend.yml        ← 完全重写(SWR 推送)
frontend/Dockerfile                          ← 完全重写(npm → nginx 静态)
frontend/.dockerignore                       ← 新增(排除 node_modules / dist)
```

**新增**:

```
nginx/Dockerfile                             ← nginx:1.27-alpine + COPY nginx.conf
nginx/nginx.conf                             ← /api/* 反代 backend:7777
backend/ops/docker-compose.deploy.yaml       ← 5 服务 image-based
```

**删**(建议;不是必须,看你的决定):

```
frontend/deploy.sh                           ← 老 Pity"塞 statics"脚本,路线换后失效
backend/gunicorn.py                          ← 主机跑生产用,Docker 化后是死代码
backend/supervisor.conf                      ← 同上,顶层那份
```

**保留原样**:

```
backend/ops/docker-compose.yaml              ← dev 用,保留
backend/ops/dev.env.ops                      ← dev 用,保留
backend/gunicorn.py + backend/supervisor.conf (如果想保留作"应急手动跑",可保留)
```

### 0.4 不要踩的坑

- **不要**保留老 `frontend/Dockerfile`(那份是开发模式启动)。要么重写,要么删了另起。
- **不要**用 `gunicorn -w 8`(2G 内存下会挤爆其他服务)。
- **不要**把 MySQL 密码 `Pitytester666666` 留在 yml 里(`docker-compose.deploy.yaml` 用 `.env` 注入)。
- **不要**用服务器上 `--build`,要走 `pull`(从 SWR 拉)。
- **不要**让 MySQL 3306 / Redis 6379 暴露到主机端口,只用 nginx 80 出。

---

## 1. 步骤 1:确认参数(决策点)

### 1.1 必填参数

| 项 | 取值 | 怎么拿 |
|---|---|---|
| `SWR_REGION` | `<region>` | 华为云控制台 → Flexus 实例详情页 |
| `SWR_ORG` | `<organization>` | SWR 控制台 → 命名空间(创建/已存在的) |
| `SWR_REGISTRY` | `swr.<region>.myhuaweicloud.com` | 拼接上面两个 |

> 三种常见 region:`cn-north-4`(北京四)/`cn-east-3`(上海二)/`cn-south-1`(广州)。**SWR 区域必须跟 Flexus 一致**,否则内网拉镜像走公网。

### 1.2 决策点

- **Flexus region?** 决定 `SWR_REGISTRY` 前缀
- **SWR 组织名?** 你在华为云 SWR 已经创建的那个
- **3 个独立镜像 vs 1 个大镜像?** 文档推荐 3 个,理由:改动频率不均
- **HTTPS?** 阶段 1 先 HTTP,后续用 Caddy 顶证书
- **数据库密码处理方式?** `.env` 不入库(推荐)或 demo 期间临时硬编码
- **老文件处置?** 是彻底删除还是保留作 fallback

---

## 2. 步骤 2:在 SWR 控制台建仓(为什么要做 / 怎么做)

### 2.1 做什么

在华为云 SWR 创建 3 个空仓库:

```
pity-backend
pity-frontend
pity-nginx
```

> 与 GitHub repo 不同,这里只是"容器镜像"的占位,不存代码,可以全选"公开"或者私有,看你偏好。

### 2.2 为什么

GH Actions 推镜像前,目标仓库必须已经存在(SWR 跟阿里云 ACR 类似,不支持隐式创建)。

### 2.3 怎么做

1. 登录华为云控制台 → 搜索"SWR"
2. 选你的组织(同一个 region,要跟 Flexus 同 region)
3. 创建镜像仓库(类型选"私有"或"公开"看你)→ 名字 `pity-backend`(再创建 `pity-frontend` / `pity-nginx`)

### 2.4 验证

控制台列表里看到 3 个新仓库,镜像版本列表是空的。

---

## 3. 步骤 3:GitHub 配置 Secrets + Vars

### 3.1 做什么

仓库 Settings → Secrets and variables → Actions:

**Repository Secrets**(机密):

| Name | 用途 |
|---|---|
| `HOST` | 主机公网 IP / 域名 |
| `USERNAME` | SSH 用户(例如 `tester`) |
| `PASSWORD` | SSH 密码(**强烈推荐**改用 `SSH_KEY`) |
| `SWR_USER` | SWR 临时登录凭证用户名(格式 `cn-north-4@<你的账户名>`)|
| `SWR_PASS` | SWR 临时登录凭证密码(12h 过期 — 见风险)|

**Repository Variables**(非机密):

| Name | 示例 |
|---|---|
| `SWR_REGISTRY` | `swr.cn-north-4.myhuaweicloud.com` |
| `SWR_ORG` | `<你的命名空间>` |

### 3.2 为什么

SWR 的登录凭证是"临时"的(每次操作生成,12h 过期)。你可以:

- **方案 A**(手动):提前在 SWR 控制台生成 12h 临时凭证,贴到 Secrets。每 12h 你手动续一次。
- **方案 B**(现拉,在 Actions 里):用 `huaweicloud/swr-credential-action` 类 action 在 job 里调用华为云 API 现拉凭证。
- 个人 demo 阶段,A 方案够用;B 留给以后自动化做透。

### 3.3 风险

- **12h 过期 → action 失败**:用方案 B 或写定时任务更新 secret
- **SSH 密码登录**:密码进 secret 安全性差,**强烈推荐**改 SSH 密钥(`SSH_KEY` secret 写私钥,服务器 `~/.ssh/authorized_keys` 写公钥)

### 3.4 验证

到 Settings → Secrets 页能看到这些条目。Vars 同理。

---

## 4. 步骤 4:改 backend dockerfile(降 worker)

### 4.1 做什么

`backend/ops/supervisor.conf` 里把 `-w 8` 改成 `-w 2`:

```diff
-command=/pity/venv/bin/gunicorn main:pity -b 0.0.0.0:7777 -w 8 -k uvicorn.workers.UvicornWorker --log-level info --access-logfile '-' --error-logfile '-'
+command=/pity/venv/bin/gunicorn main:pity -b 0.0.0.0:7777 -w 2 -k uvicorn.workers.UvicornWorker --log-level info --access-logfile '-' --error-logfile '-'
```

### 4.2 为什么

2G 内存里给后端容器 ~600MB 上限,worker 多了会触发 OOM。后续观察再调。

### 4.3 风险

- 并发能力下降(8 → 2 worker,理论上并发能力减 ~75%)。demo 上 OK
- 应用启动时短暂会"冷启",但 gunicorn worker 模型 warm-up 比较快

### 4.4 验证

下一步本地 `docker build` 跑通,容器起来 `curl http://localhost:7777/` 看响应。

---

## 5. 步骤 5:改写 `frontend/Dockerfile`(dev → nginx 静态)

### 5.1 做什么

`frontend/Dockerfile` 整段重写:

```dockerfile
# syntax=docker/dockerfile:1.7

# ---- Stage 1: build dist ----
FROM node:20-alpine AS builder
WORKDIR /work
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

# ---- Stage 2: serve dist ----
FROM nginx:1.27-alpine
COPY --from=builder /work/dist /usr/share/nginx/html/
COPY nginx-server.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

(同时新建 `frontend/nginx-server.conf`,内容很简单:)

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### 5.2 为什么

老 Dockerfile 是 `node:18 + npm start`,容器启动的是开发 server,跟生产 nginx 静态出两码事。新版用**多阶段**:第一阶段 build 产物,第二阶段 nginx 出。镜像体积能从 ~1GB(node_modules) 缩到 ~40MB(nginx)。

### 5.3 风险

- 老 `Dockerfile` 老用户可能引用过;改名/重写都会让他们的本地 `docker build` 失败。如果有团队内 CI/开发依赖老 Dockerfile,要**先通知再改**
- `try_files $uri /index.html` 是 UmiJS SPA 路由必要的;漏掉前端路由会 404

### 5.4 决策点

- 是**重写** `frontend/Dockerfile` 还是**新建 `frontend/Dockerfile.pro`** 然后改 yml 指向?推荐重写(简单)
- 你的 `frontend/` 里有没有 `nginx-server.conf`?没有就新建

---

## 6. 步骤 6:创建 `nginx/(Dockerfile + nginx.conf)`

### 6.1 做什么

新建 `nginx/Dockerfile`:

```dockerfile
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

新建 `nginx/nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;

    # 反代后端
    location /api/ {
        proxy_pass http://backend:7777/;     # 注意末尾的 /,会 strip /api 前缀
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    # 反代前端(简单起见,也走容器内网;想省也可以直接 root 静态)
    location / {
        proxy_pass http://frontend:80;
    }
}
```

### 6.2 为什么

单一入口:外部访问只看到 nginx 一个端口(:80),内部按路径分发。这才能用 HTTPS / 缓存 / 限流统一做。

### 6.3 风险

- 你的 FastAPI 路由到底是 `/xxx` 还是 `/api/xxx`?看 `backend/main.py` 注册路由时的 prefix。**这一步要核对**
  - 如果是 `/xxx`,nginx 改成 `location / { proxy_pass http://backend:7777; }` 不要 `/api/`
- SPA 路由:前端 `location /` 走 `try_files` 由前端容器自己处理,**不要**在 nginx 里硬 strip 路径

### 6.4 决策点

- **`/api/*` 还是直接根路径?** 由后端路由 prefix 决定。当前 backend 是 `app.include_router(...)` 不带 `/api` 前缀 → 我推荐 nginx 用 `location /`(直接反代到 backend)。**这一步请你确认**
- 单纯静态出 vs 反代前端?后者更灵活(后续加缓存头),更稳

---

## 7. 步骤 7:创建 `backend/ops/docker-compose.deploy.yaml`

### 7.1 做什么

新建 `backend/ops/docker-compose.deploy.yaml`:

```yaml
version: "3.8"
services:
  mysql:
    image: mysql:8.0
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: pity
    volumes:
      - /data/mysql:/var/lib/mysql
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 700M }

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}"]
    volumes:
      - /data/redis:/data
    networks: [appnet]
    deploy:
      resources:
        limits: { memory: 80M }

  backend:
    image: ${SWR_REGISTRY}/${SWR_ORG}/pity-backend:${TAG:-latest}
    restart: unless-stopped
    env_file: pro.env.ops
    depends_on: [mysql, redis]
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

networks:
  appnet:
    driver: bridge
```

### 7.2 为什么

服务器上不 build,纯 pull。所有 5 个服务在一个 compose 文件,改成某一项 image 也只改一处。

### 7.3 风险

- `env_file: pro.env.ops` 是给 pity 容器的环境文件,跟 `MYSQL_ROOT_PASSWORD`/`REDIS_PASSWORD` 的 `.env` 是**两份**别混
- `depends_on` 只是启动顺序,不真等依赖服务就绪。MySQL 起来要 ~30s,后端 cold start 可能连不上 → 让 backend 有 retry 自动重连机制(看后端代码是否实现了)
- `volumes: /data/mysql` 假设主机上 `/data/mysql` 存在且 uid:gid 对得上 mysql 容器(默认 999:999)

---

## 8. 步骤 8:重写两个 GitHub Actions yml

### 8.1 做什么

完整替换 `.github/workflows/deploy-backend.yml` 和 `deploy-frontend.yml`。内容骨架见 `DEPLOY_DOCKER_MIGRATION.md` 第 10.4 节。

基础模板(以 backend 为例):

```yaml
name: Build & Push pity-backend

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

      - name: Login SWR
        uses: docker/login-action@v3
        with:
          registry: ${{ vars.SWR_REGISTRY }}
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

      - name: Remote pull & up
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.HOST }}
          username: ${{ secrets.USERNAME }}
          password: ${{ secrets.PASSWORD }}
          script: |
            cd /home/tester/pity-deploy
            docker login -u "$SWR_USER" -p "$SWR_PASS" $SWR_REGISTRY
            export TAG=${{ github.sha }}
            docker compose -f backend/ops/docker-compose.deploy.yaml pull backend nginx
            docker compose -f backend/ops/docker-compose.deploy.yaml up -d backend nginx
```

### 8.2 为什么

- 任何 push 到 main 触发 build → push SWR → ssh 远端 pull & up
- `latest` tag 让你"不指 sha 也能跑",`${{ github.sha }}` 用于 rollback

### 8.3 风险

- 旧 yml 里 pkill gunicorn / pm2 restart 会跟新链路**冲突**(重复触发)。一旦切,旧 yml **必须**删或者 disable
- secrets.SWR_PASS 12h 过期 → actions 任务失败;用方案 B 自动化续签可破

---

## 9. 步骤 9:处理历史文件

### 9.1 决策表(每行,你来选)

| 文件 | 选项 A(保留兼容) | 选项 B(彻底删)|
|---|---|---|
| `frontend/deploy.sh` | 改名 `frontend/deploy.sh.deprecated` 留作"应急" | 直接删 |
| `backend/gunicorn.py` | 保留,不动 | 删 |
| `backend/supervisor.conf`(顶层)| 保留,不动 | 删 |
| `backend/ops/supervisor.conf` | 跟着 dockerfile 改 -w(在步骤 4) | — |
| 老 `frontend/Dockerfile`(原始版本) | 见 9.2 | 见 9.2 |

### 9.2 老 `frontend/Dockerfile` 的处置

你在步骤 5 是要"重写"它。**重写前**先决定:

- **直接重写 + commit 一次**:历史里"原 Dockerfile 的内容"被覆盖
- **改名保留**:变成 `frontend/Dockerfile.dev`(给本地 dev `docker run -p 8000:8000 pityweb:dev` 用),新建 `frontend/Dockerfile`(生产用)

我推荐后者:`Dockerfile.dev` 留作"开发容器",新版 `Dockerfile` 专做生产 nginx 镜像。语义更清晰。

### 9.3 验证

`git log -- frontend/Dockerfile` 看历史;或者看 git blame 后续找旧内容。

---

## 10. 步骤 10:创建 `.env` / `pro.env.ops`

### 10.1 必填(主机 `/home/tester/pity-deploy/.env`,**不入库**):

```bash
SWR_REGISTRY=swr.cn-north-4.myhuaweicloud.com
SWR_ORG=<你的命名空间>
TAG=latest
MYSQL_ROOT_PASSWORD=<强密码>
REDIS_PASSWORD=<强密码>
```

### 10.2 提供模板(可入库):

`backend/ops/.env.example`:

```bash
SWR_REGISTRY=swr.<region>.myhuaweicloud.com
SWR_ORG=<organization>
TAG=latest
MYSQL_ROOT_PASSWORD=change-me
REDIS_PASSWORD=change-me
```

### 10.3 必填(容器内,容器读取):

`backend/ops/pro.env.ops`(可入库,从 `backend/conf/pro.env` 复制并修改 MYSQL/Redis 连接信息):

```bash
pity_env=pro

# MySQL — 用容器名(在 appnet 网络里)
MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=${MYSQL_ROOT_PASSWORD}
MYSQL_DB=pity

# Redis — 容器名
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_DB=0

# 其他后端原配置保留:...
```

> 注意:`MYSQL_PASSWORD` 在容器内部等于 `.env` 里的 `MYSQL_ROOT_PASSWORD`,这是为了简化。建议单独建一个 `pity` 用户(权限收敛到 `pity` 库)。

---

## 11. 步骤 11:本地首次构建并推送

### 11.1 做什么

不在服务器上 build,全部在 CI 里 build。但**首次**必须有人在本地先试一下,确保基础镜像能拉到、dockerfile 语法没问题。

### 11.2 怎么做

```bash
# 后端
cd backend
docker build -f ops/dockerfile -t pity-backend:dev .
docker run --rm -p 7777:7777 --env-file ops/dev.env.ops pity-backend:dev

# 前端(新 Dockerfile)
cd ../frontend
docker build -t pity-frontend:dev .
docker run --rm -p 8080:80 pity-frontend:dev

# nginx
cd ../nginx
docker build -t pity-nginx:dev .
docker run --rm -p 8081:80 \
  --add-host backend:host-gateway \
  --add-host frontend:host-gateway \
  pity-nginx:dev
```

都起来后,浏览器访问:
- `http://localhost:7777` 后端
- `http://localhost:8080` 前端(单独测)
- `http://localhost:8081`(nginx 单独测,需要 backend/frontend 容器也起着 → 用 docker compose)

### 11.3 验证

- backend `curl http://localhost:7777/` 返回(或者 401 都行,反正能 ping 通)
- frontend `http://localhost:8080` 看到页面
- nginx 访问 `http://localhost:8081/api/...` 反代成功

---

## 12. 步骤 12:服务器首次部署

### 12.1 做什么

主机上 `/home/tester/pity-deploy/` 目录需有:

```
pity-deploy/
├── backend/
│   ├── ops/
│   │   ├── docker-compose.deploy.yaml
│   │   └── pro.env.ops
├── frontend/
├── nginx/
└── .env                       ← 不入库,主机单独放
```

### 12.2 怎么做

```bash
# 服务器上首次(只跑一次)
mkdir -p /home/tester/pity-deploy
cd /home/tester/pity-deploy

# 用 git 直接拉(因为代码都在 git 里)
git clone <你的仓库> .

# 把 docker-compose.deploy.yaml 和 pro.env.ops 等文件软链/复制到位
# (因为 ops/ 在 backend/ops/ 下,但 git clone 已经包含)

# 主机上创建 .env(单独 secret,不入库)
cat > /home/tester/pity-deploy/.env <<'EOF'
SWR_REGISTRY=swr.cn-north-4.myhuaweicloud.com
SWR_ORG=...
TAG=latest
MYSQL_ROOT_PASSWORD=...
REDIS_PASSWORD=...
EOF
chmod 600 /home/tester/pity-deploy/.env

# 主机上首次 docker login SWR
docker login -u $SWR_USER -p $SWR_PASS swr.cn-north-4.myhuaweicloud.com

# 主机上首次 up
cd /home/tester/pity-deploy/backend/ops
docker compose -f docker-compose.deploy.yaml --env-file ../../.env pull
docker compose -f docker-compose.deploy.yaml --env-file ../../.env up -d
```

### 12.3 验证

`docker ps` 看 5 个容器都 running + healthy;`curl http://HOST_IP/` 看页面。

---

## 13. 步骤 13:首次 push 触发 Actions

### 13.1 做什么

```bash
# 仓库根,改任意 backend/** 内容
git add -p
git commit -m "chore: 触发 SWR 后端镜像首次构建"
git push origin main
```

看 GitHub Actions tab:deploy-backend.yml 跑起,最终日志显示:
- `build & push` 成功
- `Remote pull & up` 远端 ssh 成功

### 13.2 验证

到 SWR 控制台:三个镜像仓库的"版本"列表里有新 tag。

服务器上 `docker ps` 看 `pity-backend` 容器在 running,tag 是刚 push 的 sha(或者 latest)。

---

## 14. 验收清单(逐条勾)

部署完成后:

- [ ] `http://<HOST_IP>/` 打开前端页面
- [ ] `http://<HOST_IP>/api/...` 任意一个接口返回 `{"code":0,...}` 风格的数据
- [ ] `docker stats` 各容器内存 ≤ deploy.resources.limits.memory
- [ ] 主机重启服务器后,5 容器自动回到 running(通过 `restart: unless-stopped`)
- [ ] MySQL 数据写入后,服务器重启数据仍在(`/data/mysql/volume`)
- [ ] Redis 数据写入后,服务器重启数据仍在
- [ ] `docker compose -f ... down && up -d` 重启后,5 服务都正常
- [ ] 任何时候 `git push` 到 main,GitHub Actions 触发 SWR push + 远端 pull & up

---

## 15. 回滚方案

### 15.1 完整回滚(放弃新部署)

1. 服务器停新部署:`cd /home/tester/pity-deploy && docker compose -f backend/ops/docker-compose.deploy.yaml down`
2. 启动老部署:按 `deploy-backend.yml` / `deploy-frontend.yml` 老版本走 scp + pm2 链路(暂时把 secrets 配回老 yml 用的)

### 15.2 部分回滚(只换 image tag)

服务器:

```bash
TAG=<上一个能跑的 sha> docker compose -f backend/ops/docker-compose.deploy.yaml --env-file ../../.env up -d backend
```

(其他服务 tag 保持 latest 不变。)

### 15.3 紧急止血

镜像 OOM → `docker compose down <服务名>` 然后在 compose 里改 `deploy.resources.limits.memory`,再 `up -d`。

---

## 16. 后续可选优化(部署稳定后再考虑)

- [ ] HTTPS:加 Caddy 容器自动证书,或者用 nginx + acme.sh
- [ ] SWR 临时凭证自动化:`huaweicloud/swr-credential-action` 类 action 每次现拉
- [ ] SSH Key 替换密码登录
- [ ] 加 `healthcheck` 让 `docker compose ps` 真实反映状态
- [ ] 日志收集:`logs/` 挂出来,或者起 Loki / Promtail
- [ ] 监控告警:用云监控 + 自定义指标(请求量、错误率)
- [ ] 数据备份:MySQL 周期 dump 到 `/data/backup/` + 远程同步
- [ ] 蓝绿部署:用 nginx upstream 切流量
- [ ] **删除** `frontend/Dockerfile.dev`(停止用开发容器时)
- [ ] **删除** 顶层 `backend/gunicorn.py` + `backend/supervisor.conf`

---

## 17. 检查清单自检表

实施前,心中默念这 12 条:

1. 我的 `SWR_REGISTRY` 跟 Flexus region 一致
2. SWR 控制台 3 个空仓库已建
3. GitHub Secrets:HOST / USERNAME / PASSWORD / SWR_USER / SWR_PASS 都填了
4. GitHub Vars:SWR_REGISTRY / SWR_ORG 都填了
5. backend dockerfile -w 2 已改
6. frontend/Dockerfile 已重写为多阶段 nginx 版
7. nginx/Dockerfile + nginx.conf 已新建
8. backend/ops/docker-compose.deploy.yaml 已新建
9. .github/workflows/{deploy-backend,deploy-frontend}.yml 已重写
10. 老 `frontend/deploy.sh` / `backend/gunicorn.py` / `backend/supervisor.conf` 我已决定保留/删除
11. 主机 /home/tester/pity-deploy/.env 已创建且 chmod 600
12. 我本地 build 跑过一次,5 容器能起来

满足后,首次 `git push`,触发 Actions,验收清单逐条勾。

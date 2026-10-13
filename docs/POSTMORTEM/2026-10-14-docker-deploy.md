# 2026-10-14 Pity Docker 化部署复盘

> 个人复盘(不局限 Pity 项目),给未来的自己看:
> - AI 把流程跑完了,但**我没真正掌握**怎么独立搭这套 — 这是真话
> - 沉淀部分:**踩坑→修法**对,以及"复盘下一次该先 grep 什么"的决策树
> - 镜像化、不复制粘贴的洞察 — 留作下一步动手的脚手架

## 上下文

个人 demo,目标机:华南广州华为云 Flexus `ahf.large.1.40g.2m`(**2 核 / 2G / 40G 系统盘**,**没有独立数据盘**)。

从 0 跑通 docker compose 5 服务 + 自建 image 推 SWR + server pull+up。约 5 小时。中间踩 7 个坑,产 8 个 commit。同一天 `docs/DEPLOY_DOCKER_MIGRATION.md` 也覆盖更新。

---

## 关键决策(每条对比 2-3 选项)

### 1. 前后端容器化:都做 image + nginx 反代,还是延续"前端 dist 塞 backend/statics"?

- A. 老 Pity 做法:`npm run build` → `cp dist backend/statics/`,后端单容器 serve API + static
- B. **都做 image + nginx 反代**(选了)

**理由:**
- monorepo 都已经把 frontend + backend 合并,既然在一起,docker 化时拆开最合理
- 前端 CSS 改动**不该触发后端 image rebuild**
- nginx 单独反代,后续上 HTTPS / 静态资源缓存 / CORS 都是改一层 nginx 的事
- 老做法在 host 部署上勉强能跑,在 docker compose 上几乎做不到(后端 image 要 COPY 前端 dist)

**教训:** 拆还是不拆,问自己"两者改动频率" — 不同频就拆。

---

### 2. 镜像推送工具:docker push 还是 skopeo?

- A. docker push(标准做法,人尽皆知)
- B. **skopeo copy**(选了)

**理由(踩坑后才悟到):**
- SWR + docker CLI 的协议层有 bug:`error from registry: Invalid image, fail to parse 'manifest.json'`,所有 layer 都 `Layer already exists`,只有最后 PUT manifest 失败
- 换 tag、删 SWR 仓库重推 **都无用**(污染在 registry 内部状态,不是 image)
- skopeo 直发 OCI distribution-spec HTTP,对国产 registry(SWR / ACR / TCR)100% 兼容

**教训:** 国产 registry 推不上去时,**第一件事试 skopeo**,比折腾 docker push 各种 hack 快得多。

---

### 3. nginx 反代路由:单一 /api/ 还是正则覆盖 11 个前缀?

- A. `location /api/`(默认思路,但**错了**)
- B. 11 个 location 块(穷举)
- C. **正则 `location ~ ^/(api|auth|...)/`一次覆盖**(选了)

**理由(踩坑后才悟到):**
- `frontend/config/proxy.ts` 列了 11 个 dev proxy 前缀(`/api/`, `/auth/`, `/testcase/`, `/config/`, `/project/`, `/operation/`, `/workspace/`, `/oss/`, `/notification/`, `/online/`, `/request/`),开发环境 dev proxy 都接
- nginx 只接 `/api/` → 其他 10 个落到 `location /` → 转给前端 nginx → 404
- 用正则一次覆盖,11 个 location 块也行但冗长
- **`proxy_pass http://backend:7777;`(无末尾 `/`) = 保留完整 URI**,后端 router `APIRouter(prefix="/auth")` 才能命中
- `proxy_pass http://backend:7777/`(末尾带 `/`)= **strip prefix**,这是常见坑

**教训:** 做反代**第一件事**:先 `grep frontend/config/proxy.ts`(或对应 proxy 配置)看 dev 列了哪些路径,**不要靠猜**。

---

### 4. 环境变量传递:bind mount vs env_file?

- A. `volumes: - ./dev.env.ops:/pity/conf/dev.env`(bind mount 文件)
- B. **`env_file: - ./dev.env.ops`**(compose 读文件 → 注入 ENV 变量)(选了)

**理由(踩坑后才悟到):**
- A 方案在 server 端文件不存在时,**docker engine 自动建空目录**当作 bind source,后续 mount 时 `MS_REC`(目录专用)挂到文件位置失败
- B 方案文件不存在时 `docker compose` 直接报错退出,行为可预期
- pydantic BaseSettings 读 ENV vars 优先级高于 .env 文件,`env_file:` 注入 ENV 后 pydantic 同样能用

**规则:** **容器配置文件默认用 `env_file`**,除非要热替换文件(比如 watchtower)。

---

### 5. Dockerfile 平台镜像:python:3.9 vs 3.10 vs 3.13?

- 选了 **python:3.10-slim**

**理由:**
- 本地 conda 是 3.10.18,要**对齐**(避免本地用 PEP 604 / PEP 634 语法,容器 3.9 解释器 `SyntaxError`)
- 3.13 太新,生态有些包可能还没 wheels
- 3.9 已老(EOL 边缘),用 LTS(3.10 / 3.11)更稳

**规则:** **跟本地开发版本对齐是默认**,除非有特定 feature 需求。Node 同理(本次顺手把 dev Dockerfile 18.18.2 → 20-alpine)。

---

## 7 个踩过的坑(现象 / 根因 / 修法)

### 坑 1 — `pip install wait-for-it.sh` GnuTLS fail

- **现象:** `wget https://github.com/vishnubob/wait-for-it/...` 报 `GnuTLS: non-properly terminated`,build hang
- **根因:** 镜像 wget 证书不全 + 这个脚本**全仓没人引用** — supervisor.conf 只启 gunicorn,不调 wait-for-it(上游 Pity 历史残留)
- **修法:** 删死代码(apt install wget 整段 + COPY 等)
- **浪费:** ~30 分钟(没先 grep)

---

### 坑 2 — `npm ci` ERESOLVE peer dep 冲突

- **现象:** `npm error code ERESOLVE`,`peer antd@"^4.6.3" from @ant-design/charts@1.4.3` 项目实际 antd@5.29.3
- **根因:** UmiJS v4 + Ant Design v5 + @ant-design/charts@1.x 不兼容(charts 1.x 只支持 antd 4.x);npm 7+ 严格 peer dep 检查
- **修法:** 加 `--legacy-peer-deps`(切回 npm 6 宽松解析)
- **警告:** 这是 npm 不再严格检查绕过,运行时 @ant-design/charts 用 antd 5 实际 API **可能**炸 — 没炸是因为浏览器还没用到 charts
- **更稳修法:** 升 `@ant-design/charts` 到 v2.x(真正支持 antd 5),TODO

---

### 坑 3 — docker CLI 推 SWR "Invalid image, fail to parse manifest.json"

- **现象:** 所有 layer 都 `Layer already exists`,最后 manifest 写失败;换 tag 重推 + 删 SWR 仓库都无用
- **根因:** docker CLI 的 manifest v2.2 跟 SWR 解析器协议层有 bug(国产 registry 通病)
- **修法:** `skopeo copy --dest-creds ... docker-archive:<tar> docker://<dest>`,直发 OCI HTTP
- **规则:** **国产 registry 推不上去第一件事试 skopeo**

---

### 坑 4 — docker compose plugin 在 Ubuntu 22.04 docker.io backport 没装

- **现象:** `docker compose version` 报 `unknown command: docker compose`
- **根因:** 华为云 Ubuntu 22.04 默认 `docker.io` 包(`29.1.3-0ubuntu3~22.04.2`)不带 compose plugin(Docker 官方仓库才打包这个)
- **修法:** GitHub release 直接下二进制到 `/usr/local/bin/docker-compose`
- **规则:** **装 OS 第一件事** `docker compose version`,不通过就 binary,而不是换 source.list

---

### 坑 5 — DaoCloud mirror 拉 buildkit 失败(被绕开)

- **现象:** `docker buildx` 报 `dial docker.m.daocloud.io: no such host`
- **根因:** buildx 用 docker-container driver,启动时拉 buildkit image,DaoCloud mirror 在我们网络 DNS 不通
- **绕开:** 我们 Mac 是 Intel x86_64,`docker build` 默认就是 amd64,**完全不需要 buildx**,普通 `docker build` 就行
- **将来:** 切到 M 系列 Mac 的话,要在 `daemon.json` 配 `registry-mirrors: ["https://hub-mirror.c.163.com"]` 之类

---

### 坑 6 — server 上 dev.env.ops 缺 → bind mount 失败

- **现象:** `mount src=.../dev.env.ops, dst=/pity/conf/dev.env, ... not a directory`
- **根因:** bind mount host 路径不存在时,**docker engine 自动建空目录**(mkdir 行为);mount 时 source 是目录但 dest 是文件,冲突
- **修法:** compose 改用 `env_file: ./dev.env.ops`(compose 读文件 → 注入 ENV 变量),不涉及 bind mount
- **规则:** 容器配置文件 → 默认用 `env_file`

---

### 坑 7 — nginx /api/ 单一前缀不匹配前端

- **现象:** 前端点 Register 报 404,response body 是 nginx 默认 404 HTML
- **根因:** `frontend/config/proxy.ts` 列了 11 个 dev proxy 前缀,nginx 只接 /api/,其他 10 个落到 location / → 转给前端 nginx → 404
- **修法:** nginx.conf 改正则 + `proxy_pass http://backend:7777;`(不带末尾 /)
- **规则:** 做反代第一件事 `grep frontend/config/proxy.ts`,看 dev 列了哪些路径

---

## 复盘 — 重新做我会怎么改

第 1 分钟要做的预装 / 验证(不是"撞了再修"):

```bash
# 装 OS 后立刻验:
docker compose version               # 没 v2 就 binary 装
skopeo --version                      # 没就 brew install skopeo

# 写 nginx.conf 前立刻 grep:
grep -E '/(api|auth|testcase|...)/.*proxy' frontend/config/proxy.ts

# 写 Dockerfile 前先 grep:
grep -rn wait-for-it backend/ops/    # 死代码检测
grep -rn cnpm frontend/                # 老黄历检测
```

第 1 分钟要装的工具:

- `skopeo`(避免后面追 docker push SWR bug)
- `jq`(debug 时读 docker inspect 友好)
- `docker-compose-plugin` 或对应 binary(国产 OS 没带,准备好)

第 1 分钟要建立的假设:

- 单盘 40G → 数据卷全落系统盘,**没有"挂到 /data" 这种偷懒假设**
- Docker compose v2 tag 默认值别用 `:latest`,**用 `:v0.2` 这种固定值或 `${TAG:-v0.2}`**,否则下次不传 TAG 时找不到镜像

---

## 留给未来自己的 3 件事

### 真想变强(脱离 AI 能干活)

不是看更多 AI 输出,是**自己写一遍**。挑 1 个今天部署的零件(比如 nginx.conf / docker-compose.deploy.yaml / push-to-swr.sh),**关 AI,关文档,从 0 写**。卡住的地方就是你的真增长点。

3 个候选练习(挑 1 个):

1. **手写 `docker-compose.deploy.yaml`** —— 不看今天那版,自己设计 5 服务,再 diff 看差在哪
2. **手写 `nginx.conf`** —— 不看,自己推断要 proxy 哪些路径,然后 `curl localhost/api/auth/register` 验
3. **手搭一遍本地 5 服务**(同 server 上那样)—— `docker compose up -d`,验 register 能通

每个 ~30 分钟,卡了就开 AI 问具体一点(比如"nginx.conf 这里 location 块怎样拆"),不要全开。

### 沉淀路径知识

不是总结"做了什么",而是**对比 2-3 选项 + 代价**。今天的 5 个决策都是这个格式:

> 选了 X,因为 A 的代价是 Y,B 的代价是 Z,X 在我的约束下最优

下次遇到类似问题,**先把上次的决策找出来** — 看约束变了没,变了就重选,没变就照抄。这比每次重新想快 100 倍。

### 区分"AI 干"和"我跟 AI 一起干"

- AI 干 = 我读报错 + 我贴方案 + 我跑命令 + 你看结果。**今天 90% 的时间是这个**
- 一起干 = 你先猜 / 你先 grep / 你先试一个方案,**我补充**。**今天 10% 是这个**

下次想问问题前,**先自己 grep 5 分钟**。grep 不到 / 试了一两个思路卡住的,再开 AI。**卡住 5 分钟比问 1 分钟多学 5 倍**。

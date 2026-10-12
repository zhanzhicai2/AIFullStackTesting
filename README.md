# AIFullStackTesting

> Pity API 测试平台 — 一个面向中小团队的开源接口自动化测试平台。采用 FastApi 后端 + React 前端的全栈方案,支持用例管理、定时调度、用例录制、在线 HTTP/SQL/Redis 客户端等功能。

![Python](https://img.shields.io/badge/Python-3.10+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.95+-green)
![React](https://img.shields.io/badge/React-18+-blue)
![UmiJS](https://img.shields.io/badge/UmiJS-4-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

## 简介

Pity 是从 0 开始构建的接口自动化测试平台,2026 年起统一为 monorepo(`AIFullStackTesting`)。代码以 Pity 上游项目为基础做了二次开发与 AI 化改造 —— 后端用 FastAPI + SQLAlchemy,前端用 UmiJS + Ant Design。

上游项目地址(感谢 [wuranxu/pity](https://github.com/wuranxu/pity) 开源):
- 后端: [wuranxu/pity](https://github.com/wuranxu/pity)
- 前端: [wuranxu/pityWeb](https://github.com/wuranxu/pityWeb)

## 快速开始

### 环境要求

| 工具      | 版本            | 说明                          |
|---------|---------------|-----------------------------|
| Python  | 3.10+         | 后端依赖                        |
| Node.js | 20 LTS        | 前端依赖(项目 CI 用 Node 20)        |
| MySQL   | 5.7+ / 8.0+  | 数据库                        |
| Redis   | 5+            | **可选**,用于定时任务分布式锁;不启用会重复执行定时任务 |

### 一键启动(开发模式)

打开两个终端:

**终端 1 — 后端**

```bash
cd backend
pip install -r requirements.txt

# 编辑 conf/dev.env,改 MySQL/Redis/GitHub OAuth 连接信息
# 第一个注册的用户自动成为超级管理员

python main.py
# → 监听 http://localhost:7777
```

**终端 2 — 前端**

```bash
cd frontend
# 1) 如果没装 Node 20,设镜像后装
NVM_NODEJS_ORG_MIRROR=https://npmmirror.com/mirrors/node nvm install 20
nvm use    # 自动切到 .nvmrc 锁的版本

# 2) 清理旧产物(首次或之前失败时)
rm -rf node_modules package-lock.json

# 3) 装包(monorepo 子目录跑 npm install 会卡在 husky install,见 §7.6)
npm install --ignore-scripts

npm run start:dev
# → 浏览器打开 http://localhost:8000
```

> 详情见 [`backend/CLAUDE.md`](backend/CLAUDE.md) 与 [`frontend/CLAUDE.md`](frontend/CLAUDE.md)

### Docker 启动(开发环境)

`backend/ops/docker-compose.yaml` 已经配置好 MySQL + Redis + 后端,一键拉起:

```bash
cd backend/ops
docker-compose up -d
```

## 项目结构

```
AIFullStackTesting/
├── backend/                    # FastAPI 后端 (Python 3.10+, port 7777)
│   ├── app/
│   │   ├── routers/            # API 路由(按模块目录)
│   │   ├── models/             # SQLAlchemy 数据模型
│   │   ├── crud/               # DAO 层
│   │   ├── schema/             # Pydantic 验证模型
│   │   ├── core/               # 业务核心:用例执行引擎、参数解析、构造器
│   │   │   ├── constructor/    # 5 种用例构造器(HTTP / SQL / Redis / Python / 嵌套)
│   │   │   └── paramters/      # JSONPath / Regex / KV / StatusCode 解析
│   │   ├── middleware/         # CORS、错误处理、请求日志
│   │   ├── enums/              # 业务枚举
│   │   └── utils/              # JWT、Redis、通知等
│   ├── alembic/                # 数据库迁移脚本
│   ├── conf/                   # 环境变量(dev.env / pro.env)
│   ├── ops/                    # Docker / supervisor 部署文件
│   ├── templates/              # HTML 模板(测试报告)
│   ├── statics/                # 前端构建产物(部署时填充)
│   ├── main.py                 # 开发模式入口(uvicorn)
│   ├── pity.py                 # 生产模式入口(Gunicorn)
│   └── CLAUDE.md
│
├── frontend/                   # UmiJS 前端 (Node 20, port 8000)
│   ├── config/                 # UmiJS 配置(routes, proxy, defaultSettings)
│   ├── src/
│   │   ├── models/             # dva 状态管理
│   │   ├── services/           # API 请求层
│   │   ├── pages/              # 业务页面(镜像路由结构)
│   │   │   ├── ApiTest/        # 接口用例、录制、测试计划
│   │   │   ├── Dashboard/      # 工作台
│   │   │   ├── Tool/           # 在线 HTTP / SQL / Redis 客户端
│   │   │   ├── Manager/        # 后台管理
│   │   │   └── ...
│   │   ├── components/         # 共享组件(ProTable / CodeEditor / ...)
│   │   ├── consts/             # 角色、状态、断言类型等全局常量
│   │   └── utils/              # auth (JWT) / request (umi-request)
│   ├── mock/                   # 开发 mock 数据
│   ├── tests/                  # Jest 单元测试
│   └── CLAUDE.md
│
├── .github/workflows/          # CI: deploy-backend.yml / deploy-frontend.yml
├── .gitignore
└── README.md
```

## 技术栈

### 后端

| 层       | 选型                                               |
|---------|--------------------------------------------------|
| Web     | FastAPI · Uvicorn · Gunicorn                      |
| ORM     | SQLAlchemy + 异步 AsyncSession                   |
| 迁移     | Alembic                                            |
| 数据库    | MySQL                                              |
| 缓存 / 锁 | Redis                                              |
| 调度     | APScheduler(分布式锁由 Redis 实现)                    |
| 鉴权     | JWT · GitHub OAuth 第三方登录                         |
| 抓包 / 录制 | mitmproxy · HAR 转换                                  |
| Mock    | 内置 Mock 服务器(`MOCK_ON=True` 启用)                  |
| 通知     | 邮件 · 钉钉 · 企微(开发中)                               |
| 日志     | Loguru                                             |

### 前端

| 层        | 选型                                                              |
|---------|-----------------------------------------------------------------|
| 框架      | React 18 · TypeScript · UmiJS 4 (`@umijs/max`)                |
| UI      | Ant Design 5 · Ant Design Pro Components                       |
| 状态管理   | dva(老) + `@umijs/plugin-model`(新文件)                         |
| 请求层    | umi-request(业务) · `@umijs/max` request(底层)                 |
| 鉴权     | JWT(`localStorage.pityToken`)                                    |
| 测试     | Jest                                                            |
| Lint    | ESLint + Prettier                                                |
| 包管理    | npm / yarn / pnpm(开发脚本都用 `npm run`)                       |

## 已有功能

### 测试核心

- ✅ 用例构造器:HTTP / SQL / Redis / Python / 嵌套用例,5 种
- ✅ 参数提取:JSONPath · Regex · KV · Status Code
- ✅ 全局变量 + 用例依赖参数传递
- ✅ 用例录制(mitmproxy)+ HAR 文件导入
- ✅ 测试集合(串行 / 并行)
- ✅ 测试计划 + 定时调度(APScheduler + Redis 锁)
- ✅ 测试报告(HTML 模板,带截图)
- ✅ 数据工厂(开发中)

### 平台能力

- ✅ 用户注册(首个用户自动超管)· JWT · GitHub OAuth
- ✅ 项目管理 · 角色权限(user / admin / superAdmin)
- ✅ 全局变量 · 环境管理 · 数据库配置 · Redis 配置
- ✅ 在线 HTTP 测试(类 Postman)
- ✅ 在线 SQL 客户端(多数据源)
- ✅ 在线 Redis 客户端
- ✅ Mock 配置 / Mock 服务
- ✅ 文件上传测试(对接 OSS)
- ✅ 操作日志 · 通知中心
- ✅ 工作台 · 数据统计

### 待开发

- 🚧 数据工厂 · 精准测试 · 用例评分 · 组织架构
- 🚧 CI/CD(类 pipeline): 已落地 GitHub Actions,平台内 CI 在前端 `frontend/src/pages/CI/`

## 开发命令速查

| 用途        | 命令                | 位置              |
|-----------|-------------------|-----------------|
| 启动后端      | `python main.py`  | `backend/`      |
| 后端热重载    | `uvicorn main:pity --reload` | `backend/`      |
| 数据库迁移     | `alembic upgrade head`     | `backend/`      |
| 启动前端      | `npm run start:dev`        | `frontend/`     |
| 前端构建      | `npm run build`            | `frontend/`     |
| 前端 lint   | `npm run lint`             | `frontend/`     |
| 前端 lint 修复 | `npm run lint:fix`         | `frontend/`     |
| 前端测试      | `npm run test`             | `frontend/`     |
| 仅类型检查     | `npx tsc --noEmit`         | `frontend/`     |
| 部署前端到后端 | `bash deploy.sh`           | `frontend/`     |

## 配置

后端从环境变量 / `.env` 文件加载配置(`pity` 通过 `pity_env=dev|pro` 切环境):

- 关键配置:MySQL 连接 · Redis 连接 · GitHub OAuth(`CLIENT_ID` / `SECRET_KEY`) · `SERVER_PORT` · `MOCK_ON` · `PROXY_ON`
- dev 默认读 [`backend/conf/dev.env`](backend/conf/dev.env)
- 生产推荐用环境变量注入,避免 `.env` 上仓库

前端核心配置在:
- [`frontend/config/defaultSettings.ts`](frontend/config/defaultSettings.ts) — 主题 / API 地址 / WS 地址
- [`frontend/config/proxy.ts`](frontend/config/proxy.ts) — 开发模式 API 代理

## 部署

### CI/CD(GitHub Actions)

仓库自带两个 workflow:

- [`.github/workflows/deploy-backend.yml`](.github/workflows/deploy-backend.yml) — `backend/**` 变更时触发,经 SCP 推送到部署机后重启 Gunicorn
- [`.github/workflows/deploy-frontend.yml`](.github/workflows/deploy-frontend.yml) — `frontend/**` 变更时触发,构建后 SCP 推送到部署机,PM2 重启

两个 workflow 都支持手动 `workflow_dispatch`。需要在仓库 Settings → Secrets 配置:

| Secret       | 用途                |
|--------------|-------------------|
| `HOST`       | 部署服务器 IP/域名     |
| `USERNAME`   | SSH 用户            |
| `PASSWORD`   | SSH 密码            |

### 手动部署

```bash
# 1. 后端:本地构建产物
cd backend
pip install -r requirements.txt

# 2. 前端:本地构建 → 复制到后端 statics
cd frontend
npm run build
cp -r dist/* ../backend/statics/

# 3. 一键脚本(开发)
bash deploy.sh
```

## 二次开发约定

- 后端 DAO 文件命名 `XxxDao.py`,放在 `backend/app/crud/<模块>/` 下,用 `@ModelWrapper(Model)` 装饰器绑定
- 前端**新文件**用 TypeScript + `@umijs/plugin-model` hooks 风格;老 dva model 保留不迁移
- 路由 authority: `user (0)` · `admin (1)` · `superAdmin (2)`
- 项目角色: `MEMBER (0)` · `ADMIN (1)` · `OWNER (2)`
- 修改 2025-10-12 之前编写的代码优先创建新文件,与原作者商量后再决定

## License

MIT,详见 [`backend/LICENSE`](backend/LICENSE)。

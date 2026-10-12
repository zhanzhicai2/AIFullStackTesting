# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
请始终使用简体中文与我对话，并在回答时保持专业、简洁

## 项目性质

AIFullStackTesting 是 Pity API 测试平台的 monorepo,从 2026 年起把原 `pity`(后端) 与 `pityWeb`(前端) 合并管理。上游项目: [wuranxu/pity](https://github.com/wuranxu/pity) · [wuranxu/pityWeb](https://github.com/wuranxu/pityWeb)。

完整文档拆到两个子目录,本文件只记录跨模块和 monorepo 层级的约定。

- 后端相关(包括架构、DAO/Model/Schema 流程、执行引擎、响应码) → [`backend/CLAUDE.md`](backend/CLAUDE.md)
- 前端相关(包括 dva model、路由表、API 代理、编码规范) → [`frontend/CLAUDE.md`](frontend/CLAUDE.md)

## 目录布局

```
AIFullStackTesting/
├── backend/         # FastAPI 后端 (Python 3.10+, port 7777)
├── frontend/        # UmiJS 前端 (Node 20,  port 8000)
├── .github/workflows/
│   ├── deploy-backend.yml    # backend/** 变更触发, SCP + Gunicorn
│   └── deploy-frontend.yml   # frontend/** 变更触发, npm build + PM2
└── README.md
```

每个子目录都有自己的 `CLAUDE.md`,进入对应模块工作时优先读那里的文件。

## 常用命令

### 跨模块

```bash
# 一键拉起开发依赖(MySQL + Redis + 后端)
cd backend/ops && docker-compose up -d

# 一键构建前端并把产物塞到后端 statics
bash frontend/deploy.sh
```

### 后端

```bash
cd backend
pip install -r requirements.txt
python main.py                                # 开发启动 (0.0.0.0:7777)
uvicorn main:pity --reload                    # 热重载
alembic revision --autogenerate -m "描述"      # 生成迁移
alembic upgrade head                          # 执行迁移
```

环境变量 `pity_env=dev`(默认) 读 `backend/conf/dev.env`,`pity_env=pro` 读 `pro.env`。首个注册用户自动成为超管。

### 前端

```bash
cd frontend
npm install
npm run start:dev                              # 开发 (localhost:8000)
npm run build                                  # 生产构建
npm run lint                                   # ESLint + Prettier + tsc
npm run lint:fix                               # 自动修复 ESLint
npm run test                                   # Jest
npm run test:coverage                          # 覆盖率
npx tsc --noEmit                               # 仅类型检查
```

## 跨模块约定

这些是前后端必须保持一致的硬性约定。

### 角色与权限

- 用户角色(全局路由 `authority`):
  - `user (0)` · `admin (1)` · `superAdmin (2)`
- 项目内角色(项目成员表):
  - `MEMBER (0)` · `ADMIN (1)` · `OWNER (2)`
- 用例构造器类型(`construct_type` 字典):
  - `0` 测试场景 · `1` SQL · `2` Redis · `3` Python · `4` HTTP

### 响应协议

所有 HTTP 响应都是 `200`,业务码在 body 里:

```json
{"code": 0, "data": {}, "msg": "操作成功"}
```

| code | 含义 |
|------|------|
| `0` | 成功 |
| `101` | 参数错误(RequestValidationError 自动捕获) |
| `110` | 业务异常 |
| `401` | 未登录(AuthException) |
| `403` | 无权限(PermissionException) |

### 鉴权

- JWT 存储在 `localStorage.pityToken` (key 名固定)
- 前端 service 调用通过 `auth.headers()` 注入
- 后端用 `Depends(Permission())` 解析,`Permission(role=Config.ADMIN)` 限定角色

### 代码改动守则

- **2025-10-12 之前编写的代码优先创建新文件**,确实需要改老代码时先和原作者确认
- 后端 DAO 命名 `XxxDao.py`,放在 `backend/app/crud/<模块>/`,配 `@ModelWrapper(Model)` 装饰器
- 前端**新文件必须用 TypeScript + `@umijs/plugin-model`(hooks 风格)**,老 dva model 不迁移,新旧通过 `useModel('name')` 统一消费
- 用例时间字段:`moment`,不要用 dayjs

## CI/CD

两个 workflow 都在仓库根 `.github/workflows/`,通过 `paths` 过滤:

| workflow | 触发 | 动作 |
|----------|------|------|
| `deploy-backend.yml` | `backend/**` 变更 | SCP `backend/` 到部署机 → `pip install` → `pkill gunicorn` |
| `deploy-frontend.yml` | `frontend/**` 变更 | 在 CI 里 `npm run build` → SCP `dist/` → `pm2 restart` |

都需要 GitHub Secrets:`HOST`、`USERNAME`、`PASSWORD`。两个都支持手动 `workflow_dispatch`。

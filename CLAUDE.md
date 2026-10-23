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
│   ├── deploy-docker.yml      # 后端/前端/nginx/scripts/ops 变更触发, GH build + SWR push + ssh pull/up
│   └── monitor-deploy.yml     # 每 30 分钟 cron 健康检查, curl 后端 + 邮件告警
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
python pity.py                           # 开发启动 (0.0.0.0:7777)
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
npm run lint                                   # ESLint + Prettier + tsc(tsc 那步当前无效, 见 frontend/CLAUDE.md)
npm run lint:fix                               # 自动修复 ESLint
npm run test                                   # Jest
npm run test:coverage                          # 覆盖率
npx tsc --noEmit                               # ⚠️ 目前检测不到类型错误, 别用它做验收
npx -y -p typescript@5.9.2 tsc -p tsconfig.json --noEmit   # ✅ 真正能查类型错误(原因见 frontend/CLAUDE.md)
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

- 后端 DAO 命名 `XxxDao.py`,放在 `backend/app/crud/<模块>/`,配 `@ModelWrapper(Model)` 装饰器
- 前端**新文件必须用 TypeScript + `@umijs/plugin-model`(hooks 风格)**,老 dva model 不迁移,新旧通过 `useModel('name')` 统一消费
- 用例时间字段:`moment`,不要用 dayjs

## CI/CD

两个 workflow 都在仓库根 `.github/workflows/`,Docker 化部署 + 健康检查闭环:

| workflow | 触发 | 动作 |
|----------|------|------|
| `deploy-docker.yml` | `backend/**` / `frontend/**` / `nginx/**` / `scripts/**` / `backend/ops/**` 变更 | GH Actions build 3 镜像 → push SWR → ssh pull/up |
| `monitor-deploy.yml` | cron 每 30 分钟(可手动触发) | curl `/auth/login`,5xx/000 → GH fail → 邮件告警 |

`deploy-docker.yml` 需要的 GitHub Secrets:`HOST`、`USERNAME`、`PASSWORD`、`SWR_ACCESS_KEY`、`SWR_SECRET_KEY`;Variables:`SWR_REGISTRY`、`SWR_ORG`、`TAG`(默认 `dev`)。两个 workflow 都支持手动 `workflow_dispatch`。

## 工具配置

### Claude Code 自动 commit hook

项目级 `.claude/settings.json` 注册了一个 `Stop` hook:**每轮 Claude Code 对话结束(Stop 事件触发)时,会向 Claude 注入一段 prompt,让它先 `git status` 检查改动,有未提交改动就生成 conventional commit message 并 `git commit`,完成后才能真正退出**。

**约束**(详细步骤见 `.claude/hooks/auto-commit.md`):
- 排除 `.claude/memory/`、`.claude/settings.local.json`、`.claude/agents/local/` 等个人/本地状态 — 这些不该入库
- **逐个** add 文件路径(`git add <path>`),**禁止** `git add .` / `git add -A` / `git add *`
- **代码审查** — commit 前若本次是实质代码改动(非纯文档/配置,且改动 ≥ 20 行),会先跑一次 `code-review` 并修掉发现的问题,再一起提交。纯文档或小改动会跳过
- **push 时机** — 晚 **20:30–21:30**(9 点 ±30 分钟)之间自动 `git push`;**其他时间不 push**,你自己手动 `git push`
- commit message 走 Conventional Commits(`type(scope): subject`)

**调整方式**(改 `.claude/hooks/auto-commit.md` 里的对应步骤):
- 想关掉自动 commit:把 `.claude/settings.json` 里的 `hooks.Stop` 数组清空(留个空 `[]` 或直接删字段)
- 想关掉自动代码审查:删掉 `auto-commit.md` 的第 6 步;或调它的跳过阈值(`< 20 行` 那个数字)
- 想加更严的过滤(比如只允许 commit `backend/` 和 `frontend/`):改第 3 步排除规则
- 想换成 commit 前弹确认:把第 9 步的"`git commit`"改成"展示 diff 和拟用 message,等用户确认后再 commit"
- 想改自动 push 的时间窗口(比如改成 22:00–23:00):改第 10 步里的 `20:30–21:30` 字符串
- 想彻底禁用自动 push(永远手动):把第 10 步改成"`git push` 永远不跑,只在结尾告诉用户'push 由你手动执行'"

**为什么 20:30–21:30 是 push 窗口**:
- 20:30 是给还在用 Claude Code 干活的人留的缓冲 — 即使你踩着 9 点才收工,只要在 9:30 之前关掉会话,改动会跟着 commit 一起推上去
- 21:30 之后到次日 20:30 之前:不自动推,白天手动推 — 防止 AI 在工作时间误推触发 CI、推错分支、或把没 review 的代码公开
- **只要看到 Claude 在 20:30–21:30 窗口内自动 push,先自己 `git log -1` 看一眼再确认**

### 版本与 CHANGELOG

版本源是 **git tag**(SemVer,如 `v2.1.0`),日常改动累积在根目录 `CHANGELOG.md` 的 `[Unreleased]` 段 —— **日常提交不动 CHANGELOG**。

- 用户说"打版本"或输入 `/release` 时,按 `.claude/commands/release.md` 的流程归档 `[Unreleased]` 并打 tag
- bump 规则:有 `feat` → MINOR;只有 `fix`/`docs`/`chore` → PATCH;不兼容改造 → MAJOR(先确认再动)
- **打版本后不自动 push tag**,让用户自己 `git push && git push --tags`
- 一个功能拆成多个 commit 时,CHANGELOG 里合并成**一条**,不要按 commit 重复罗列


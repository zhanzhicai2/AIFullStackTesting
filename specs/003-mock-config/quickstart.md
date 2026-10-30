# Quickstart: Mock 配置

**Branch**: `003-mock-config` | **Date**: 2026-10-30 | **Spec**: [spec.md](./spec.md)

## 1. 环境准备

```bash
# 后端(需要 MySQL,Redis 可关)
cd backend/ops && docker-compose up -d        # MySQL + Redis + 后端依赖
cd ../..
cd backend && python pity.py                  # 起后端 (0.0.0.0:7777)

# 前端(Node 20)
cd frontend && nvm use && npm run start:dev   # localhost:8000
```

建表:新表 `pity_mock_rule` 由 SQLAlchemy `create_all` 自动创建(与 001/002 相同方式);若走 alembic 则 `alembic revision --autogenerate -m "mock rule" && alembic upgrade head`。

## 2. 端到端场景

### 场景 A:配置一条规则并被被测系统命中

1. 登录 → 进入「Mock 配置」菜单(`/mock`)
2. 选择一个项目(项目 `app` 非空;为空时界面就地提示 → 先去项目设置补全)
3. 点「新建规则」:method `GET`、path `/api/user/:id`、状态码 `200`、响应体 `{"code":0,"data":{"id":"$request.path","name":"$request.query.name"}}`、延迟 `100`
4. 保存 → 列表出现该规则,基地址区显示 `http://localhost:7777/mock/{app}/`
5. 在调试入口填入 method `GET`、path `/api/user/1?name=tom` → 命中该规则,响应体渲染为 `{"code":0,"data":{"id":"/api/user/1","name":"tom"}}`
6. 用 curl 走真实对外入口:

```bash
curl -s "http://localhost:7777/mock/{app}/api/user/1?name=tom"
# → {"code":0,"data":{"id":"/api/user/1","name":"tom"}}  (约 100ms 后返回)
```

### 场景 B:未命中与边界

```bash
curl -s "http://localhost:7777/mock/{app}/api/nonexist"     # 404 {"code":404,...,"msg":"mock rule not found"}
curl -s "http://localhost:7777/mock/no-such-app/x"           # 同上(不泄露信息)
```

### 场景 C:启停与删除

1. 停用规则 → 立即 `curl` 同一路径返回 404;重新启用 → 立即恢复
2. 删除规则 → 返回 404
3. 新建一条与既有规则「同方法+同精确路径」的规则 → 提示已存在,但仍可保存(靠优先级区分)

### 场景 D:权限

1. 用非项目成员账号(非超管)访问该项目的规则列表 → 403
2. 项目成员账号 → 可增删改启停

## 3. 回归命令

```bash
# 后端(核心门禁)
cd backend
.venv/bin/python scripts/mock_selftest.py     # 不依赖数据库:匹配全表 + 变量正反例 + 源码静态扫描
.venv/bin/python scripts/mock_e2e.py          # 需要数据库:管理链路 + 对外服务 + 权限 + 边界

# 前端
cd ../frontend
nvm use
npx tsc --noEmit                              # 目标 0 错误
npm run lint:js
```

## 4. SC 对照

| SC | 验证方式 |
|---|---|
| SC-001 配置到生效 ≤ 3 步 | 场景 A 第 1~6 步,1 分钟内完成 |
| SC-002 匹配 100% 确定 | `mock_selftest.py` 的「双跑一致」断言;同一 curl 连发两次响应逐字段一致 |
| SC-003 对外响应 ≤ 50ms(不含模拟延迟) | 场景 A 第 6 步,延迟配置 0 时耗时 < 50ms |
| SC-004 安全面可控 | `mock_selftest.py` 的 AST 静态扫描:mock 模块无出网调用、无 eval/exec |
| SC-005 规则质量闭环 | 场景 A 第 5 步,含变量规则 30 秒内看到「命中 + 解析后响应」 |

## 5. 已知限制

- 对外 mock 服务无鉴权(半公开):**不要在 mock 响应中放置真实凭据**;规则管理仍走平台鉴权
- `app` 重复时基地址命中最早创建的项目(配置页就地提示)
- 同名 query 参数多值只取第一个;body 变量仅支持 JSON 请求体
- 不做命中统计/限流(MVP 范围外)

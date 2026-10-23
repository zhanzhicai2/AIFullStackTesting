# CLAUDE.md

> 请始终使用简体中文与我对话，并在回答时保持专业、简洁

## 项目概述

Pity 前端 — Pity API 测试平台的 React 前端项目。基于 UmiJS v4 (`@umijs/max`)、Ant Design v5、Ant Design Pro Components 构建。后端为 Python FastAPI 应用。

## 开发命令

```bash
nvm use                 # 自动切到 .nvmrc 锁的 Node 20(umi 4.x 不兼容 Node 22/24)
npm install --ignore-scripts   # monorepo 子目录跑 npm install 必须加 --ignore-scripts
npm run start:dev       # 启动开发服务器 (localhost:8000, 代理到后端 :7777)
npm run build           # 生产构建
npm run lint            # 完整 lint (ESLint + Prettier + tsc; tsc 那步当前无效, 见下)
npm run lint:fix        # 自动修复 ESLint 问题
npm run test            # 运行 Jest 测试
npm run test:coverage   # 运行测试并生成覆盖率报告
npx tsc --noEmit        # ⚠️ 目前检测不到类型错误, 别用它做验收
npx -y -p typescript@5.9.2 tsc -p tsconfig.json --noEmit   # ✅ 真正能查类型错误
```

### ⚠️ TypeScript 检查当前是失效的

`npx tsc --noEmit`（以及 `npm run lint` 里的 tsc 那一步）**报不出任何 `src/` 下的类型错误**，不要拿它的"0 错误"当验收结果。

- 现象：它固定输出 70 个错误，全部在 `node_modules/@ant-design/pro-form/.../*.d.ts`（TS 4.9.5 解析不了 TS 5 语法）。
- 后果：这些 `.d.ts` 语法错误会让整个**语义检查被跳过** —— 实测往 `src/` 里写故意的类型错误，tsc 一条都不报。
- ESLint 也没兜住：本仓库的 eslint 配置没开 type-aware 规则，同样查不出这类问题。
- 绕过办法（不改仓库依赖）：
  ```bash
  npx -y -p typescript@5.9.2 tsc -p tsconfig.json --noEmit
  ```
  这条能正常检查。当前基线是 **44 个错误，全部是既有的**（`components/TestCase/recorder/*`、`components/TestCase/variableModal.tsx`、`pages/Ai/*`、`pages/Chat/index.tsx`、`models/auth.ts`），改代码时只要**别让这个数字变多**，尤其别在自己改的文件里新增。
- 根因是 `typescript@4.9.5` 与 `@ant-design/pro-form`（TS 5 语法）不匹配。升级 TypeScript 能根治，但会波及全站，是独立任务。

## 技术架构

### 框架与构建

- **UmiJS v4** + `@umijs/max` 预设 — 处理路由、状态管理(dva)、请求、构建
- **无 `.umirc.ts`** — 配置拆分到 `config/` 目录 (routes, proxy, defaultSettings)
- **路径别名**: `@/*` → `src/*`, `@@/*` → `src/.umi/*`

### 请求层（双系统并存）

1. **`@umijs/max` request** — 配置在 `src/app.tsx` → `src/requestErrorConfig.ts`（基于 Axios，带拦截器）
2. **`umi-request`** — 自定义封装在 `src/utils/request.js`（大部分 service 文件使用）

大多数 service 文件使用 `umi-request` 封装，通过 `import request from '@/utils/request'` 引入，手动通过 `auth.headers()` 附加认证头（来自 `src/utils/auth.ts`）。

### 认证机制

- JWT token 存储在 `localStorage`，key 为 `pityToken`
- 每个 service 调用手动注入认证头: `headers: auth.headers()`
- 401 响应触发重定向到 `/user/login`（`src/utils/auth.ts` 处理）
- 初始用户状态在 `src/app.tsx` → `getInitialState()` 中获取

### 状态管理 (dva models)

`src/models/` 中的模型遵循 dva 模式: `namespace`, `state`, `reducers`, `effects`。通过 `useModel('modelName')` hook 访问。

核心 model:

- `auth.ts` — 认证状态
- `testcase.js` — 测试用例 CRUD（最大的 model）
- `testplan.js` — 测试计划管理
- `project.js` — 项目状态
- `constructor.js` — 构造器/断言类型
- `notice.ts` — 通知消息
- `recorder.js` — 用例录制
- `gconfig.js` — 全局配置

### 路由

定义在 `config/routes.ts`。路由使用懒加载（字符串组件路径如 `'./ApiTest/TestCaseDirectory'`）。通过 `authority` 属性控制角色访问。详情/编辑页从菜单隐藏 (`hideInMenu: true`)。

主要路由结构:

| 路径           | 说明                                | 权限             |
| -------------- | ----------------------------------- | ---------------- |
| `/user/login`  | 登录                                | 公开             |
| `/dashboard/*` | 工作台、统计                        | 已登录           |
| `/project`     | 项目管理                            | 已登录           |
| `/apiTest/*`   | 接口用例、录制、测试计划            | 已登录           |
| `/record/*`    | 构建历史、测试报告                  | 已登录           |
| `/config/*`    | 环境管理、全局变量、数据库等        | admin/superAdmin |
| `/system/*`    | 系统设置、用户管理                  | superAdmin       |
| `/tool/*`      | HTTP 测试、SQL 客户端、Redis 客户端 | 已登录           |
| `/mock`        | Mock 配置                           | 已登录           |
| `/ci`          | 持续集成                            | 已登录           |
| `/datafactory` | 数据工厂                            | 已登录           |

### API 代理

`config/proxy.ts` 在开发模式下将所有 API 前缀代理到 `http://0.0.0.0:7777`: `/api/`, `/auth/`, `/testcase/`, `/config/`, `/project/`, `/operation/`, `/workspace/`, `/oss/`, `/notification/`, `/online/`, `/request/`

### 关键配置文件

- `config/defaultSettings.ts` — 布局主题、主色、API/WS 地址、应用标题
- `src/consts/config.ts` — 所有应用常量（角色、优先级、断言类型、用例状态、构造器类型、布局配置等）

## 项目结构

```
frontend/
├── config/                    # UmiJS 配置
│   ├── routes.ts              # 路由定义
│   ├── proxy.ts               # API 代理配置
│   ├── defaultSettings.ts     # 布局/主题/URL 配置
│   └── config.ts              # 其他 UmiJS 配置
├── src/
│   ├── app.tsx                # 应用入口、getInitialState、layout 配置
│   ├── requestErrorConfig.ts  # @umijs/max 请求错误处理配置
│   ├── consts/
│   │   └── config.ts          # 全局常量（角色、状态、断言类型等）
│   ├── models/                # dva 状态管理
│   ├── services/              # API 请求服务
│   ├── pages/                 # 页面组件（镜像路由结构）
│   │   ├── ApiTest/           # 接口测试（用例、录制、计划）
│   │   ├── Dashboard/         # 工作台
│   │   ├── BuildHistory/      # 测试报告
│   │   ├── Config/            # 测试配置（环境、数据库、Redis等）
│   │   ├── Manager/           # 后台管理
│   │   ├── Tool/              # 实用工具（HTTP/SQL/Redis）
│   │   ├── User/              # 登录
│   │   ├── uiTest/            # UI测试（开发中）
│   │   └── datafactory/       # 数据工厂
│   ├── components/            # 共享组件
│   │   ├── TestCase/          # 测试用例相关组件
│   │   ├── Project/           # 项目相关组件
│   │   ├── PityForm/          # 自定义表单
│   │   ├── CodeEditor/        # 代码编辑器
│   │   ├── Table/             # 表格组件
│   │   ├── Tree/              # 树形组件
│   │   └── ...                # 其他通用组件
│   └── utils/
│       ├── auth.ts            # 认证工具（token、401处理）
│       ├── request.js         # umi-request 封装
│       ├── common.js          # 通用工具函数
│       └── utils.js           # 其他工具
├── mock/                      # Mock 数据
├── tests/                     # 测试文件
├── types/                     # 类型定义
└── package.json
```

## 编码规范

### Service 模式

`src/services/` 中的 service 文件导出 async 函数，调用方式:

- URL 拼接: `${CONFIG.URL}/endpoint`
- 传入 method、data/params、auth headers
- 响应格式: `{ code: number, data: any, msg: string }`，`code === 0` 表示成功

### 页面组件

页面位于 `src/pages/`，镜像路由结构。标准 CRUD 界面使用 Ant Design Pro 组件 (ProTable, ProForm, ProList)。共享组件位于 `src/components/`。

### 状态管理迁移策略

项目现有 dva model（`namespace`/`reducers`/`effects`）继续保留，不做迁移。**新文件必须使用纯 hooks 风格**（`@umijs/plugin-model`），为 React 19 及后续版本做准备。

```typescript
// 新 model 示例: src/models/newFeature.ts
import { useState, useCallback } from 'react';

export default function useNewFeature() {
  const [list, setList] = useState([]);
  const fetchList = useCallback(async () => {
    /* ... */
  }, []);
  return { list, fetchList };
}
```

两种风格通过 `useModel('name')` 统一消费，可共存无需配置改动。

### 语言

项目混合使用 TypeScript (`.ts/.tsx`) 和 JavaScript (`.js/.jsx`)。**新文件应使用 TypeScript**。

### 日期处理

使用 `moment`（非 dayjs）。

### 角色常量

`src/consts/config.ts` 中定义三个用户角色: `user (0)`, `admin (1)`, `superAdmin (2)`。路由通过 `authority` 数组控制访问权限。

### 项目角色

- `OWNER (2)` — 负责人
- `ADMIN (1)` — 组长
- `MEMBER (0)` — 组员

### 用例构造器类型

- `0` — 测试场景
- `1` — SQL 语句
- `2` — Redis 命令
- `3` — Python 方法
- `4` — HTTP 请求

## 重要规则

1. 前端开发服务器运行在 `localhost:8000`，后端 API 运行在 `localhost:7777/7778`。
3. `localStorage` 中的 `pityToken` 是 JWT token 的 key。
4. 后端 FastAPI 应用的根目录在 `../backend/`。

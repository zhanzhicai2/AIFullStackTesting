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
npm run lint            # 完整 lint (ESLint + Prettier + tsc)
npm run lint:fix        # 自动修复 ESLint 问题
npm run test            # 运行 Jest 测试(6 套件 / 85 测试,退出码 0)
npm run test:coverage   # 运行测试并生成覆盖率报告
npx tsc --noEmit        # ✅ 类型检查, 当前 0 错误

# 扫 antd 废弃 API(v5→v6 迁移期用, 见「Ant Design 写法」小节)
npx -y @ant-design/cli@6.7.2 --format json lint src --only deprecated --version 6.7.2
```

### TypeScript 检查

`npx tsc --noEmit`（`npm run lint` 里的 tsc 那一步）**是有效的**，可以拿它的"0 错误"当验收结果。

- 版本：仓库锁 `typescript@5.9.2`。**不要降回 4.x** —— `@ant-design/pro-form@2.32.0` 和 `@types/node@26.x` 的 `.d.ts` 用了 TS 5.0 才有的 `const` 泛型参数（`function f<const T extends ...>`），TS 4.x 解析不了这个语法，**语义检查会被整个跳过**，表现为：`src/` 里写故意的类型错误，tsc 一条都不报，只剩 `node_modules` 里的语法错误。
- `skipLibCheck: true` 只跳过 `.d.ts` 的**类型检查**，跳不过**语法解析**，救不了这种情况。
- ESLint 没兜底：本仓库的 eslint 配置没开 type-aware 规则，类型错误只有 tsc 能查。
- 改代码后建议 `./node_modules/.bin/tsc -p tsconfig.json --noEmit`（等价于 `npx tsc --noEmit`），目标是 **0 错误**。

### Jest 测试

`npm run test` **现在可以跑起来**（2026-10-26 修复）。此前完全跑不起来，根因和现状：

- **根因**：`@umijs/max/test` 的 `createConfig` 只给 css/less 系列做了资源映射，**没映射 `.svg`**。Jest 于是把 svg 当 js 源码解析，报 `SyntaxError: Unexpected token '<'`。触发路径是 `src/app.tsx:11` 的 `import NoTableData from "@/assets/NoSearch.svg"` —— 测试文件只要碰了 `@@/`（如 `@@/testBrowser`），umi 生成的运行时入口就会加载 `app.tsx`，把它所有顶层 import 一起拽进来。
- **修复**：`jest.config.ts` 里叠加 `moduleNameMapper`，把 `\.svg$` 指向 `tests/__mocks__/svgMock.jsx`（默认导出 url 字符串 + `ReactComponent`，对齐 umi 编译期的导出形状）；同时加了 `passWithNoTests: true`。
- **⚠️ 顺序陷阱（很容易再踩）**：jest 的 `moduleNameMapper` 按 **key 插入顺序**匹配，**首个命中即生效，且不会递归重匹配**。`configUmiAlias`（`umi/dist/test.js`）会把 umi 的路径别名写进 `moduleNameMapper`（`^@/(.*)$` → `src/$1`）。所以 **svg 规则必须排在别名规则前面** —— 否则 `@/assets/NoSearch.svg` 会先被改写成绝对路径，svg 规则再也匹配不上，报错和没加一样。
- **⚠️ 跑测试用 `npm test` / `npm run jest`，不要用 `npx jest`**：`package.json` 里有 `"jest": "jest"` 这个 script，npm 7+ 的 `npx` 会优先匹配**本地 script** 而不是 `node_modules` 里的二进制，于是进入交互式 npm script 环境（提示 `Entering npm script environment` + `sh-3.2$`），把命令卡住不返回。
- **⚠️ 必须 Node 20**：Node 22+ 移除了 `process.binding('http_parser')`，jest 连配置文件都解析不了，报 `Error: Register plugin .../registerMethods.js failed, since No such module: http_parser` —— 这跟 jest 配置无关，纯粹是 node 版本问题。跑之前先 `nvm use`。
- **注意**：svg 资源以后再新增格式（png/webp 等）同样要在 `moduleNameMapper` 里补，umi 那边不会替你兜底。
- **当前状态（2026-11-24 起）**：仓库**已有真实测试用例** —— 6 个套件 / 85 个测试，`npm test` 退出码 0，耗时约 20s：

  | 套件 | 内容 | 用时 |
  |------|------|------|
  | `tests/contracts/ci.test.ts` | `src/consts/ci.ts` ↔ 后端 `backend/app/enums/CiEnum.py` | <1s |
  | `tests/contracts/uiTest.test.ts` | `src/consts/uiTest.ts` ↔ 后端 `backend/app/core/ui_executor.py` | <1s |
  | `tests/utils/cron.test.ts` | `src/utils/cron.ts` 纯函数 | ~1s |
  | `tests/utils/tool.test.ts` | `src/utils/tool.ts` 纯函数 | ~1s |
  | `tests/components/ToolShell.test.tsx` | 工具页外壳组件 | ~16s |
  | `tests/pages/CronParser.test.tsx` | 工具页页面 + 交互 | ~17s |

- **跨端契约测试是重点**：CLAUDE.md 要求前后端常量「改一处必须同时改另一处」，`tests/contracts/` 用 `fs.readFileSync` **直接解析后端 Python 源码**（正则抽 `NAME = <int>` 常量、`ACTIONS` / `STRATEGIES` 字典），再与前端镜像**逐字段**比对 —— 任何一端单独改动都会红灯。**以后加跨端常量，照这个模式补契约测试。**
  - ⚠️ 解析 Python class 体用 `indexOf` 切片，**不要用 `\Z`**（JS 正则没有这个转义）；常量正则要**要求缩进**，否则会连类后面的模块级常量一起吞进来。
  - ⚠️ 平台全局码（`0/101/110/401/403`）**没有单一权威定义**（散落在 `backend/app/handler/fatcory.py`、`backend/app/__init__.py`），只能断言期望值；只有 CI 专属码（`111/112`）以 `CiEnum.py` 为准。
- **⚠️ jsdom 没有 `TextEncoder` / `TextDecoder`**：`src/utils/tool.ts` 的 UTF-8 编解码依赖它们，缺了报 `ReferenceError: TextEncoder is not defined`。已在 `tests/setupTests.jsx` 里从 `node:util` 补上 polyfill。
- **⚠️ 中文文本要按「去空白后相等」匹配**：antd Button 的文本从 DOM 取出时带空白（`<span>清 空</span>`），`getByText('清空')` 与 `getByRole('button', { name: '清空' })` **都会匹配失败**。正确写法：`screen.getByText((content) => content.replace(/\s/g, '') === '清空')`。
  - ⚠️ **匹配失败会 dump 整个 DOM**，单条测试曾因此耗时 **500s+**。断言尽量精确 —— `getByText(/分/)` 这类宽泛选择器会匹配到多个元素而失败，同样触发 dump。
- **没有 `@testing-library/jest-dom`**：只能用基础断言（`toBeTruthy` / `toBe`），不能写 `toBeInTheDocument()`。
- **组件/页面测试成本远高于纯函数测试**（16~17s vs 1s）—— 优先给纯函数和跨端契约补测试；页面测试只挑**零 request / 零 model 依赖**的（如 `pages/Tool/CronParser.tsx`），依赖 `useRequest` 的要先 mock `@/services/*`。
- **写新测试的坑**：umi 4 的 svg **默认导出是 url 字符串**，`ReactComponent` 才是 React 组件（见 `src/.umi-production/typings.d.ts`）。antd `Empty` 的 `image` 属性两种都吃，但如果你要当组件渲染必须用 `ReactComponent`。


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
│   │   ├── config.ts          # 全局常量（角色、状态、断言类型等）
│   │   └── uiTest.ts          # UI 自动化常量（镜像后端 ui_executor.py）
│   ├── models/                # dva 状态管理 + hooks 风格新 model
│   ├── services/              # API 请求服务
│   ├── pages/                 # 页面组件（镜像路由结构）
│   │   ├── ApiTest/           # 接口测试（用例、录制、计划）
│   │   ├── uiTest/            # UI 自动化（Element/ 元素库、CaseManage/ 用例）
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

### Ant Design 写法（v5 → v6 迁移期约定）

当前锁 **antd 5.29.3**（v5 终版），**尚未升 v6**。上游闸门未开：`@ant-design/pro-components` stable 2.8.10 的 peer 只到 `^5.11.2`（仅 `beta` 3.x 支持 `antd ^6`），`@umijs/max` 最新版仍声明 `antd ^4.20.6`、其 layout 插件依赖 `pro-components ^2.0.1`。

**核心规则：只写 v5 和 v6 都支持的写法（取交集）。v5 没有的 v6 新属性一律不碰** —— 混着写会把 v5 直接写坏。

**A 类 · v5 已双支持，新代码一律用新写法**（升级时零改动）

| 场景 | ✅ 用这个 | ❌ 别再写 |
|------|-----------|-----------|
| Card 去边框 | `variant="borderless"` | `bordered={false}` |
| Card / Modal / Drawer 内容区样式 | `styles={{body: {...}}}` | `bodyStyle={{...}}` |
| 关闭时销毁 | `destroyOnHidden` | `destroyOnClose`（v5 已标 `@deprecated`） |
| 下拉/弹层类名 | `classNames={{popup: {...}}}` | `popupClassName` / `dropdownClassName` |
| 空状态图片 | `styles={{image: {...}}}` | `imageStyle` |
| Tooltip 类名 | `classNames={{root: ...}}` | `overlayClassName` |
| 菜单数据 | `items={[...]}` | 手写 `<Menu.Item>` children |
| Tabs 销毁面板 | `destroyOnHidden` | `destroyInactiveTabPane` |

**B 类 · v5 根本没有新写法，只能写旧的**（升级时靠 codemod 批量换，**现在千万别提前改**）

| 场景 | 现在只能写 | v6 才有 |
|------|-----------|---------|
| Space 排列方向 | `direction="vertical"` | `orientation` |
| Divider 竖线 | `type="vertical"` | `orientation`（⚠️ v5 的 `orientation` 是 `left/right/center`，**语义完全不同**，提前改 = 行为错） |
| Tabs 位置 | `tabPosition="left"` | `tabPlacement` |
| Drawer 遮罩点击关闭 | `maskClosable={false}` | `mask.closable`（v5 的 `mask` 是 `boolean`） |

**C 类 · 迁移期不动**（改法非机械，等 v6 实测）：`Dropdown overlay`（v6 官方废弃清单未列它，且 `overlay` 收 ReactElement、`menu` 收 props 对象）、`Dropdown.Button`、`Timeline.Item`。

**升级时的三堆活**：① B 类 + 剩余废弃 API 走官方 CLI / codemod 自动过；② 样式层手改 —— 20 个 less 文件依赖 `.ant-*` 内部类名 + 23 处 `:global`/深选择器，是唯一无法自动化、也最估不准的部分；③ pro-components 3.x 转正 + umi 适配 —— 只能等上游。

**所以 A 类现在就该改、B 类现在千万别改**，两条方向相反，混做会把 v5 搞坏。目标：升级时 A 类增量为零、B 类存量锁死在可 codemod 的范围内。

**迁移现状（2026-11-24）**：A 类已清零（`Card.bordered` 37 / `bodyStyle` 20 / `destroyOnClose` 13 / `TreeSelect.dropdownStyle` 1，共 71 处），CLI 复检 v6 废弃项从 297 降到 **230**，剩下的全是 B 类：

| 数量 | 规则 | 说明 |
|---|---|---|
| 87 | `Alert.message` → `title` | 最大单项，v5 无 `title` 属性 |
| 39 | `Space.direction` → `orientation` | v5 只有 `direction` |
| **28** | `List` → `Listy` | **组件级替换**，v5 无 `Listy`，只能等升级 |
| 18 | `Statistic.valueStyle` → `styles.content` | v5 无 `styles` |
| 17 | `Divider.type` → `orientation` | ⚠️ v5 的 `orientation` 语义完全不同 |
| 9 | `Drawer.width` → `size` | v5 的 `size` 是 `default\|large`，不是尺寸值 |
| 11 | `Select.filterOption` / `optionFilterProp` | |
| 9 | `Input/InputNumber.addonBefore` → `Space.Compact` | v5 有 `Space.Compact`，但改法需重构 JSX |
| 4 | `Tabs.tabPosition` → `tabPlacement` | v5 无 `tabPlacement`（来自 `rc-tabs`） |

**查漏用官方 CLI**（手工 grep 会漏，两边互补）：

```bash
npx -y @ant-design/cli@6.7.2 --format json lint src --only deprecated --version 6.7.2
```

- `--version` 决定用哪套废弃规则：默认按当前装的 antd（5.x）只报 **57** 处，`--version 6.7.2` 才出 v6 全量（**297** 处）。
- ⚠️ **CLI 的规则库也不全**（它漏报 `Modal.bodyStyle`），所以要**手工核对 + CLI 交叉验证**，不能只信一边。
- `npx -y @ant-design/cli@6.7.2 migrate 5.29.3 6.7.2 --apply src` 可生成受影响文件清单。

**其他 v6 硬性要求**：`@ant-design/icons` 必须 ≥ 6 且**与 antd 同升**（icons@6 与 antd@5 不兼容）；v6 默认启用 CSS variables，只支持现代浏览器；`antd@6` 要求 React ≥ 18（本项目 18.3.1 ✅）。

### 依赖陷阱（改依赖前后都要看）

- **`rc-field-form` 必须显式声明在 `dependencies`**：`@ant-design/pro-form` 把它列为 peer（`>=1.22.0`），但 antd5 要 `2.7.1`、pro-form 要 `1.x`，`npm install` 重算 hoisting 时会把顶层那份**移走** → `pro-form` 从自己目录向上找不到 → `Cannot find module 'rc-field-form'`（构建与 jest 全挂）。已显式锁 `"rc-field-form": "^1.44.0"` 固定在顶层。
  - **教训**：别只看 `npm install` 退出码，要验证关键 peer 的**顶层解析**：
    ```bash
    node -e "console.log(require.resolve('rc-field-form',{paths:[require('path').resolve('node_modules/@ant-design/pro-form/lib')]}))"
    ```
- **`@ant-design/charts` 锁 1.4.3，不要升 2.x** —— 2.x 是真 breaking：
  - `TinyArea` 被移除（改名 `Tiny`）
  - **`RingProgress` 直接消失且无替代**（`@ant-design/plots` 2.x 无此导出），得换图表类型（`RadialBar`/`Gauge`）+ 人工视觉验证
  - `@antv/g6-plugin` 用了 `@antv/path-util` 却**没声明**该依赖（graphs 2.x 的依赖 bug），得手动补
  - 图表渲染 jsdom 测不了、只能人眼看 —— 这条要等有视觉验证条件时再做
- `npm ls` 会报 `@ant-design/charts` 的 peer `invalid`（1.x 把 antd peer 写死成 `^4.6.3`）—— **已知无害**，实际运行在 antd5 上正常，不要为此盲目升级。
- **webpack/mfsu 缓存会记住模块解析失败**：`node_modules/.cache/mfsu`（曾达 922MB）。依赖装好后 dev server 仍报 `Cannot find module` 时，先 `rm -rf node_modules/.cache/mfsu node_modules/.cache/bundler-webpack` 再重启 dev server（umi dev 是父子进程，只 kill 父进程端口不会释放）。

- **外网域名依赖（`static.pity.fun` / `oss.pity.fun`）**：平台作者的公网服务，**域名已失效**（`static.pity.fun` DNS 能解析但 HTTPS 连接超时，`oss.pity.fun` 直接失败）。⚠️ **这不是"内网无出口"** —— 生产用的**七牛云 API 是通的**（`upload.qiniup.com` 正常响应）。
  - ✅ **前端默认头像已改本地**：`AVATAR_URL` / `PROJECT_AVATAR_URL` → `src/assets/defaultAvatar.svg`（在 `config.ts` 里 `import` 进来）。这两个常量被 **13 处用户头像 + 6 处项目头像**引用，只改常量即可，调用点零改动。
  - ✅ 前端 `OSS_URL`（`http://oss.pity.fun/pity`）与 `WECHAT_URL` 都是**死常量**（全项目 0 引用，前端不直连 OSS），已删除。
  - ✅ **后端两个失效常量已移除**（2026-11-24）：`Config.OSS_URL` / `Config.QINIU_URL` 已删，桶的访问域名统一从 `configuration_*.json` 的 `oss.endpoint` 读（`OssClient` 分发时传入，`qiniu.py` 的 `get_url` 改成实例方法用 `self.domain`）；没配 endpoint 时回退到七牛默认域名 `http://{bucket}.hdslb.com`。改之前的状态是「上传到七牛成功、但存库的链接打不开、后端自己下载也失败（`private_download_url` 的签名基于错误域名）」。
    ⚠️ 生产 `oss.endpoint` 现填 `http://pity.hdslb.com`（七牛默认域名）—— **需与七牛控制台里 `pity` 桶的实际绑定域名核对**；若是自定义域名，改配置即可，不用改代码。
  - ✅ **dev 环境改用本地文件存储**：`configuration_dev.json` 的 `oss_type = "local"`，新增 `backend/app/middleware/oss/local.py`（继承 `OssFile`，文件落 `backend/data/oss/`，对外 URL `/oss/files/{key}`，由 nginx 与前端 dev proxy 代理）。原先的 `gitee` 配置是废弃的（Gitee 对象存储早已下线，且不在 `OssEnum` 里 → 调接口直接抛「不支持的oss类型」）。
  - ⚠️ **改 `configuration_*.json` 后必须清 Redis 缓存**（`SystemConfiguration.get_config()` 有 24 小时缓存，key `pity:SystemConfiguration:configuration`），否则继续读旧值 —— 本轮改 `oss_type` 时踩过。
  - 后端 `app/core/msg/dingtalk.py:30` 的钉钉通知里也引了一张 `static.pity.fun` 的图（`走势监测.png`）—— 同样不可达，通知里那张图会裂。
- 💡 **决策记录（2026-11-24）：不自建 MinIO**。理由：① 服务器目前**没有流量**（`pity_oss_file` 仅 8 行、0 个用户有头像），自建存储没有收益；② 生产机只有 **2 核 2G / 40G 系统盘**，compose 已限 **1.44G** 内存 —— MinIO 挤同机会和 MySQL(700M)、backend(600M) 抢内存抢盘，且单点无异地容灾；③ 换云厂商**零代码**（`SystemConfiguration` 驱动，改 `configuration_*.json` 的 `oss` 段即可）。
  → 若将来出现「必须数据自持 / 必须内网可达」的硬需求，走**独立一台**（1核1G+50G 盘），改动面：新增 `backend/app/middleware/oss/minio.py`（继承 `OssFile`，实现 5 个方法）+ `OssEnum` 加 `MINIO` + `OssClient` 分发加分支 + nginx 代理文件流量；**前端不用改**（`OSS_URL` 已无引用）。

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

### UI 自动化常量（跨端同步）

`src/consts/uiTest.ts` 里的 `UI_ACTIONS`（动作白名单）与 `UI_STRATEGIES`（8 种定位策略）是**后端 `backend/app/core/ui_executor.py` 的 `ACTIONS` / `STRATEGIES` 的镜像** —— **改一处必须同时改另一处**。契约文档：`../specs/002-ui-automation/contracts/steps.md`。

- 后端是最终裁决者（不合规的步骤被丢弃）；前端只做**提前提示**，不在前端做最终判定 —— 前端放行、后端丢弃会造成「改了还是被丢弃」的困惑
- `src/services/uiTest.ts` + `src/models/uiTest.ts`（hooks 风格）封装 `/ui/*` 的 27 个端点
- 页面在 `src/pages/uiTest/`（**小写 t**）：`Element/`（元素库）、`CaseManage/`（用例列表 + 用例编辑器）、`Record/`（录制导入）、`Execution/`（执行中心）、`Node/`（执行节点）
  - ⚠️ 目录名是 `uiTest` 不是 `UiTest` —— 仓库里早就有个同名的旧 JS 页面目录，macOS 大小写不敏感，写错大小写会让 TypeScript 报 TS1261、Linux CI 直接构建失败。**路径一律用磁盘上的真实大小写**
- 报告页 `src/pages/BuildHistory/ReportDetail.jsx` 扩了「附件」tab，展示 UI 用例的失败截图（数据来自 `/ui/execution/attachments`）
- **白名单为空 = 不可执行**（不是「允许全部」）：前端要提示「本项目尚未配置允许访问的域名，去配置」

### CI 常量（跨端同步）

`src/consts/ci.ts` 里的 `CI_ERROR_CODE`（业务码 `0/101/110/111/112/401/403`）与 `CI_RUN_STATUS`（触发记录六态）是**后端 `backend/app/enums/CiEnum.py` 的 `CiErrorCode` / `RunStatus` 的镜像** —— **改一处必须同时改另一处**。契约文档：`../specs/004-ci/contracts/api.md` §0、§4。

- **`3`（测试未通过）与 `5`（平台执行失败）必须可区分** —— 一个是测试红了、一个是平台坏了，文案与 Tag 颜色都不能混（spec FR-015 / SC-006）
- 接入示例片段里的凭据**恒为占位符 `YOUR_PITY_CI_TOKEN`** —— 片段要被粘进 Git 仓库，填真实凭据等于教用户把凭据提交进代码库；完整明文只在签发成功的那一个弹窗里出现一次
- `src/services/ci.ts` + `src/models/ci.ts`（hooks 风格）封装 `/ci/*` 的 8 个端点；页面在 `src/pages/ci/`
- CI 端点的鉴权 header 与平台同名（`token`），但值是 `pity_ci_` 前缀的长期凭据，**不是 JWT**

## 重要规则

1. 前端开发服务器运行在 `localhost:8000`，后端 API 运行在 `localhost:7777/7778`。
3. `localStorage` 中的 `pityToken` 是 JWT token 的 key。
4. 后端 FastAPI 应用的根目录在 `../backend/`。

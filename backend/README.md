[English](README_EN.md)

![png](https://img.shields.io/badge/Python-3.10+-green)
![png](https://img.shields.io/badge/React-18+-blue)
![png](https://img.shields.io/badge/FastApi-green)

## 🎉 技术栈

- [x] 🎨 FastApi
- [x] 🎶 SQLAlchemy
- [x] 🎉 Apscheduler(定时任务框架)
- [x] 🎃 mitmproxy(Mock、用例录制生成)
- [x] 🔒 Redis
- [x] 🏐 Gunicorn(内含 Uvicorn,部署服务)
- [x] 🎲 Nginx(反向代理、HTTPS 配置等)
- [x] 💎 OSS(用于文件上传时接口测试文件存储)
- [x] 👟 asyncio(几乎全异步写法,值得参考)
- [ ] ⛏ Grpc(支持 Grpc 请求,即将支持)

## ☕ 说明

这是一个从 0 开始写的接口自动化测试平台,采用 `Python` + `FastApi` + `React` 开发,严格遵循 "写一块代码、补一篇文章" 的形式。它经历了从 `Flask` 到 `FastApi` 的过渡,代码质量也许不是最高的,但对新人而言可以跟着从 `接口自动化框架` 走到 `接口自动化平台`,并看到持续优化的过程。

<details open="open">
<summary>火热开发中</summary>

| 功能点      | 敬请期待             |
|:---------|:-----------------|
| 数据工厂     | 🍔🍔🍔🍔         |
| Locust 结合 | 🍔🍔🍔🍔🍔 |
| Mock     | 🍔             |

</details>

## 🌙 已有功能

| 功能点            | 状态  |
|:---------------|:----|
| 精美的邮件/钉钉通知模板   | ✅  |
| 用例录制生成 🔥      | ✅   |
| har 导入 🔥       | ✅   |
| http 测试         | ✅   |
| 测试集合           | ✅   |
| 定时任务           | ✅   |
| 全局变量           | ✅   |
| 自定义脚本          | ✅   |
| 场景测试           | ✅   |
| 后台管理           | ✅   |
| 文件上传测试         | ✅   |
| 在线 SQL          | ✅   |
| 在线 Redis        | ✅   |
| 测试报告           | ✅   |
| 项目管理           | ✅   |
| 权限系统           | ✅   |
| 串行/并行执行用例      | ✅   |
| 参数提取           | ✅   |

## 🚚 即将到来

| 功能点          | 敬请期待 |
|:-------------|:-----|
| CI/CD        | 🎉🎉🎉   |
| HttpRunner 支持 | 🎉🎉🎉   |
| 数据工厂         | 🎉🎉🎉   |
| 精准测试         | 🎉🎉🎉   |
| 组织架构         | 🎉🎉🎉   |
| 用例评分         | 🎉🎉🎉   |

## 🐳 Docker 启动

1. 安装 Docker Desktop
2. 打开终端并进入 `backend` 目录
3. 执行以下命令,一键启动(内置 MySQL + Redis + 后端,无需额外安装):

```bash
docker-compose -f ops/docker-compose.yaml up
```

## 🎉 二次开发

1. 拉取代码

```bash
git clone https://github.com/zhanzhicai2/AIFullStackTesting.git
cd AIFullStackTesting/backend
```

2. 安装依赖

```bash
# 一次性创建 venv
uv venv --python 3.10
source .venv/bin/activate

uv pip install -r requirements.txt
# 可换豆瓣源或者清华源安装依赖
```

3. 安装并启动 Redis / MySQL

4. 修改 `conf/dev.env`

修改其中 MySQL 和 Redis 连接信息。Redis 不开启会导致 `定时任务重复执行`(基于 Redis 实现了分布式锁)。

5. 启动服务

```bash
python pity.py
```

6. 注册用户

打开浏览器输入 `http://localhost:7777` 进入登录页。

点击注册按钮,第一个注册的用户会成为 `超级管理员`,拥有一切权限。

登录后即可开启 Pity 之旅。

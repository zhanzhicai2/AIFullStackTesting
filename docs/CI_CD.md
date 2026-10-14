# GitHub Actions CI/CD 配置说明

> 新增于 2026-10-14
>
> **本文与 `DEPLOY_RUNBOOK.md` 的关系**：runbook 是"为何这样做 + 决策树"（用户主导的计划手册）；本文是"**已落地的 CI/CD 怎么配 + 怎么用**"。两者角色互补，按需查阅。本文涉及 GH Secrets / workflow 的部分以本文为准 — runbook §3 / §8 里的 `SWR_USER` / `SWR_PASS`、重写老 yml 那些方案**已经过时**，我们实际采用了**永久 AK/SK + 新建 deploy-docker.yml + 保留老 workflow**。

## 1. 整体流程

```
git push origin main
        ↓
.github/workflows/deploy-docker.yml
   ├─ 1. checkout
   ├─ 2. docker buildx 准备
   ├─ 3. apt 装 skopeo
   ├─ 4. ./scripts/build-images.sh ${TAG}    ← build pity-backend/frontend/nginx
   ├─ 5. ./scripts/push-to-swr.sh ${TAG}     ← skopeo copy → 华为云 SWR
   └─ 6. ssh root@124.71.69.165
            docker compose -f docker-compose.deploy.yaml \
              --env-file .env pull && \
            docker compose -f docker-compose.deploy.yaml \
              --env-file .env up -d
        ↓
服务器 5 容器自动跑新版本
```

## 2. 一次性配置(仓库 Settings)

路径:GitHub repo → **Settings → Secrets and variables → Actions**

### 2.1 Secrets(机密,密文存储)

| 名称 | 值 | 来源 |
|------|----|------|
| `HOST` | `124.71.69.165` | 服务器公网 IP(沿用老 workflow) |
| `USERNAME` | `root` | SSH 用户(沿用老 workflow) |
| `PASSWORD` | `********` | SSH 密码(沿用老 workflow) |
| `SWR_ACCESS_KEY` | `********` | 华为云 IAM 子用户永久 AK(见下 §2.3) |
| `SWR_SECRET_KEY` | `********` | 华为云 IAM 子用户永久 SK |

### 2.2 Variables(明文,公开配置)

切到 **Variables** tab(同位置)新增:

| 名称 | 值 | 说明 |
|------|----|------|
| `SWR_REGISTRY` | `swr.cn-south-1.myhuaweicloud.com` | 你的 SWR 区域地址(跟服务器 `dev.env.ops` 配套) |
| `SWR_ORG` | `pity` | SWR 组织/组织名 |
| `TAG` | `dev` | 默认 tag;workflow_dispatch 时可覆盖 |

### 2.3 创建 IAM 子用户(方案 A)

SWR 控制台"我的凭证 → 临时登录指令"生成的临时凭证 12h 过期,不适合放 GH Secrets(过期后 Action 失败)。改用**永久 AK/SK**:

1. 登录 [华为云控制台](https://console.huaweicloud.com)
2. **统一身份认证服务 → 用户 → 创建用户**
3. 用户名:`pity-actions`(随意),访问类型:**编程访问**(Programmatic access)
4. 授权:**只勾 `SWR FullAccess`**(再加 `Tenant Guest` 也行,看保险)
5. 创建后**立即保存**弹出的 AK/SK —— 这对字符串只显示一次
6. 把 AK/SK 分别填到 §2.1 的 `SWR_ACCESS_KEY` / `SWR_SECRET_KEY`

> ⚠️ 永久凭证意味着被盗=无限权限。建议在 IAM 控制台给该子账号:
> - 启用"登录保护"(MFA) — Actions 用不上 MFA,留作防御层
> - 启用"访问控制 → IP 限制" — 限制该 AK 只能从可信 IP 段调用(可填 `0.0.0.0/0` 不限制)
> - 不在主账号下用,只在 SWR 子操作下挂名,出问题影响范围可控

### 2.4 ⚠️ SWR login 的 username 格式必须带 region 前缀,且 password 不是 SK 本身

2026-10-14 实测坑:**SWR docker registry 不接受裸 AK,且 password 是 HMAC 派生值,不是 SK 字面**。docker login 必须用:

```bash
DERIVED_PASS=$(printf "%s" "<AK>" \
  | openssl dgst -binary -sha256 -hmac "<SK>" \
  | od -An -vtx1 | sed 's/[ \n]//g' | sed 'N;s/\n//')

docker login "swr.<region>.myhuaweicloud.com" \
  -u "<region>@<AK>" \
  --password-stdin <<< "$DERIVED_PASS"
```

举例:`swr.cn-south-1.myhuaweicloud.com` 对应 `cn-south-1@<AK>`,password 是 HMAC-SHA256(AK, SK) 的 64 字符小写 hex。

> **两个 SWR 强制规则**(不搞清楚就 `denied: Authenticate Error`):
> 1. **username 必须带 region 前缀**(`<region>@<AK>`),为了在多 region 账号下区分 namespace。
> 2. **password 是 HMAC-SHA256(AK, SK) 的 hex,不是 SK 本身**。SK 字面字符串当 password 会被 SWR 拒。
>
> 手动算验证:把 HK mac(`printf AK | openssl dgst -sha256 -hmac SK`)的输出当 docker login password 用,应看到 `Login Succeeded`。

workflow 已经把这两个坑都自动化了:
- `Derive SWR region from registry` step 用 `sed` 从 `SWR_REGISTRY` 动态提取 region
- `Derive SWR pass (HMAC-SHA256 of AK with SK)` step 在 push 前自动算 password
- **不要**再单独配 `SWR_REGION` 变量或手动改 `SWR_PASS`,会导致跟 workflow 不一致

## 3. 触发方式

### 3.1 自动 push 触发(推荐)

```bash
git push origin main
```

仅当改动在以下路径才会跑:
- `backend/**`
- `frontend/**`
- `nginx/**`
- `scripts/**`
- `backend/ops/**`

文档 / CLAUDE.md typo 不会触发。

### 3.2 手动触发(应急/重跑)

GitHub repo → **Actions → deploy-docker → Run workflow → 输入 tag(可选)→ Run**

手动触发时可以指定非默认 tag(比如 `v0.2`),便于发布带版本号的镜像,避免 `dev` tag 被覆盖后无法回滚。

## 4. 验证第一次跑

第一次跑建议手动 `workflow_dispatch` 触发,别直接 push 业务代码试。

跑完后检查:
- repo → Actions → deploy-docker run → **全部 step 绿色**
- 服务器上 `docker ps` 看 5 个 `-deploy` 容器都在 Up
- 浏览器访问服务器公网 IP,前端应正常加载
- SWR 控制台 → pity-backend / pity-frontend / pity-nginx 三个仓库 → "版本"页有新条目

## 5. 老 workflow 怎么处理

按"先留着做回滚兜底"思路,**当前不动**:
- `.github/workflows/deploy-backend.yml`
- `.github/workflows/deploy-frontend.yml`

它们用的还是 SCP + gunicorn + PM2 那条老路,跟现在的 docker-compose 部署**不冲突** —— 服务器上 docker compose 在跑,老 workflow 即使触发了,scp 推上去的代码也没人用(没有 gunicorn / PM2 在跑)。

跑顺新 workflow **至少一周**后,可以手动 `rm .github/workflows/deploy-backend.yml .github/workflows/deploy-frontend.yml` 删掉。

## 6. 排错速查

| 现象 | 排查方向 |
|------|---------|
| `skopeo: command not found` | `apt-get install` step 失败,看 apt 源是否要换华为云镜像(参考 `DEPLOY_DOCKER_MIGRATION.md` §11.3) |
| `push-to-swr.sh: ERROR: SWR_USER/SWR_PASS required` | GH Secrets 配错,或 `secrets.SWR_*` 拼写不一致 |
| `denied: requested access to the resource is denied` | IAM 子账号没绑 `SWR FullAccess` 角色,去 IAM 控制台加 |
| `ssh-action` 超时 | 服务器 SSH 密码错 / 安全组没放行 GH IP(可用 `nc -zv 124.71.69.165 22` 自测) |
| 服务器上 `pull` 拉镜像 `denied` | 服务器侧 `~/.docker/config.json` 还没 login;在服务器上手动 `docker login $SWR_REGISTRY` 一次即可 |

## 7. 关联文档

- [DEPLOY_DOCKER_MIGRATION.md](./DEPLOY_DOCKER_MIGRATION.md) — docker 化部署的完整背景 / 镜像命名约定 / SWR manifest bug 复盘
- [DEPLOY_RUNBOOK.md](./DEPLOY_RUNBOOK.md) — 历史"决策树"风格实施手册,§3/§8 已过时,本文为准
- [POSTMORTEM/2026-10-14-docker-deploy.md](./POSTMORTEM/2026-10-14-docker-deploy.md) — 当日 docker 化踩坑复盘
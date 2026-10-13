# dev 用 — 见 docs/DEPLOY_DOCKER_MIGRATION.md §11.1
# 注意:生产部署(用于 SWR push)走 frontend/Dockerfile.production,跟这份是分开的
# 2026-10-14 升级:node:18.18.2 → node:20-alpine(跟本地开发 Node 20 对齐;Node 18 已 EOL);
#              移除 cnpm 老黄历,改用 npm ci + 国内镜像;加 COPY 分层,改源码不重装依赖。
FROM node:20-alpine

WORKDIR /app

# 先只拷 manifest,装依赖 — 这样源码改动不触发依赖层重 build
COPY package.json package-lock.json ./
# 走 lockfile + 国内 registry,跟 Dockerfile.production 保持一致
RUN npm ci --no-audit --prefer-offline \
        --registry=https://registry.npmmirror.com

# 再拷源码
COPY . .

EXPOSE 8000
CMD ["npm", "start"]


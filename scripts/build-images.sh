#!/usr/bin/env bash
# 新增于 2026-10-14 — Step 1:本地构建 3 个自建镜像(pity-backend / pity-frontend / pity-nginx)
# MySQL 和 Redis 是 docker.io 公开镜像,不需要本地 build,server 上 docker compose pull 会自动拉
# 见 docs/DEPLOY_DOCKER_MIGRATION.md §4.1
#
# 用法: 在仓库根目录
#   ./scripts/build-images.sh           # 默认 tag = dev
#   ./scripts/build-images.sh 0.1       # tag = 0.1
#
# UI 自动化子系统: 后端镜像默认**不**装 chromium(体积 +~600MB)。
# 需要跑 UI 用例时用环境变量打开:
#   INSTALL_PLAYWRIGHT=1 ./scripts/build-images.sh dev
set -euo pipefail

cd "$(dirname "$0")/.."
TAG="${1:-dev}"
INSTALL_PLAYWRIGHT="${INSTALL_PLAYWRIGHT:-0}"

echo ">> [1/3] pity-backend:$TAG (INSTALL_PLAYWRIGHT=$INSTALL_PLAYWRIGHT)"
docker build -f backend/ops/dockerfile -t "pity-backend:$TAG" \
  --build-arg "INSTALL_PLAYWRIGHT=$INSTALL_PLAYWRIGHT" backend

echo ">> [2/3] pity-frontend:$TAG (max build 走国内 npm 镜像)"
docker build -f frontend/Dockerfile.production -t "pity-frontend:$TAG" frontend

echo ">> [3/3] pity-nginx:$TAG"
docker build -f nginx/Dockerfile -t "pity-nginx:$TAG" nginx

echo ""
echo ">> Done. 3 自建镜像:"
docker images | grep -E 'pity-(backend|frontend|nginx)' || true

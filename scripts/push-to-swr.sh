#!/usr/bin/env bash
# 新增于 2026-10-14 — Step 2:把 3 个自建镜像推到华为云 SWR
# 镜像 tag/push;mysql/redis 是公开镜像不走这里,server 上 pull 时自动取
# 见 docs/DEPLOY_DOCKER_MIGRATION.md §4.2 / §10
#
# 用法:
#   1. 先设置环境变量(可放 ~/.bashrc 或 scripts 旁的 .env.push):
#        export SWR_REGISTRY=swr.cn-north-4.myhuaweicloud.com
#        export SWR_ORG=<你的 SWR 组织名>
#        export SWR_USER=<SWR 临时访问凭证用户名>
#        export SWR_PASS=<SWR 临时访问凭证密码,12h 过期>
#   2. ./scripts/push-to-swr.sh           # 默认 tag = dev
#      ./scripts/push-to-swr.sh 0.1       # tag = 0.1
#   3. 服务器侧再 ssh 上去 docker compose pull && up -d(见 /home/tester/pity-deploy README)
set -euo pipefail

TAG="${1:-dev}"
: "${SWR_REGISTRY:?必须先 export SWR_REGISTRY,例如 swr.cn-north-4.myhuaweicloud.com}"
: "${SWR_ORG:?必须先 export SWR_ORG,你的 SWR 组织名}"
: "${SWR_USER:?必须先 export SWR_USER,SWR 临时凭证用户名}"
: "${SWR_PASS:?必须先 export SWR_PASS,SWR 临时凭证密码(12h 过期)}"

echo ">> SWR_REGISTRY=$SWR_REGISTRY"
echo ">> SWR_ORG=$SWR_ORG"
echo ">> TAG=$TAG"
echo ""

echo ">> [1/4] docker login $SWR_REGISTRY"
docker login -u "$SWR_USER" -p "$SWR_PASS" "$SWR_REGISTRY"

SELF_BUILT=(pity-backend pity-frontend pity-nginx)
i=2
for img in "${SELF_BUILT[@]}"; do
  echo ""
  echo ">> [$i/4] $img:$TAG → $SWR_REGISTRY/$SWR_ORG/$img:$TAG"
  docker tag  "$img:$TAG" "$SWR_REGISTRY/$SWR_ORG/$img:$TAG"
  docker push "$SWR_REGISTRY/$SWR_ORG/$img:$TAG"
  i=$((i + 1))
done

echo ""
echo ">> Done. 服务器侧 ssh 上去:"
echo "     cd /home/tester/pity-deploy"
echo "     docker login $SWR_REGISTRY"
echo "     SWR_REGISTRY=$SWR_REGISTRY SWR_ORG=$SWR_ORG TAG=$TAG \\"
echo "       docker compose -f docker-compose.deploy.yaml --env-file .env pull && \\"
echo "       docker compose -f docker-compose.deploy.yaml --env-file .env up -d"

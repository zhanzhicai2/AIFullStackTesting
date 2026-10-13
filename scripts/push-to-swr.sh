#!/usr/bin/env bash
# 2026-10-14 重写:由 docker tag + docker push 改成 skopeo
# 原方案(SWR 反复报 'Invalid image, fail to parse manifest.json')根因是 docker CLI 推
# manifest v2.2 跟 SWR 的解析器有兼容 bug。skopeo 直发 OCI distribution-spec HTTP,
# 对国内 SWR / 阿里云 ACR / 腾讯云 TCR 100% 兼容,绕过这个 bug。
# 见 docs/DEPLOY_DOCKER_MIGRATION.md §11.1
#
# 用法:
#   1. brew install skopeo         # 一次性,本机需要 skopeo 命令
#   2. 设置 4 个 env(SWR 控制台 → 我的凭证 → 临时登录指令 → 生成,12h 过期):
#        export SWR_REGISTRY=swr.<region>.myhuaweicloud.com
#        export SWR_ORG=<你的 SWR 组织名>
#        export SWR_USER=<SWR 临时访问凭证用户名>
#        export SWR_PASS=<SWR 临时访问凭证密码>
#   3. ./scripts/push-to-swr.sh        # 默认 tag = dev
#      ./scripts/push-to-swr.sh v0.2   # tag = v0.2(推荐,用版本号可避免 tag-level 残 manifest)
#   4. 服务器侧再 ssh 上去 docker compose pull && up -d(配合 -e SWR_REGISTRY=... -e TAG=...)
set -euo pipefail

TAG="${1:-dev}"
: "${SWR_REGISTRY:?必须先 export SWR_REGISTRY,例如 swr.cn-south-1.myhuaweicloud.com}"
: "${SWR_ORG:?必须先 export SWR_ORG,你的 SWR 组织名}"
: "${SWR_USER:?必须先 export SWR_USER,SWR 临时凭证用户名}"
: "${SWR_PASS:?必须先 export SWR_PASS,SWR 临时凭证密码(12h 过期)}"

if ! command -v skopeo &>/dev/null; then
  echo "ERROR: skopeo 未安装。请先 brew install skopeo" >&2
  exit 1
fi

# skopeo 在 Mac 上缺 trust policy 文件会拒启动(写成 permissive,仅本地开发用)
POLICY="$HOME/.config/containers/policy.json"
if [[ ! -f "$POLICY" ]]; then
  echo "WARN: $POLICY 不存在,自动创建 permissive policy"
  mkdir -p "$(dirname "$POLICY")"
  cat > "$POLICY" <<'EOF'
{
  "default": [
    {"type": "insecureAcceptAnything"}
  ]
}
EOF
fi

echo ">> SWR_REGISTRY=$SWR_REGISTRY"
echo ">> SWR_ORG=$SWR_ORG"
echo ">> TAG=$TAG"
echo ""

# 用临时目录装 docker save 的 tar,跑完自动清理
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

SELF_BUILT=(pity-backend pity-frontend pity-nginx)
total=${#SELF_BUILT[@]}
i=1

for img in "${SELF_BUILT[@]}"; do
  echo ""
  echo ">> [$i/$total] $img:$TAG → $SWR_REGISTRY/$SWR_ORG/$img:$TAG"

  # docker save → tar → skopeo docker-archive (source)
  # 不用 docker-daemon: 是因为 skopeo 在 Mac 上抓不到 /var/run/docker.sock
  TAR="$TMPDIR/${img}.tar"
  docker save "$img:$TAG" -o "$TAR"

  skopeo copy --dest-creds "$SWR_USER:$SWR_PASS" \
    "docker-archive:$TAR" \
    "docker://$SWR_REGISTRY/$SWR_ORG/$img:$TAG"

  i=$((i + 1))
done

echo ""
echo ">> Done. 服务器侧 ssh 上去:"
echo "     cd /home/tester/pity-deploy"
echo "     docker login $SWR_REGISTRY"
echo "     SWR_REGISTRY=$SWR_REGISTRY SWR_ORG=$SWR_ORG TAG=$TAG \\"
echo "       docker compose -f docker-compose.deploy.yaml --env-file .env pull && \\"
echo "       docker compose -f docker-compose.deploy.yaml --env-file .env up -d"

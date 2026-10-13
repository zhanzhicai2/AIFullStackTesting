# 新增于 2026-10-14
# 反代容器:把 :80 进来的请求按前缀分发到 backend (API) 或 frontend (静态)
# 见 docs/DEPLOY_DOCKER_MIGRATION.md §4.1
FROM nginx:1.27-alpine

# 覆盖官方默认配置(/etc/nginx/conf.d/default.conf),只用我们自己这份
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

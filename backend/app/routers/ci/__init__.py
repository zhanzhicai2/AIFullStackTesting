"""
CI 持续集成路由

前缀 `/ci`(由本文件统一加, 子模块不带前缀 —— 与 `app/routers/ui/` 同款)。

**两组端点、两种鉴权**:
- `integration/*` —— 凭据管理, `Permission(Config.MANAGER)`(仅 admin/superAdmin)
- `run/*`         —— 触发与查询, `CIPermission()`(项目级 CI 长期凭据)

接口清单与业务码表以 `specs/004-ci/contracts/api.md` 为准。
"""
from fastapi import APIRouter

from app.routers.ci.integration import router as integration_router
from app.routers.ci.run import router as run_router

router = APIRouter(prefix="/ci")

# ⚠️ 顺序: 先集成配置, 再触发查询。两组路径不重叠, 但保持「配置 → 使用」的阅读顺序
router.include_router(integration_router)
router.include_router(run_router)

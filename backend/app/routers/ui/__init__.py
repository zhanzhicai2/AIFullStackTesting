"""
UI 自动化路由

前缀 `/ui`, 全部走 `PityResponse` 的 `{code, data, msg}`。
接口清单以 `specs/002-ui-automation/contracts/api.md` 为准。
"""
from fastapi import APIRouter

from app.routers.ui.case import router as case_router
from app.routers.ui.domain import router as domain_router
from app.routers.ui.element import router as element_router
from app.routers.ui.node import router as node_router
from app.routers.ui.page import router as page_router

router = APIRouter(prefix="/ui")
router.include_router(page_router)
router.include_router(element_router)
router.include_router(domain_router)
router.include_router(node_router)
router.include_router(case_router)

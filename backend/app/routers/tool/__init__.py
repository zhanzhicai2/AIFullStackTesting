"""
实用工具路由 —— `/tool/*` 下的**无状态计算**接口。

⚠️ 这几个端点**刻意不挂 `request_info`**(见 `main.py` 的注册处):
- 它们不写库、不改数据, 记操作日志只会往 `pity_operation_log` 灌等量垃圾;
- `request_info` 会把 POST body 写进 DEBUG 日志, 而这里的 body 是用户粘贴的
  密文/明文/待加密文本, 明文落盘不合适(与 `ai_chat_router` 同一理由)。

鉴权照旧走 `Permission()` —— 已登录才能用, 与 `/online/*` 同级。
"""
from fastapi import APIRouter

from app.routers.tool.compare import router as compare_router
from app.routers.tool.crypto import router as crypto_router
from app.routers.tool.network import router as network_router

router = APIRouter(prefix="/tool", tags=["实用工具"])

router.include_router(compare_router)
router.include_router(crypto_router)
router.include_router(network_router)

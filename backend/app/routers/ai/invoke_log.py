"""
调用流水路由 —— 谁在什么时候用什么模型调了 AI、花了多少、成没成

契约见 `specs/001-ai-workbench/contracts/api.md` §2.1。

`error_msg` 不含 API Key, 也不含完整 prompt 正文(ai_service 在写入前已脱敏)。
"""
from fastapi import APIRouter, Depends

from app.crud.ai.AIInvokeLogDao import AIInvokeLogDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.routers.ai.base import router


@router.get("/invoke/log", description="AI 模型调用流水")
async def list_invoke_log(page: int = 1, size: int = 10, scene: str = None,
                          model_name: str = None, user_id: int = None,
                          start_time: str = None, end_time: str = None,
                          user_info=Depends(Permission())):
    """
    调用流水 —— 分页 + 按 scene / model_name / 用户 / 时间段过滤。
    """
    try:
        logs, total = await AIInvokeLogDao.list_logs(page=page, size=size, scene=scene,
                                                     model_name=model_name, user_id=user_id,
                                                     start_time=start_time, end_time=end_time)
        result = PityResponse.model_to_list(logs)
        return PityResponse.success_with_size(data=result, total=total)
    except Exception as e:
        return PityResponse.failed(e)

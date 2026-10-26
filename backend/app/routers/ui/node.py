"""
UI 执行节点路由

v1 只有内置的本地节点 —— 平台启动时注册一个 `local` 节点。
分布式节点是 v2, 但表与接口形状先定好, 避免 v2 时改调用方(research §3.12)。

节点是**平台级资源**, 删除需要 ADMIN。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.crud.ui.UINodeDao import UINodeDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from config import Config

router = APIRouter()


class UIHearbeatForm(BaseModel):
    """节点心跳 —— v1 由内置节点自注册"""
    name: str = "内置本地节点"
    node_type: str = "local"
    browser: str = "chromium"
    headless: bool = True
    max_concurrency: int = 2
    version: str = "1.0.0"


@router.get("/node/list", description="节点列表")
async def list_node(user_info=Depends(Permission())):
    try:
        data = await UINodeDao.list_nodes()
        return PityResponse.success(PityResponse.model_to_list(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/node/heartbeat", description="节点心跳 / 自注册")
async def node_heartbeat(form: UIHearbeatForm, user_info=Depends(Permission())):
    try:
        data = await UINodeDao.register_node(name=form.name, user_id=user_info['id'],
                                             node_type=form.node_type, browser=form.browser,
                                             headless=form.headless,
                                             max_concurrency=form.max_concurrency,
                                             version=form.version)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/node/delete", description="删除节点")
async def delete_node(id: int, user_info=Depends(Permission(role=Config.ADMIN))):
    try:
        await UINodeDao.delete_node(id, user_info['id'])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)

"""
允许域名白名单路由 —— **SSRF 安全边界**

**增删权限收紧到 `Config.ADMIN`** —— 它直接决定平台能访问哪些外部地址,
放宽它 = 放宽 SSRF 边界。配错等于放行内网。

**语义**: 白名单为空 → 该项目的 UI 用例**不可执行**(不是「允许全部」)。
这是刻意选的失败方向 —— 宁可跑不了, 也不能让平台裸奔到内网。
"""
from fastapi import APIRouter, Depends

from app.crud.ui.UIAllowedDomainDao import UIAllowedDomainDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.ui_case import UIAllowedDomainForm
from config import Config

router = APIRouter()


@router.get("/domain/list", description="允许域名列表")
async def list_domain(project_id: int, env: int = None, user_info=Depends(Permission())):
    try:
        data = await UIAllowedDomainDao.list_domains(project_id, env)
        return PityResponse.success(PityResponse.model_to_list(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/domain/insert", description="新增允许域名")
async def insert_domain(form: UIAllowedDomainForm, user_info=Depends(Permission(role=Config.ADMIN))):
    try:
        data = await UIAllowedDomainDao.insert_domain(form.domain, form.project_id,
                                                       user_info['id'], form.env)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/domain/delete", description="删除允许域名")
async def delete_domain(id: int, user_info=Depends(Permission(role=Config.ADMIN))):
    try:
        await UIAllowedDomainDao.delete_domain(id, user_info['id'])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)

"""
UI 元素库路由

**权限说明(constitution 要求对新增写入通道显式回应)**:
页面与元素的写入保持 `Permission()` —— 元素库是**团队协作资产**, 它的价值恰恰在于
「测试人员自己沉淀元素」; 而「创建用例」在既有平台本就是 `Permission()`,
UI 用例的写入权限与之同级, **不扩大权限面**。
真正需要收紧的是允许域名白名单(那是安全边界), 见 domain.py。

去重时返回既有元素 id 与 `duplicated` 标志 —— 同一个定位不应该在库里堆多份。
"""
from fastapi import APIRouter, Depends

from app.crud.ui.UIElementDao import UIElementDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.ui_case import UIElementForm, UIElementStatusForm

router = APIRouter()


@router.get("/element/list", description="元素列表")
async def list_element(project_id: int = None, page_id: int = None, status: int = None,
                        user_info=Depends(Permission())):
    try:
        data = await UIElementDao.list_elements(project_id=project_id, page_id=page_id, status=status)
        return PityResponse.success(PityResponse.model_to_list(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/element/insert", description="新建元素")
async def insert_element(form: UIElementForm, user_info=Depends(Permission())):
    try:
        data, duplicated = await UIElementDao.insert_element(
            name=form.name, strategy=form.strategy, locator=form.locator,
            project_id=form.project_id, page_id=form.page_id, user_id=user_info['id'],
            name_attr=form.name_attr, description=form.description)
        msg = "创建成功"
        if duplicated:
            msg = "已存在相同的定位策略与定位值, 已复用既有元素"
        return PityResponse.success(dict(id=data.id, duplicated=duplicated), msg=msg)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/element/update", description="修改元素")
async def update_element(form: UIElementForm, user_info=Depends(Permission())):
    try:
        if not form.id:
            return PityResponse.failed("缺少元素 id")
        data = await UIElementDao.update_element(element_id=form.id, project_id=form.project_id,
                                                  user_id=user_info['id'], name=form.name,
                                                  strategy=form.strategy, locator=form.locator,
                                                  name_attr=form.name_attr,
                                                  description=form.description, page_id=form.page_id)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/element/delete", description="删除元素")
async def delete_element(id: int, project_id: int, user_info=Depends(Permission())):
    try:
        await UIElementDao.delete_element(id, project_id, user_info['id'])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/element/status", description="启用 / 停用元素")
async def update_element_status(form: UIElementStatusForm, user_info=Depends(Permission())):
    try:
        data = await UIElementDao.update_status(form.id, form.project_id, user_info['id'], form.status)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)

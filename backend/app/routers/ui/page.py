"""
UI 页面树路由

页面是元素引用的键(「页面名」)。删除页面**不级联删元素** —— 元素转为停用,
并把受影响的元素名回显给用户去处理引用(data-model.md §8)。
"""
from fastapi import APIRouter, Depends

from app.crud.ui.UIPageDao import UIPageDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.ui_case import UIPageForm

router = APIRouter()


@router.get("/page/list", description="页面树")
async def list_page(project_id: int, user_info=Depends(Permission())):
    try:
        data = await UIPageDao.list_page_tree(project_id)
        return PityResponse.success(data)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/page/insert", description="新建页面")
async def insert_page(form: UIPageForm, user_info=Depends(Permission())):
    try:
        data = await UIPageDao.insert_page(name=form.name, project_id=form.project_id,
                                            user_id=user_info['id'], url=form.url,
                                            parent=form.parent, description=form.description)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/page/update", description="修改页面")
async def update_page(form: UIPageForm, user_info=Depends(Permission())):
    try:
        if not form.id:
            return PityResponse.failed("缺少页面 id")
        data = await UIPageDao.update_page(page_id=form.id, project_id=form.project_id,
                                            user_id=user_info['id'], name=form.name,
                                            url=form.url, parent=form.parent,
                                            description=form.description)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/page/delete", description="删除页面")
async def delete_page(id: int, project_id: int, user_info=Depends(Permission())):
    try:
        data = await UIPageDao.query_page(id)
        if data is None:
            return PityResponse.failed("页面不存在")
        if data.project_id != project_id:
            return PityResponse.failed("页面不属于当前项目")
        count, names = await UIPageDao.delete_page(id, user_info['id'])
        msg = "删除成功"
        if count:
            msg = f"删除成功, 页面下的 {count} 个元素已转为停用: {', '.join(names)}"
        return PityResponse.success(dict(element_count=count), msg=msg)
    except Exception as e:
        return PityResponse.failed(e)

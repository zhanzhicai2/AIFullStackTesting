from fastapi import Depends

from app.core.ai_client import fetch_remote_models
from app.core.ai_models import list_system_models
from app.crud.ai.AIModelDao import AIModelDao
from app.crud.ai.AIVendorDao import AIVendorDao
from app.enums.AIModelEnum import AIModelSourceEnum
from app.handler.fatcory import PityResponse
from app.routers import Permission, get_session
from app.routers.ai.base import router
from app.schema.ai import AIModelFetchForm, AIModelForm, AIModelImportDto, AIModelSystemForm, AIModelUpdateForm
from config import Config


@router.get("/model/list", description="厂商下的模型列表")
async def list_ai_model(vendor_id: int, _=Depends(Permission(Config.ADMIN))):
    try:
        models = await AIModelDao.list_model(vendor_id)
        return PityResponse.success(PityResponse.model_to_list(models))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/model/add", description="自定义添加模型")
async def add_ai_model(form: AIModelForm, user_info=Depends(Permission(Config.ADMIN))):
    try:
        model = await AIModelDao.insert_model(form.vendor_id, form.name, form.model_type,
                                              form.enable, AIModelSourceEnum.custom, user_info['id'])
        return PityResponse.success(PityResponse.model_to_dict(model))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/model/update", description="更新模型(启停/参数)")
async def update_ai_model(form: AIModelUpdateForm, user_info=Depends(Permission(Config.ADMIN))):
    try:
        model = await AIModelDao.update_model(form, user_info['id'])
        return PityResponse.success(PityResponse.model_to_dict(model))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/model/delete", description="删除模型")
async def delete_ai_model(id: int, user_info=Depends(Permission(Config.ADMIN)), session=Depends(get_session)):
    try:
        await AIModelDao.delete_record_by_id(session, user_info['id'], id, log=True)
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/model/fetch", description="从厂商接口拉取可用模型")
async def fetch_ai_model(form: AIModelFetchForm, _=Depends(Permission(Config.ADMIN))):
    try:
        vendor = await AIVendorDao.query_vendor(form.vendor_id)
        if vendor is None:
            return PityResponse.failed("厂商不存在")
        models = await fetch_remote_models(vendor.base_url, vendor.api_key)
        # 回传已有的模型名,方便前端默认勾选
        existing = await AIModelDao.list_model(form.vendor_id)
        existed = {m.name for m in existing}
        return PityResponse.success(dict(models=models, existed=list(existed)))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/model/system", description="获取系统预置模型模板")
async def system_ai_model(form: AIModelSystemForm, _=Depends(Permission(Config.ADMIN))):
    try:
        models = list_system_models(form.vendor_code)
        existed = []
        vendor = await AIVendorDao.query_vendor_by_code(form.vendor_code)
        if vendor is not None:
            existed = [m.name for m in await AIModelDao.list_model(vendor.id)]
        return PityResponse.success(dict(models=models, existed=existed))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/model/import", description="批量导入模型")
async def import_ai_model(form: AIModelImportDto, user_info=Depends(Permission(Config.ADMIN))):
    try:
        added, skipped = await AIModelDao.batch_insert_model(form.vendor_id, form.models, form.source,
                                                             form.model_types, user_info['id'])
        return PityResponse.success(dict(added=added, skipped=skipped),
                                    msg=f"成功导入 {added} 个模型" + (f",跳过 {skipped} 个已存在的模型" if skipped else ""))
    except Exception as e:
        return PityResponse.failed(e)
from fastapi import Depends

from app.crud.ai.AIVendorDao import AIVendorDao, mask_api_key
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.routers.ai.base import router
from app.schema.ai import AIVendorUpdateForm
from config import Config


def _to_dict(vendor) -> dict:
    """厂商转 dict,api_key 一律脱敏,避免明文密钥进入浏览器"""
    data = PityResponse.model_to_dict(vendor)
    data["api_key"] = mask_api_key(vendor.api_key)
    data["has_key"] = bool(vendor.api_key)
    return data


@router.get("/vendor/list", description="AI模型厂商列表")
async def list_ai_vendor(user_info=Depends(Permission(Config.ADMIN))):
    try:
        data = await AIVendorDao.list_vendor(user_info['id'])
        result = [{"vendor": _to_dict(item["vendor"]), "model_count": item["model_count"]} for item in data]
        return PityResponse.success(result)
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/vendor/query", description="查询AI模型厂商详情")
async def query_ai_vendor(id: int, _=Depends(Permission(Config.ADMIN))):
    try:
        vendor = await AIVendorDao.query_vendor(id)
        if vendor is None:
            return PityResponse.failed("厂商不存在")
        return PityResponse.success(_to_dict(vendor))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/vendor/update", description="保存AI模型厂商配置")
async def update_ai_vendor(form: AIVendorUpdateForm, user_info=Depends(Permission(Config.ADMIN))):
    try:
        vendor = await AIVendorDao.update_vendor(form, user_info['id'])
        return PityResponse.success(_to_dict(vendor))
    except Exception as e:
        return PityResponse.failed(e)
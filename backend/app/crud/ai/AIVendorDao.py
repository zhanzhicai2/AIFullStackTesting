from sqlalchemy import and_, func, select

from app.core.ai_models import VENDORS
from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ai_model import AIModel
from app.models.ai_vendor import AIVendor

# api_key 的脱敏占位符,前端提交回这个值时表示"保持原值不变"
MASK_FLAG = "***"


def mask_api_key(api_key: str) -> str:
    """API Key 脱敏:sk-abcdefghijkl -> sk-a***ijkl"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return f"{api_key[:2]}{MASK_FLAG}"
    return f"{api_key[:4]}{MASK_FLAG}{api_key[-4:]}"


def is_masked(value: str) -> bool:
    """判断前端提交的是否是脱敏占位符"""
    return bool(value) and MASK_FLAG in value


@ModelWrapper(AIVendor)
class AIVendorDao(Mapper):
    """
    AI 模型厂商配置,全局共享由超管维护

    读方法刻意不加 @RedisHelper.cache: 配置类数据量极小(默认10条),
    且左侧列表的启用状态要求保存后立刻可见,缓存只会带来脏读
    """

    @classmethod
    async def ensure_seed(cls, user_id: int) -> None:
        """
        幂等写入预置厂商,只补缺失的 code
        不会覆盖已配置好的 api_key/base_url/enable
        """
        async with async_session() as session:
            async with session.begin():
                query = await session.execute(select(AIVendor.code).where(AIVendor.deleted_at == 0))
                # select(code) 后 .scalars().all() 返回的就是字符串,不要再 row[0]
                exists = set(query.scalars().all())
                for index, item in enumerate(VENDORS):
                    if item["code"] in exists:
                        continue
                    session.add(AIVendor(name=item["name"], code=item["code"],
                                         en_name=item.get("en_name"),
                                         base_url=item.get("base_url"),
                                         console_url=item.get("console_url"),
                                         enable=False, builtin=True, sort=index,
                                         user=user_id))

    @classmethod
    async def list_vendor(cls, user_id: int) -> list:
        """
        厂商列表,带各厂商已配置的模型数量
        :return: [{"vendor": {...}, "model_count": 3}, ...]
        """
        await cls.ensure_seed(user_id)
        async with async_session() as session:
            sql = select(AIVendor, func.count(AIModel.id)).outerjoin(
                AIModel, and_(AIModel.vendor_id == AIVendor.id, AIModel.deleted_at == 0)
            ).where(AIVendor.deleted_at == 0).group_by(AIVendor.id).order_by(AIVendor.sort, AIVendor.id)
            result = await session.execute(sql)
            rows = result.all()
            return [{"vendor": row[0], "model_count": row[1]} for row in rows]

    @classmethod
    async def query_vendor(cls, vendor_id: int) -> AIVendor:
        async with async_session() as session:
            sql = select(AIVendor).where(AIVendor.id == vendor_id, AIVendor.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def query_vendor_by_code(cls, code: str) -> AIVendor:
        async with async_session() as session:
            sql = select(AIVendor).where(AIVendor.code == code, AIVendor.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def update_vendor(cls, form, user_id: int) -> AIVendor:
        async with async_session() as session:
            async with session.begin():
                vendor = await session.get(AIVendor, form.id)
                if vendor is None or vendor.deleted_at != 0:
                    raise Exception("厂商不存在或已删除")
                vendor.en_name = form.en_name
                vendor.base_url = form.base_url
                vendor.console_url = form.console_url
                vendor.enable = form.enable
                # 前端回显的是脱敏值,原样提交时保持原 Key 不变
                if form.api_key and not is_masked(form.api_key):
                    vendor.api_key = form.api_key
                vendor.update_user = user_id
                await session.flush()
                session.expunge(vendor)
                return vendor
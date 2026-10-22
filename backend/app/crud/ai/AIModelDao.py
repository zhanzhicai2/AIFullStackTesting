from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ai_model import AIModel


@ModelWrapper(AIModel)
class AIModelDao(Mapper):
    """
    AI 模型配置,隶属于某个厂商

    同 AIVendorDao: 读方法不加 Redis 缓存,配置页要求保存后立即可见
    """

    @classmethod
    async def list_model(cls, vendor_id: int) -> list:
        async with async_session() as session:
            sql = select(AIModel).where(AIModel.vendor_id == vendor_id,
                                        AIModel.deleted_at == 0).order_by(AIModel.sort, AIModel.id)
            result = await session.execute(sql)
            return result.scalars().all()

    @classmethod
    async def insert_model(cls, vendor_id: int, name: str, model_type: str, enable: bool,
                           source: int, user_id: int) -> AIModel:
        async with async_session() as session:
            async with session.begin():
                query = await session.execute(
                    select(AIModel).where(AIModel.vendor_id == vendor_id, AIModel.name == name,
                                          AIModel.deleted_at == 0))
                if query.scalars().first() is not None:
                    raise Exception(f"模型 {name} 已存在")
                model = AIModel(vendor_id=vendor_id, name=name, model_type=model_type,
                                enable=enable, source=source, user=user_id)
                session.add(model)
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def batch_insert_model(cls, vendor_id: int, models: list, source: int,
                                 model_types: dict, user_id: int) -> list:
        """
        批量导入模型,自动跳过已存在的同名模型
        :param models:   ["deepseek-chat", ...]
        :param model_types: {"deepseek-chat": "chat"},可选,用于带上模型类型
        :return: (新增数量, 跳过数量)
        """
        model_types = model_types or {}
        async with async_session() as session:
            async with session.begin():
                query = await session.execute(
                    select(AIModel.name).where(AIModel.vendor_id == vendor_id,
                                               AIModel.deleted_at == 0))
                exists = {row[0] for row in query.scalars().all()}
                added, skipped = 0, 0
                for item in models:
                    # 兼容前端传字符串或 {"name": ..., "model_type": ...} 两种格式
                    if isinstance(item, dict):
                        name, model_type = item.get("name"), item.get("model_type") or "chat"
                    else:
                        name, model_type = str(item), "chat"
                    if not name or name in exists:
                        skipped += 1
                        continue
                    exists.add(name)
                    session.add(AIModel(vendor_id=vendor_id, name=name,
                                        model_type=model_types.get(name, model_type),
                                        enable=False, source=source, user=user_id))
                    added += 1
                return added, skipped

    @classmethod
    async def update_model(cls, form, user_id: int) -> AIModel:
        async with async_session() as session:
            async with session.begin():
                model = await session.get(AIModel, form.id)
                if model is None or model.deleted_at != 0:
                    raise Exception("模型不存在或已删除")
                model.name = form.name
                model.model_type = form.model_type
                model.enable = form.enable
                if form.params is not None:
                    model.params = form.params
                model.update_user = user_id
                await session.flush()
                session.expunge(model)
                return model
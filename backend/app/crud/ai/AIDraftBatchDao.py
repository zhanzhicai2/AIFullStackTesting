"""
AI 生成批次 DAO

批次是一次生成任务的留痕: 用了哪个模型、输入多长、产出多少条草稿、
有哪些告警。批次内的草稿由 `AICaseDraftDao` 管。
"""
from typing import List, Optional, Tuple

from sqlalchemy import func, select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ai_draft import PityAIDraftBatch


@ModelWrapper(PityAIDraftBatch)
class AIDraftBatchDao(Mapper):
    """
    AI 生成批次

    批次本身没有业务写操作(除了落库与状态更新), 因此不做 Redis 缓存 ——
    生成页刷新后必须立刻看到最新的批次与草稿。
    """

    @classmethod
    async def insert_batch(cls, title: str, user_id: int, project_id: int = None,
                           directory_id: int = None, vendor_id: int = None, model_name: str = None,
                           test_type: str = "api", source_type: str = None, source_name: str = None,
                           source_chars: int = 0, status: int = 1, case_count: int = 0,
                           total_tokens: int = 0, warnings: str = None) -> PityAIDraftBatch:
        async with async_session() as session:
            async with session.begin():
                model = PityAIDraftBatch(title=title, user=user_id, project_id=project_id,
                                         directory_id=directory_id, vendor_id=vendor_id,
                                         model_name=model_name, test_type=test_type,
                                         source_type=source_type, source_name=source_name,
                                         source_chars=source_chars, status=status,
                                         case_count=case_count, total_tokens=total_tokens,
                                         warnings=warnings)
                session.add(model)
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def query_batch(cls, batch_id: int) -> Optional[PityAIDraftBatch]:
        async with async_session() as session:
            sql = select(PityAIDraftBatch).where(PityAIDraftBatch.id == batch_id,
                                                  PityAIDraftBatch.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def update_batch(cls, batch_id: int, user_id: int, **kwargs) -> Optional[PityAIDraftBatch]:
        """
        更新批次(状态 / 草稿数 / token / 告警)。
        只允许改白名单字段 —— 避免调用方顺手把 title 之类的也改了。
        """
        allowed = ("status", "case_count", "total_tokens", "warnings", "source_chars")
        values = {k: v for k, v in kwargs.items() if k in allowed}
        if not values:
            return await cls.query_batch(batch_id)
        async with async_session() as session:
            async with session.begin():
                sql = select(PityAIDraftBatch).where(PityAIDraftBatch.id == batch_id,
                                                      PityAIDraftBatch.deleted_at == 0)
                result = await session.execute(sql)
                model = result.scalars().first()
                if model is None:
                    raise Exception("批次不存在")
                for key, value in values.items():
                    setattr(model, key, value)
                model.update_user = user_id
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def list_batches(cls, page: int = 1, size: int = 10, project_id: int = None,
                           user_id: int = None) -> Tuple[List[PityAIDraftBatch], int]:
        """批次列表(分页) —— 按创建时间倒序"""
        async with async_session() as session:
            conditions = [PityAIDraftBatch.deleted_at == 0]
            if project_id is not None:
                conditions.append(PityAIDraftBatch.project_id == project_id)
            if user_id is not None:
                conditions.append(PityAIDraftBatch.create_user == user_id)
            count_sql = select(func.count(PityAIDraftBatch.id)).where(*conditions)
            total = (await session.execute(count_sql)).scalar() or 0
            sql = select(PityAIDraftBatch).where(*conditions).order_by(PityAIDraftBatch.id.desc())
            sql = sql.offset(max(0, (page - 1) * size)).limit(size)
            result = await session.execute(sql)
            return list(result.scalars().all()), total

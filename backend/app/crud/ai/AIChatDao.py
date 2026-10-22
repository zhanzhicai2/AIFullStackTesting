import time

from sqlalchemy import func, select, update

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ai_chat import PityChatMessage, PityChatSession


@ModelWrapper(PityChatSession)
class AIChatDao(Mapper):
    """
    AI 聊天会话与消息

    读方法一律不加 @RedisHelper.cache, 同 AIModelDao 的取舍:
    消息是高频写入且要求即时可见, 缓存只会带来脏读。

    越权隔离: 每个查询都显式带 user_id / session_id 条件。
    query_wrapper 只自动加 deleted_at == 0, 不会帮你加业务归属条件。
    """

    # ---------------- 会话 ----------------

    @classmethod
    async def insert_session(cls, user_id: int, vendor_id: int = None, model_name: str = None) -> PityChatSession:
        async with async_session() as session:
            async with session.begin():
                data = PityChatSession(user_id=user_id, vendor_id=vendor_id,
                                       model_name=model_name, user=user_id)
                session.add(data)
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def list_session(cls, user_id: int) -> list:
        """我的会话列表,按最近活跃排序,带最后一条消息预览"""
        async with async_session() as session:
            sql = select(PityChatSession).where(
                PityChatSession.user_id == user_id, PityChatSession.deleted_at == 0
            ).order_by(PityChatSession.updated_at.desc(), PityChatSession.id.desc())
            result = await session.execute(sql)
            sessions = result.scalars().all()
            if not sessions:
                return []
            ids = [s.id for s in sessions]
            # 取每个会话的最后一条消息做预览
            last_stmt = select(PityChatMessage.session_id,
                              func.max(PityChatMessage.id).label('mid')).where(
                PityChatMessage.session_id.in_(ids),
                PityChatMessage.deleted_at == 0,
            ).group_by(PityChatMessage.session_id).subquery()
            preview_stmt = select(PityChatMessage.session_id, PityChatMessage.content).join(
                last_stmt, last_stmt.c.mid == PityChatMessage.id
            )
            preview_result = await session.execute(preview_stmt)
            preview = {row[0]: row[1] for row in preview_result.all()}
            return [{"session": s, "preview": preview.get(s.id, '')} for s in sessions]

    @classmethod
    async def query_session(cls, session_id: int, user_id: int) -> PityChatSession:
        """按 id 取会话,带归属校验"""
        async with async_session() as session:
            sql = select(PityChatSession).where(
                PityChatSession.id == session_id,
                PityChatSession.user_id == user_id,      # 越权隔离
                PityChatSession.deleted_at == 0,
            )
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def update_session(cls, session_id: int, user_id: int, title: str = None,
                             vendor_id: int = None, model_name: str = None) -> None:
        async with async_session() as session:
            async with session.begin():
                result = await session.execute(select(PityChatSession).where(
                    PityChatSession.id == session_id,
                    PityChatSession.user_id == user_id,      # 越权隔离
                    PityChatSession.deleted_at == 0,
                ))
                data = result.scalars().first()
                if data is None:
                    raise Exception("会话不存在或无权访问")
                if title is not None:
                    data.title = title
                if vendor_id is not None:
                    data.vendor_id = vendor_id
                if model_name is not None:
                    data.model_name = model_name
                data.update_user = user_id

    @classmethod
    async def delete_session(cls, session_id: int, user_id: int) -> None:
        """软删会话,连带软删其下消息"""
        now = int(time.time() * 1000)
        async with async_session() as session:
            async with session.begin():
                data = await session.get(PityChatSession, session_id)
                if data is None or data.deleted_at != 0 or data.user_id != user_id:
                    raise Exception("会话不存在或无权访问")
                data.deleted_at = now
                data.update_user = user_id
                await session.execute(
                    update(PityChatMessage)
                    .where(PityChatMessage.session_id == session_id, PityChatMessage.deleted_at == 0)
                    .values(deleted_at=now, update_user=user_id)
                )

    # ---------------- 消息 ----------------

    @classmethod
    async def insert_message(cls, session_id: int, role: str, content: str, user_id: int,
                             model_name: str = None, tokens: int = 0) -> PityChatMessage:
        async with async_session() as session:
            async with session.begin():
                data = PityChatMessage(session_id=session_id, role=role, content=content,
                                       model_name=model_name, tokens=tokens, user=user_id)
                session.add(data)
                await session.flush()
                session.expunge(data)
                # 顺带把会话的 updated_at 顶上去, 列表按最近活跃排序才准
                await session.execute(
                    update(PityChatSession)
                    .where(PityChatSession.id == session_id)
                    .values(updated_at=func.now())
                )
                return data

    @classmethod
    async def list_message(cls, session_id: int) -> list:
        async with async_session() as session:
            sql = select(PityChatMessage).where(
                PityChatMessage.session_id == session_id, PityChatMessage.deleted_at == 0
            ).order_by(PityChatMessage.id)
            result = await session.execute(sql)
            return result.scalars().all()

    @classmethod
    async def has_message(cls, session_id: int) -> bool:
        async with async_session() as session:
            sql = select(PityChatMessage.id).where(
                PityChatMessage.session_id == session_id, PityChatMessage.deleted_at == 0
            ).limit(1)
            result = await session.execute(sql)
            return result.scalars().first() is not None
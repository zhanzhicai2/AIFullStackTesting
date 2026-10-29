"""
AI 模型调用流水 DAO

每次模型调用一行 —— 成本核算 / 效果评测 / 故障定位都靠它。

⚠️ 流水是**只增不改**的审计记录, 不做 Redis 缓存。
"""
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ai_draft import PityAIInvokeLog


@ModelWrapper(PityAIInvokeLog)
class AIInvokeLogDao(Mapper):
    """AI 调用流水"""

    @classmethod
    async def insert_log(cls, scene: str, user_id: int = None, vendor_id: int = None,
                         model_name: str = None, prompt_chars: int = 0, tokens: int = 0,
                         elapsed: float = 0.0, status: str = "success",
                         error_msg: str = "") -> PityAIInvokeLog:
        async with async_session() as session:
            async with session.begin():
                # create_user 是 NOT NULL —— 调用人未知时记 0(系统调用),
                # 否则这一行会插不进去, 而埋点失败是静默的(见 ai_service._write_invoke_log)
                model = PityAIInvokeLog(user=user_id if user_id is not None else 0,
                                        scene=scene, model_name=model_name,
                                        user_id=user_id, vendor_id=vendor_id,
                                        prompt_chars=prompt_chars, tokens=tokens,
                                        elapsed=elapsed, status=status, error_msg=error_msg)
                session.add(model)
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def list_logs(cls, page: int = 1, size: int = 10, scene: str = None,
                        model_name: str = None, user_id: int = None,
                        start_time: str = None, end_time: str = None
                        ) -> Tuple[List[PityAIInvokeLog], int]:
        """
        调用流水列表(分页) —— 可按场景 / 模型 / 用户 / 时间段过滤。

        时间参数是 `YYYY-MM-DD HH:MM:SS` 字符串, 解析失败就当没传。
        """
        async with async_session() as session:
            conditions = [PityAIInvokeLog.deleted_at == 0]
            if scene:
                conditions.append(PityAIInvokeLog.scene == scene)
            if model_name:
                conditions.append(PityAIInvokeLog.model_name == model_name)
            if user_id is not None:
                conditions.append(PityAIInvokeLog.user_id == user_id)
            start = _parse_time(start_time)
            if start is not None:
                conditions.append(PityAIInvokeLog.created_at >= start)
            end = _parse_time(end_time)
            if end is not None:
                conditions.append(PityAIInvokeLog.created_at <= end)
            count_sql = select(func.count(PityAIInvokeLog.id)).where(*conditions)
            total = (await session.execute(count_sql)).scalar() or 0
            sql = select(PityAIInvokeLog).where(*conditions).order_by(PityAIInvokeLog.id.desc())
            sql = sql.offset(max(0, (page - 1) * size)).limit(size)
            result = await session.execute(sql)
            return list(result.scalars().all()), total


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    """解析 `YYYY-MM-DD HH:MM:SS` —— 解析不出来返回 None(当作没传)"""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None

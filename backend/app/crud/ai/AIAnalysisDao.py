"""
AI 分析结论 DAO

**每次分析一行, 永不覆盖**(research.md §3.8):
覆盖式更新(只留最新)会让"同一失败反复出现但根因结论在变"这一重要信号消失 ——
而那恰恰是最值得看的现象。
"""
import json
from typing import List, Optional, Tuple

from sqlalchemy import func, select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ai_draft import PityAIAnalysis


@ModelWrapper(PityAIAnalysis)
class AIAnalysisDao(Mapper):
    """AI 分析结论"""

    @classmethod
    async def insert_analysis(cls, title: str, user_id: int, scene: str, result: str,
                              project_id: int = None, ref_type: str = "manual", ref_id: int = 0,
                              vendor_id: int = None, model_name: str = None,
                              tokens: int = 0) -> PityAIAnalysis:
        async with async_session() as session:
            async with session.begin():
                model = PityAIAnalysis(title=title, user=user_id, scene=scene, result=result,
                                       project_id=project_id, ref_type=ref_type, ref_id=ref_id,
                                       vendor_id=vendor_id, model_name=model_name, tokens=tokens)
                session.add(model)
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def list_analyses(cls, scene: str = None, ref_type: str = None, ref_id: int = None,
                            project_id: int = None, page: int = 1, size: int = 10
                            ) -> Tuple[List[PityAIAnalysis], int]:
        """分析结论列表(分页) —— 可按场景 / 关联对象过滤"""
        async with async_session() as session:
            conditions = [PityAIAnalysis.deleted_at == 0]
            if scene:
                conditions.append(PityAIAnalysis.scene == scene)
            if ref_type:
                conditions.append(PityAIAnalysis.ref_type == ref_type)
            if ref_id is not None:
                conditions.append(PityAIAnalysis.ref_id == ref_id)
            if project_id is not None:
                conditions.append(PityAIAnalysis.project_id == project_id)
            count_sql = select(func.count(PityAIAnalysis.id)).where(*conditions)
            total = (await session.execute(count_sql)).scalar() or 0
            sql = select(PityAIAnalysis).where(*conditions).order_by(PityAIAnalysis.id.desc())
            sql = sql.offset(max(0, (page - 1) * size)).limit(size)
            result = await session.execute(sql)
            return list(result.scalars().all()), total

    @classmethod
    async def query_analysis(cls, analysis_id: int) -> Optional[PityAIAnalysis]:
        async with async_session() as session:
            sql = select(PityAIAnalysis).where(PityAIAnalysis.id == analysis_id,
                                               PityAIAnalysis.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()


def parse_result(value) -> dict:
    """把 `result` 字段(结构化结论 JSON)解出来 —— 解析失败返回空 dict"""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

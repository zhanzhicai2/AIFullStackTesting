"""
录制导入记录 DAO —— 留痕用, 记录这次导入产出与跳过了什么
"""
from typing import List, Optional

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ui_case import PityUIImportLog


@ModelWrapper(PityUIImportLog)
class UIImportLogDao(Mapper):

    @classmethod
    async def insert_import_log(cls, user_id: int, project_id: int = None, source: str = "codegen",
                                raw_len: int = 0, parsed_lines: int = 0, skipped_lines: int = 0,
                                page_count: int = 0, element_count: int = 0, case_count: int = 0,
                                batch_id: int = None, status: int = 1, message: str = "") -> PityUIImportLog:
        model = PityUIImportLog(user=user_id, project_id=project_id, source=source, raw_len=raw_len,
                                 parsed_lines=parsed_lines, skipped_lines=skipped_lines,
                                 page_count=page_count, element_count=element_count,
                                 case_count=case_count, batch_id=batch_id, status=status,
                                 message=message)
        return await cls.insert(model=model, log=False)

    @classmethod
    async def query_import_log(cls, log_id: int) -> Optional[PityUIImportLog]:
        async with async_session() as session:
            sql = select(PityUIImportLog).where(PityUIImportLog.id == log_id,
                                                PityUIImportLog.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def list_import_logs(cls, project_id: int = None) -> List[PityUIImportLog]:
        async with async_session() as session:
            sql = select(PityUIImportLog).where(PityUIImportLog.deleted_at == 0)
            if project_id is not None:
                sql = sql.where(PityUIImportLog.project_id == project_id)
            sql = sql.order_by(PityUIImportLog.id.desc())
            result = await session.execute(sql)
            return list(result.scalars().all())

from typing import Optional

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.oss_file import PityOssFile


@ModelWrapper(PityOssFile)
class PityOssDao(Mapper):

    @classmethod
    async def query_file(cls, file_id: int) -> Optional[PityOssFile]:
        """
        按 id 取一个 OSS 文件记录 —— AI 日志分析要按 `view_url` 取已上传的日志文件。
        """
        async with async_session() as session:
            sql = select(PityOssFile).where(PityOssFile.id == file_id, PityOssFile.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

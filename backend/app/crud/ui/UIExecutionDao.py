"""
UI 执行中心 DAO

**复用既有的 `pity_report` / `pity_test_result`** —— 不新建表。
这里只做 UI 用例的筛选与汇总, 统计口径与接口用例完全一致(FR-034):
UI 用例与接口用例写进同一张结果表, 通过率按同一套公式算。
"""
from datetime import datetime
import time
from typing import List, Optional, Tuple

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import Mapper, ModelWrapper, connect
from app.models import async_session
from app.models.oss_file import PityOssFile
from app.models.report import PityReport
from app.models.result import PityTestResult
from app.models.test_case import TestCase

# UI 用例的请求类型
UI_REQUEST_TYPE = 4
# 截图在 OSS 上的路径前缀
OSS_UI_PREFIX = "ui/"


@ModelWrapper(PityTestResult)
class UIExecutionDao(Mapper):

    @classmethod
    async def ui_case_ids(cls, report_id: int) -> List[int]:
        """某个报告里 UI 用例的 case_id 列表"""
        async with async_session() as session:
            sql = select(PityTestResult.case_id).join(
                TestCase, TestCase.id == PityTestResult.case_id).where(
                PityTestResult.report_id == report_id,
                PityTestResult.deleted_at == 0,
                TestCase.request_type == UI_REQUEST_TYPE)
            result = await session.execute(sql)
            return list({row[0] for row in result.all()})

    @classmethod
    async def ui_statistic(cls, report_ids: List[int]) -> dict:
        """
        批量统计每个报告里 UI 用例的数量与通过数。

        :return: {report_id: {total, success, failed, error}}
        """
        if not report_ids:
            return dict()
        async with async_session() as session:
            sql = select(
                PityTestResult.report_id,
                func.count(PityTestResult.id),
                func.sum(func.if_(PityTestResult.status == 0, 1, 0)),
                func.sum(func.if_(PityTestResult.status == 1, 1, 0)),
                func.sum(func.if_(PityTestResult.status == 2, 1, 0)),
            ).join(TestCase, TestCase.id == PityTestResult.case_id).where(
                PityTestResult.report_id.in_(report_ids),
                PityTestResult.deleted_at == 0,
                TestCase.request_type == UI_REQUEST_TYPE,
            ).group_by(PityTestResult.report_id)
            result = await session.execute(sql)
            return {row[0]: dict(total=row[1] or 0, success=row[2] or 0,
                                 failed=row[3] or 0, error=row[4] or 0)
                    for row in result.all()}

    @classmethod
    async def list_reports(cls, page: int, size: int, start_time: datetime, end_time: datetime,
                           executor=None, deleted: bool = False) -> Tuple[List, int]:
        """
        报告列表 —— 与既有的 `TestReportDao.list_report` 同一套口径。

        :param deleted: True 时查回收站(已软删的报告)
        :return: ([(报告, 计划名)], 总数)
        """
        from app.models.test_plan import PityTestPlan
        async with async_session() as session:
            sql = select(PityReport, PityTestPlan.name).outerjoin(
                PityTestPlan, PityTestPlan.id == PityReport.plan_id).where(
                PityReport.start_at.between(start_time, end_time)).order_by(
                desc(PityReport.start_at))
            if deleted:
                sql = sql.where(PityReport.deleted_at != 0)
            else:
                sql = sql.where(PityReport.deleted_at == 0)
            if executor is not None:
                executor = executor if executor != "CPU" else 0
                sql = sql.where(PityReport.executor == executor)
            result = await session.execute(sql)
            total = result.raw.rowcount
            if total == 0:
                return [], 0
            sql = sql.offset((page - 1) * size).limit(size)
            result = await session.execute(sql)
            return list(result.all()), total

    @classmethod
    async def running_reports(cls) -> List[PityReport]:
        """正在执行的报告(status = 1)"""
        async with async_session() as session:
            sql = select(PityReport).where(PityReport.deleted_at == 0,
                                           PityReport.status == 1).order_by(desc(PityReport.start_at))
            result = await session.execute(sql)
            return list(result.scalars().all())

    @classmethod
    async def attachments(cls, report_id: int) -> List[dict]:
        """
        报告里 UI 用例的失败截图。

        截图上传 OSS 后登记在 `pity_oss_file`(路径 `ui/<case_id>/<name>`),
        这里按 case_id 反查, 不去解析日志文本。
        """
        case_ids = await cls.ui_case_ids(report_id)
        if not case_ids:
            return []
        async with async_session() as session:
            sql = select(PityOssFile).where(PityOssFile.deleted_at == 0,
                                            PityOssFile.file_path.like(f"{OSS_UI_PREFIX}%"))
            result = await session.execute(sql)
            files = list(result.scalars().all())
        ans = []
        for f in files:
            parts = f.file_path.split('/')
            if len(parts) < 3:
                continue
            try:
                case_id = int(parts[1])
            except ValueError:
                continue
            if case_id not in case_ids:
                continue
            ans.append(dict(case_id=case_id, name=parts[-1], url=f.view_url,
                            file_path=f.file_path, file_size=f.file_size))
        return ans

    @classmethod
    @connect(True)
    async def delete_report(cls, session: AsyncSession = None, report_id: int = None,
                             user_id: int = None):
        """
        删除执行历史(软删) —— 报告与它的执行结果一起删。
        重新执行会产生**新**的报告与结果, 原记录不被覆盖。
        """
        sql = select(PityReport).where(PityReport.id == report_id, PityReport.deleted_at == 0)
        result = await session.execute(sql)
        report = result.scalars().first()
        if report is None:
            raise Exception("执行记录不存在")
        # pity_report 不继承 PityBase(没有 update_user / updated_at 列), 只能自己软删
        report.deleted_at = int(time.time() * 1000)
        await session.flush()
        # 结果一并软删
        await session.execute(update(PityTestResult).where(
            PityTestResult.report_id == report_id).values(deleted_at=report.deleted_at))
        await session.flush()
        return True

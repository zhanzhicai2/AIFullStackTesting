"""
UI 执行中心

**复用既有的 `pity_report` / `pity_test_result`** —— 不新建表。
UI 用例与接口用例写进同一张结果表, 通过率按同一套公式算(FR-034 口径一致)。

「重新执行」会产生**新的**报告与结果, 原记录不被覆盖。
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.crud.ui.UIExecutionDao import UIExecutionDao
from app.handler.fatcory import PityResponse
from app.routers import Permission, get_session

router = APIRouter()


class UIRerunForm(BaseModel):
    """重新执行"""
    env: int
    case_id: List[int]
    executor: int = 0


def _report_dict(report, stat: dict, plan_name: str = None) -> dict:
    """报告 + UI 用例的统计 —— 统计口径与接口用例一致"""
    total = stat.get('total', 0)
    success = stat.get('success', 0)
    failed = stat.get('failed', 0)
    error = stat.get('error', 0)
    percent = 0
    count = success + failed + error
    if count > 0:
        percent = round(success * 100 / count, 2)
    return dict(
        id=report.id,
        executor=report.executor,
        env=report.env,
        plan_id=report.plan_id,
        plan_name=plan_name,
        status=report.status,
        mode=report.mode,
        cost=report.cost,
        start_at=report.start_at.strftime("%Y-%m-%d %H:%M:%S") if report.start_at else None,
        finished_at=report.finished_at.strftime("%Y-%m-%d %H:%M:%S") if report.finished_at else None,
        success_count=report.success_count,
        failed_count=report.failed_count,
        error_count=report.error_count,
        skipped_count=report.skipped_count,
        ui_total=total,
        ui_success=success,
        ui_failed=failed,
        ui_error=error,
        ui_percent=percent,
    )


@router.get("/execution/list", description="UI 用例执行历史")
async def list_execution(page: int = 1, size: int = 10, start_time: str = None, end_time: str = None,
                         executor: str = None, deleted: bool = False,
                         user_info=Depends(Permission())):
    try:
        end = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S") if end_time else datetime.now()
        start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S") if start_time else datetime(1970, 1, 1)
        rows, total = await UIExecutionDao.list_reports(page, size, start, end, executor, deleted)
        reports = [r[0] for r in rows]
        plan_names = {r[0].id: r[1] for r in rows}
        stats = await UIExecutionDao.ui_statistic([r.id for r in reports])
        data = [_report_dict(r, stats.get(r.id, {}), plan_names.get(r.id)) for r in reports]
        return PityResponse.success_with_size(data=data, total=total)
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/execution/running", description="正在执行的任务")
async def running_execution(user_info=Depends(Permission())):
    try:
        reports = await UIExecutionDao.running_reports()
        stats = await UIExecutionDao.ui_statistic([r.id for r in reports])
        data = [_report_dict(r, stats.get(r.id, {})) for r in reports]
        return PityResponse.success(data)
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/execution/attachments", description="报告里 UI 用例的失败截图")
async def execution_attachments(report_id: int, user_info=Depends(Permission())):
    try:
        data = await UIExecutionDao.attachments(report_id)
        return PityResponse.success(data)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/execution/rerun", description="重新执行 UI 用例")
async def rerun_execution(form: UIRerunForm, user_info=Depends(Permission())):
    try:
        from app.core.executor import Executor
        report_id = await Executor.run_multiple(user_info['id'], form.env, form.case_id, mode=0)
        return PityResponse.success(dict(report_id=report_id), msg="重新执行完成, 产生了新的执行记录")
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/execution/delete", description="删除执行历史")
async def delete_execution(report_id: int, user_info=Depends(Permission()),
                           session=Depends(get_session)):
    try:
        async with session.begin():
            await UIExecutionDao.delete_report(session=session, report_id=report_id,
                                               user_id=user_info['id'])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)

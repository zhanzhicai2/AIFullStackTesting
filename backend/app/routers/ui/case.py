"""
UI 用例路由

用例主体落在既有的 `pity_testcase`(request_type = 4), UI 专有数据落在 `pity_ui_case`。
执行结果照写既有的 `pity_test_result`, 报告链路零改造。

**校验策略(与 001 的 DSL 校验一致)**:
- 单个步骤无效 → **丢弃该步骤并告警**, 不让整条用例建不出来
- **全部步骤都无效** → 拒绝创建并回显原因
"""
import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends

from app.core.ui_executor import (run_ui_case, strip_internal, upload_failure_screenshot,
                                  validate_steps)
from app.crud.test_case.TestCaseDao import TestCaseDao
from app.crud.test_case.TestResult import TestResultDao
from app.crud.ui.UICaseDao import UICaseDao
from app.enums.RequestTypeEnum import RequestType
from app.handler.fatcory import PityResponse
from app.models.test_case import TestCase
from app.routers import Permission, get_session
from app.schema.ui_case import UICaseForm, UIRunForm
from app.utils.case_logger import CaseLog

router = APIRouter()

# pity_testcase.name 是 String(32)
MAX_CASE_NAME = 32
STATUS_LABEL = {0: "成功", 1: "失败", 2: "出错"}


def _truncate_name(name: str, warnings: list) -> str:
    """用例名超长时按既有列长度截断并回显告警(FR-035)"""
    if len(name) <= MAX_CASE_NAME:
        return name
    truncated = name[:MAX_CASE_NAME]
    warnings.append(f"用例名超过 {MAX_CASE_NAME} 个字符, 已截断为「{truncated}」")
    return truncated


async def _check_base_url(project_id: int, base_url: str):
    """
    base_url 的域名必须在项目白名单内。

    **白名单为空时不在这里拦** —— 用户可能先把用例写好再配白名单,
    执行时会被拦并给出 U1 的就地指引(见 ui_executor 的 check_url)。
    """
    from app.crud.ui.UIAllowedDomainDao import UIAllowedDomainDao
    from app.utils.ui_security import domain_allowed, url_host
    domains = await UIAllowedDomainDao.list_domain_names(project_id)
    if not domains:
        return
    host = url_host(base_url)
    if host and not domain_allowed(host, domains):
        raise Exception(f"目标域名 {host} 不在本项目允许列表内")


@router.get("/case/list", description="UI 用例列表")
async def list_case(project_id: int = None, directory_id: int = None, name: str = "",
                     user_info=Depends(Permission())):
    try:
        cases = await TestCaseDao.list_test_case(directory_id=directory_id, name=name)
        data = []
        for case in cases:
            if case.request_type != RequestType.web_ui:
                continue
            ui_case = await UICaseDao.query_ui_case(case.id)
            data.append(dict(id=case.id, name=case.name, directory_id=case.directory_id,
                             priority=case.priority, status=case.status,
                             base_url=ui_case.base_url if ui_case else case.url,
                             viewport=ui_case.viewport if ui_case else None,
                             timeout=ui_case.timeout if ui_case else None,
                             updated_at=case.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                             if case.updated_at else None))
        return PityResponse.success(data)
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/case/detail", description="UI 用例详情")
async def case_detail(id: int, user_info=Depends(Permission())):
    try:
        case = await TestCaseDao.async_query_test_case(id)
        if case is None:
            return PityResponse.failed("用例不存在")
        ui_case = await UICaseDao.query_ui_case(id)
        if ui_case is None:
            return PityResponse.failed("用例不存在或不是 UI 用例")
        steps = []
        try:
            steps = json.loads(ui_case.steps)
        except Exception:
            steps = []
        return PityResponse.success(dict(
            id=case.id, name=case.name, directory_id=case.directory_id, priority=case.priority,
            status=case.status, base_url=ui_case.base_url, viewport=ui_case.viewport,
            locale=ui_case.locale, timeout=ui_case.timeout, browser=ui_case.browser,
            screenshot=ui_case.screenshot, steps=steps))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/case/insert", description="新建 UI 用例")
async def insert_case(form: UICaseForm, user_info=Depends(Permission())):
    try:
        warnings = list()
        # 步骤校验 —— 不合规的步骤在这里就被丢掉
        steps, step_warnings = await validate_steps(form.project_id, form.steps)
        warnings.extend(step_warnings)
        if not steps:
            return PityResponse.failed("所有步骤均无效, 用例未创建", data=dict(warnings=warnings))
        name = _truncate_name(form.name, warnings)
        await _check_base_url(form.project_id, form.base_url)
        exist = await TestCaseDao.query_record(name=name, directory_id=form.directory_id)
        if exist is not None:
            return PityResponse.failed("用例已存在")
        model = TestCase(name=name, request_type=RequestType.web_ui.value, url=form.base_url,
                         directory_id=form.directory_id, status=1, priority=form.priority,
                         create_user=user_info['id'])
        model = await TestCaseDao.insert(model=model, log=True)
        await UICaseDao.insert_ui_case(case_id=model.id, base_url=form.base_url,
                                       steps=json.dumps(strip_internal(steps), ensure_ascii=False),
                                       user_id=user_info['id'], viewport=form.viewport,
                                       timeout=form.timeout, locale=form.locale)
        return PityResponse.success(dict(case_id=model.id, warnings=warnings), msg="创建成功")
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/case/update", description="修改 UI 用例")
async def update_case(form: UICaseForm, user_info=Depends(Permission())):
    try:
        if not form.id:
            return PityResponse.failed("缺少用例 id")
        warnings = list()
        case = await TestCaseDao.async_query_test_case(form.id)
        if case is None:
            return PityResponse.failed("用例不存在")
        if case.request_type != RequestType.web_ui:
            return PityResponse.failed("该用例不是 UI 用例")
        steps, step_warnings = await validate_steps(form.project_id, form.steps)
        warnings.extend(step_warnings)
        if not steps:
            return PityResponse.failed("所有步骤均无效, 用例未更新", data=dict(warnings=warnings))
        name = _truncate_name(form.name, warnings)
        await _check_base_url(form.project_id, form.base_url)
        exist = await TestCaseDao.query_record(name=name, directory_id=form.directory_id)
        if exist is not None and exist.id != form.id:
            return PityResponse.failed("用例已存在")
        # 用例主体
        await UICaseDao.update_case_info(case_id=form.id, user_id=user_info['id'],
                                         name=name, priority=form.priority, url=form.base_url)
        # UI 专有数据
        await UICaseDao.update_ui_case(case_id=form.id, user_id=user_info['id'],
                                       base_url=form.base_url,
                                       steps=json.dumps(strip_internal(steps), ensure_ascii=False),
                                       viewport=form.viewport, timeout=form.timeout,
                                       locale=form.locale)
        return PityResponse.success(dict(case_id=form.id, warnings=warnings), msg="更新成功")
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/case/delete", description="删除 UI 用例")
async def delete_case(id: int, user_info=Depends(Permission()), session=Depends(get_session)):
    try:
        await UICaseDao.delete_ui_case(id, user_info['id'])
        async with session.begin():
            await TestCaseDao.delete_records(session, user_info['id'], [id])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/case/run", description="单独执行一条 UI 用例(调试)")
async def run_case(form: UIRunForm, user_info=Depends(Permission())):
    try:
        start_at = datetime.now()
        logger = CaseLog()
        result = await run_ui_case(form.case_id, form.env, logger=logger)
        finished_at = datetime.now()
        cost = round((finished_at - start_at).total_seconds(), 2)
        status = result.get("status", 2)
        # 失败截图 -> OSS -> URL 写入 case_log
        screenshot_url = ""
        if result.get("screenshot"):
            screenshot_url = await upload_failure_screenshot(
                user_info['id'], form.case_id,
                result.get("screenshot_name") or f"ui_{form.case_id}_fail.png",
                result["screenshot"])
            if screenshot_url:
                logger.append(f"失败截图: {screenshot_url}")
        # 结果写入既有的 pity_test_result
        result_id = await TestResultDao.insert_report(
            None, form.case_id, result.get("case_name") or "", status,
            logger.join(), start_at, finished_at, result.get("url"), "",
            "", "", f"{cost}s", result.get("asserts") or "{}", "", "",
            None, "", 0, "", "", None)
        return PityResponse.success(dict(
            result_id=result_id, status=status, status_label=STATUS_LABEL.get(status, "出错"),
            cost=cost, steps=result.get("steps") or [], assertions=result.get("assertions") or [],
            asserts=result.get("asserts") or "{}", screenshot_url=screenshot_url,
            error=result.get("error"), error_reason=result.get("error_reason")),
            msg="执行完成")
    except Exception as e:
        return PityResponse.failed(e)

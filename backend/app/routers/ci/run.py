"""
CI 触发与结果查询路由 —— 前缀 `/ci`(**由 `app/routers/ci/__init__.py` 统一加**),
**`CIPermission` 鉴权**

**为什么 `POST /ci/run` 是 POST 不是 GET**(契约 §3.1):
平台既有 `/testcase/plan/execute` 用 GET 是历史习惯, 但触发会**创建一条
`pity_ci_run` 记录**(副作用), 语义上是创建资源; CI 场景下 GET 还会被中间层
缓存/预取。本端点刻意用 POST, 与既有 GET 不同路径、不冲突。

**业务码判定**(契约 §0):
- `0`   成功且测试通过
- `111` 测试未通过(或空计划)      → CI `exit 1`
- `112` 等待超时, 执行仍在继续    → 拿 run_id 轮询
- `110` 业务异常(计划不存在 / 重复触发 / 执行未能启动)
- `401`/`403` 由 `CIPermission` 与作用域判定抛出

**`wait=false` 时 `code` 恒为 0** —— 受理成功 ≠ 测试通过, 判定必须再查
`GET /ci/run/{id}`(决定 Q3)。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends

from app.core.ci_runner import CiTriggerError, trigger
from app.crud.ci.CiRunDao import CiRunDao
from app.crud.test_case.TestPlan import PityTestPlanDao
from app.enums.CiEnum import CiErrorCode, RunStatus
from app.handler.fatcory import PityResponse
from app.models.ci import PityCiRun
from app.routers import CIPermission
from app.schema.ci import CiRunForm
from config import Config

router = APIRouter()


def _report_url(run: PityCiRun) -> Optional[str]:
    """报告入口 —— 取第一条报告 id 拼既有报告页 URL(FR-013)"""
    ids = CiRunDao.decode_report_ids(run.report_ids)
    if not ids:
        return None
    return f"{Config.SERVER_REPORT}{ids[0]}"


def _scope_ok(user_info: dict, project_id: int) -> bool:
    """
    作用域判定。

    - **CI 凭据路径**(`ci_integration` 非空): 只能看/查本项目的记录(FR-005 越权边界)
    - **平台管理员 JWT 路径**(`ci_integration` 为 `None`): 不受项目限制 ——
      `/ci` 页本身已按 `authority: admin/superAdmin` 收紧, 管理员看全部项目的历史
    """
    ci = user_info.get("ci_integration")
    if not ci:
        return True
    return ci.get("project_id") == project_id


def _payload(run: PityCiRun, plan_name: str = None, summary: dict = None) -> dict:
    """按契约 §3.2 组装 `data`(触发摘要与记录同构, 字段可叠加)"""
    data = dict(
        run_id=run.id,
        status=run.status,
        integration_id=run.integration_id,
        project_id=run.project_id,
        plan_id=run.plan_id,
        plan_name=plan_name,
        env=[int(x) for x in str(run.env).split(",") if x],
        external_build_id=run.external_build_id,
        external_url=run.external_url,
        success_count=run.success_count,
        failed_count=run.failed_count,
        error_count=run.error_count,
        skipped_count=run.skipped_count,
        pass_rate=run.pass_rate,
        report_ids=CiRunDao.decode_report_ids(run.report_ids),
        report_url=_report_url(run),
        error_msg=run.error_msg,
        cost=run.cost,
        waited=bool(run.waited),
        wait_timeout=bool(summary and summary.get("wait_timeout")),
        started_at=run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else None,
        finished_at=run.finished_at.strftime("%Y-%m-%d %H:%M:%S") if run.finished_at else None,
        created_at=run.created_at.strftime("%Y-%m-%d %H:%M:%S") if run.created_at else None,
    )
    if summary:
        for key in ("run_id", "status", "plan_id", "plan_name", "env", "waited",
                    "wait_timeout"):
            if key in summary and summary[key] is not None:
                data[key] = summary[key]
    return data


def _decide(summary: dict, run: PityCiRun, plan_name: str):
    """
    由终态决定业务码与文案(契约 §0)。

    **`3`(测试未通过) 与 `5`(平台执行失败) 必须分开** —— 前者 `111` 让 CI 阻断,
    后者 `110` 是平台问题, 两者不能混(spec FR-015 / SC-006)。
    """
    status = summary.get("status", run.status)
    data = _payload(run, plan_name=plan_name, summary=summary)
    if status == RunStatus.TIMEOUT or summary.get("wait_timeout"):
        return PityResponse.failed("等待超时，执行仍在继续，请轮询 run_id",
                                   code=CiErrorCode.WAIT_TIMEOUT, data=data)
    if status == RunStatus.SUCCESS:
        return PityResponse.success(data, msg="测试通过")
    if status == RunStatus.FAILED:
        return PityResponse.failed(run.error_msg or "测试未通过",
                                   code=CiErrorCode.NOT_PASSED, data=data)
    if status == RunStatus.ERROR:
        return PityResponse.failed(run.error_msg or "平台执行失败",
                                   code=110, data=data)
    # PENDING / RUNNING —— 只可能出现在 wait=false 的受理返回
    return PityResponse.success(data, msg="已受理，正在执行")


@router.post("/run", description="触发测试计划(等待或立即返回)")
async def run_plan(form: CiRunForm, user_info=Depends(CIPermission())):
    try:
        integration = user_info.get("ci_integration")
        # 触发是外部流水线的动作 —— 平台用户看历史用 JWT, 但触发必须走 CI 凭据,
        # 否则「谁触发的」就退化成「哪个管理员点了按钮」, 记录失去溯源意义
        if not integration:
            return PityResponse.failed("触发测试计划必须使用 CI 凭据", code=401)
        # 作用域与计划校验在 ci_runner 里做(它要读计划), 这里只负责翻译异常
        summary = await trigger(
            integration=integration, plan_id=form.plan_id, env=form.env, wait=form.wait,
            timeout_sec=form.timeout_sec, external_build_id=form.external_build_id,
            external_url=form.external_url, executor_id=user_info["id"])
        run = await CiRunDao.get_run(summary["run_id"])
        if run is None:
            return PityResponse.failed("触发记录创建失败", code=110)
        plan = await PityTestPlanDao.query_test_plan(run.plan_id)
        plan_name = plan.name if plan else "(已删除)"
        if not form.wait:
            # 受理成功 —— 判定要轮询
            return PityResponse.success(_payload(run, plan_name=plan_name, summary=summary),
                                        msg="已受理，正在执行")
        return _decide(summary, run, plan_name)
    except CiTriggerError as e:
        return PityResponse.failed(str(e), code=e.code)
    except Exception as e:
        return PityResponse.failed(e)


# ⚠️ `/run/list` 必须定义在 `/run/{run_id}` **之前** —— FastAPI 按注册顺序匹配,
# 顺序颠倒会把 `list` 当成 run_id 捕获(int 转换失败 → 101), 历史列表直接打不开
@router.get("/run/list", description="触发历史(分页)")
async def list_run(project_id: int, page: int = 1, size: int = 20, plan_id: int = None,
                   status: int = None, start_time: datetime = None, end_time: datetime = None,
                   user_info=Depends(CIPermission())):
    try:
        # 项目隔离是硬边界 —— 不传 project_id 直接 101(契约 §3.3)
        if not project_id:
            return PityResponse.failed("缺少 project_id", code=101)
        if not _scope_ok(user_info, project_id):
            return PityResponse.forbidden()
        rows, total = await CiRunDao.list_runs(
            project_id=project_id, page=page, size=size, plan_id=plan_id, status=status,
            start_time=start_time, end_time=end_time)
        # 计划名: 同页通常只有几个不同计划, 本地缓存避免 N 次查询
        names = {}
        for row in rows:
            if row.plan_id not in names:
                plan = await PityTestPlanDao.query_test_plan(row.plan_id)
                names[row.plan_id] = plan.name if plan else "(已删除)"
        data = [_payload(row, plan_name=names.get(row.plan_id)) for row in rows]
        return PityResponse.success_with_size(data, total=total)
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/run/{run_id}", description="查询单次触发结果(轮询用)")
async def get_run(run_id: int, user_info=Depends(CIPermission())):
    try:
        run = await CiRunDao.get_run(run_id)
        if run is None:
            return PityResponse.failed("触发记录不存在")
        # 作用域: CI 凭据只能看本项目的记录; 平台管理员(JWT)不受此限
        if not _scope_ok(user_info, run.project_id):
            return PityResponse.forbidden()
        plan = await PityTestPlanDao.query_test_plan(run.plan_id)
        return PityResponse.success(_payload(run, plan_name=plan.name if plan else "(已删除)"))
    except Exception as e:
        return PityResponse.failed(e)

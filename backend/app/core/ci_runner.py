"""
CI 触发编排 —— 「防重 → 建记录 → 执行 → 回填」的唯一入口

**关键实现约束(research D3, 对应 spec FR-011 / FR-032)**:

等待语义用 **`asyncio.wait(tasks, timeout=)` 而不是 `asyncio.wait_for`**:
- `asyncio.wait_for` 超时会**主动 cancel 内部任务** —— 与 FR-011「超时后不得中断
  仍在进行的执行」直接冲突, 用户等了 5 分钟的结果会凭空消失
- `asyncio.wait` 超时只返回 pending, **不取消**; 而且 `asyncio.wait` **本身被取消时
  也不取消被等的任务** —— 所以调用方断连导致 handler 被取消, 执行照样继续(FR-032)
- Python 3.10+ 向 `asyncio.wait` 传裸协程是 `DeprecationWarning`(3.11 移除),
  **必须先 `ensure_future` 包成 Task**

**超时任务必须有强引用**: 事件循环只持弱引用, 不留住的话任务可能被 GC 中途回收。
`_REFS` 就是这个强引用集合, 任务结束时由 done_callback 摘除。

**防重双层判定**(research D7 / FR-017):
1. `pity_test_plan.state == 1` —— 计划正被 cron 或手工 `/plan/execute` 执行
2. `CiRunDao.find_in_flight(plan_id)` —— 已有一份 CI 执行在跑

两层都过才派发。窗口内的残余并发由 `Executor.run_test_plan` 自带的
`@lock("test_plan")` Redis 锁兜底 —— 抢不到锁时它返回 `None`, 本模块据此报 110
(不能把 `None` 当成「执行成功」)。
"""
import asyncio
from typing import Dict, Optional

from app.core.executor import Executor
from app.crud.ci.CiRunDao import CiRunDao
from app.crud.test_case.TestPlan import PityTestPlanDao
from app.enums.CiEnum import CiErrorCode, RunStatus
from app.utils.logger import Log

log = Log("CiRunner")

# 超时后仍在后台跑的 Task —— **强引用**, 见模块 docstring
_REFS: Dict[int, asyncio.Task] = {}


class CiTriggerError(Exception):
    """带业务码的触发失败 —— 路由据此返回 110/403/111 而不是笼统的 110"""

    def __init__(self, msg: str, code: int = 110):
        super().__init__(msg)
        self.code = code


async def _resolve_plan(plan_id: Optional[int], bound_plan_id: Optional[int]):
    """解析最终要跑的计划; 凭据绑定了默认计划且调用方没传时用绑定值"""
    effective = plan_id or bound_plan_id
    if not effective:
        raise CiTriggerError("未指定测试计划, 且该凭据未绑定默认计划", 110)
    plan = await PityTestPlanDao.query_test_plan(effective)
    if plan is None:
        raise CiTriggerError("测试计划不存在或已删除", 110)
    return plan


async def _execute(run_id: int, plan_id: int, executor_id: int):
    """
    执行体(前台与后台共用): 置 running → 跑 → 回填。

    **本函数不向外抛异常** —— 所有失败都落到记录的 `status=5`, 否则后台分支
    没人接异常, 记录会永久停在 running(FR-031)。
    """
    try:
        await CiRunDao.mark_running(run_id)
        report_dict = await Executor.run_test_plan(plan_id, executor_id, raise_on_error=True)
        if report_dict is None:
            # 两种可能: 计划刚被删、或 @lock 分布式锁没抢到(同 plan+executor 已有执行在跑)
            await CiRunDao.finish(run_id, RunStatus.ERROR,
                                  error_msg="执行未能启动(测试计划可能正在执行中)")
            return
        success = sum(int(d.get("success", 0)) for d in report_dict.values())
        failed = sum(int(d.get("failed", 0)) for d in report_dict.values())
        error = sum(int(d.get("error", 0)) for d in report_dict.values())
        skipped = sum(int(d.get("skip", 0)) for d in report_dict.values())
        report_ids = [d.get("report_id") for d in report_dict.values() if d.get("report_id")]
        costs = [d.get("cost") for d in report_dict.values() if d.get("cost")]
        status, err_msg = CiRunDao.decide_status(success, failed, error, skipped)
        # 逐环境判定兜底: 某个环境空计划而其它环境全过时, 汇总计数看不出问题,
        # 但 `plan_result` 是逐环境算的, 任一环境未通过即整体未通过(FR-013/018)
        if status == RunStatus.SUCCESS and report_dict and not all(
                d.get("plan_result") == "通过" for d in report_dict.values()):
            status = RunStatus.FAILED
            err_msg = "存在未通过的执行环境"
        elif not report_dict:
            status, err_msg = CiRunDao.decide_status(0, 0, 0, 0)
        await CiRunDao.finish(run_id, status, success=success, failed=failed, error=error,
                              skipped=skipped, report_ids=report_ids,
                              cost=costs[-1] if costs else None, error_msg=err_msg or None)
    except Exception as e:
        log.exception(f"CI 执行失败: run_id={run_id} plan_id={plan_id}")
        try:
            await CiRunDao.finish(run_id, RunStatus.ERROR, error_msg=str(e))
        except Exception as inner:
            # 回填也失败时至少留痕 —— 否则这条记录会永久停在 running
            log.error(f"CI 执行失败后回填也失败: run_id={run_id} ({inner})")


def _summary(run_id: int, status: int, waited: bool, wait_timeout: bool = False,
             plan_id: int = None, plan_name: str = None, env=None) -> dict:
    return dict(run_id=run_id, status=status, waited=waited, wait_timeout=wait_timeout,
                plan_id=plan_id, plan_name=plan_name, env=env)


async def trigger(integration: dict, plan_id: Optional[int] = None, env=None,
                  wait: bool = False, timeout_sec: int = 300,
                  external_build_id: str = None, external_url: str = None,
                  executor_id: int = 0) -> dict:
    """
    触发一次测试计划执行(契约 `contracts/api.md` §3.1)。

    :param integration: `CIPermission` 解析出的**凭据字典**
        `{id, project_id, plan_id, name}` —— 注意是 dict 不是 model,
        与 `user_info` 同构
    :return: 触发摘要 dict; `wait=False` 时 `status` 恒为 `PENDING`(受理成功),
             **判定必须再查 `GET /ci/run/{id}`**
    :raises CiTriggerError: 计划不存在 / 未指定计划 / 重复触发 / 越权, 带业务码
    """
    plan = await _resolve_plan(plan_id, integration.get("plan_id"))

    # 作用域(契约 §1.3 第 6 步): 凭据只能触发本项目的计划
    if plan.project_id != integration.get("project_id"):
        raise CiTriggerError("无权触发该项目的测试计划", 403)

    # 防重第一层: 计划正被 cron / 手工执行
    if getattr(plan, "state", 0) == 1:
        raise CiTriggerError("该测试计划已有执行在进行中", 110)
    # 防重第二层: 已有一份 CI 执行在跑
    if await CiRunDao.find_in_flight(plan.id) is not None:
        raise CiTriggerError("该测试计划已有执行在进行中", 110)

    env_value = env or [int(x) for x in str(plan.env).split(",") if str(x).strip()]
    run = await CiRunDao.create_run(
        integration_id=integration.get("id"), project_id=integration.get("project_id"),
        plan_id=plan.id, env=",".join(str(e) for e in env_value), user_id=executor_id,
        external_build_id=external_build_id, external_url=external_url, waited=wait)

    task = asyncio.ensure_future(_execute(run.id, plan.id, executor_id))
    # 强引用 + 完成即摘除(见模块 docstring)
    _REFS[run.id] = task
    task.add_done_callback(lambda t, rid=run.id: _REFS.pop(rid, None))

    if not wait:
        # 决定 Q3: 默认不等待, 立即返回 run_id 供轮询
        return _summary(run.id, RunStatus.PENDING, waited=False,
                        plan_id=plan.id, plan_name=plan.name, env=env_value)

    # 等待语义 —— **必须是 asyncio.wait, 不能是 asyncio.wait_for**
    await asyncio.wait({task}, timeout=timeout_sec)
    if not task.done():
        # 超时: 任务继续在后台跑(FR-011), 记录终态由回填步骤写
        return _summary(run.id, RunStatus.TIMEOUT, waited=True, wait_timeout=True,
                        plan_id=plan.id, plan_name=plan.name, env=env_value)
    if task.exception() is not None:
        # _execute 内部已兜底, 走到这里说明兜底本身也失败了
        log.error(f"CI 执行任务异常退出: run_id={run.id} ({task.exception()})")
        try:
            await CiRunDao.finish(run.id, RunStatus.ERROR, error_msg=str(task.exception()))
        except Exception:
            pass
    final = await CiRunDao.get_run(run.id)
    return _summary(run.id, final.status if final else RunStatus.ERROR, waited=True,
                    plan_id=plan.id, plan_name=plan.name, env=env_value)


def in_flight_count() -> int:
    """仍在后台跑的任务数(排障用)"""
    return len(_REFS)

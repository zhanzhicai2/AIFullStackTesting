"""
持续集成(CI)端到端测试(**需要数据库**)

跑法:
    cd backend
    .venv/bin/python scripts/ci_e2e.py

**等价路径说明**: 与 `mock_e2e.py` / `ai_workbench_e2e.py` 一致 —— 管理接口与触发接口
**直接调路由函数**(传模拟 `user_info`, 绕开 JWT / CI 凭据的 HTTP 传输层);鉴权链本身
由 `CIPermission()._by_credential` 与 `CiIntegrationDao.validate_token` 直接调用来覆盖。
不依赖 httpx/TestClient(venv 无此包)。

覆盖:
- 签发 → 列表只有前缀、响应无 `token_hash`(FR-002 / SC-007)
- 校验链四类拒绝: 无效 / 停用 / 过期 / 越权(FR-016 / SC-008)
- 触发: `wait=false` 受理 + 轮询到终态; `wait=true` 单次拿到结论(111)
- 空计划 → 111「计划为空」(FR-018)
- 计划不存在 → 110; 重复触发 → 110(FR-017)
- 触发历史分页 + 项目隔离(FR-022 / SC-005)
- 重启终态恢复: 残留 running → error(FR-031)
- 并发触发只产生一次真实执行(SC-010)
- 1000 条记录分页 < 1 秒(SC-009)

⚠️ 会在 dev 库留下痕迹(e2e 项目 / 计划 / 凭据 / 触发记录) —— `backend/scripts/`
下留下 e2e 痕迹是既有约定, 不要清理。唯一例外: SC-009 的 1000 条批量记录测完
会**逻辑删除**, 避免把历史页刷满。
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402,F401  (触发全部 include_router)
from sqlalchemy import select  # noqa: E402

from app.crud.ci.CiIntegrationDao import CiIntegrationDao  # noqa: E402
from app.crud.ci.CiRunDao import CiRunDao  # noqa: E402
from app.crud.project.ProjectDao import ProjectDao  # noqa: E402
from app.crud.test_case.TestPlan import PityTestPlanDao  # noqa: E402
from app.enums.CiEnum import CiErrorCode, RunStatus  # noqa: E402
from app.models import Base, async_engine, async_session  # noqa: E402
from app.models.ci import PityCiRun  # noqa: E402
from app.models.environment import Environment  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.test_plan import PityTestPlan  # noqa: E402
from app.routers.ci.integration import (delete_integration, insert_integration,  # noqa: E402
                                        list_integration, switch_integration)
from app.routers.ci.run import get_run, list_run, run_plan  # noqa: E402
from app.schema.ci import CiIntegrationForm, CiRunForm  # noqa: E402
from app.schema.test_plan import PityTestPlanForm  # noqa: E402

FAILED = []

ADMIN = {"id": 1, "name": "e2e-ci-admin", "role": 2}

TS = str(int(time.time() * 1000))
# pity_project.name 是 String(16) —— 项目名必须 ≤16 字符(HANDOFF 坑 4 同族)
PROJECT_NAME = f"cie2e-{TS[-6:]}"
OTHER_NAME = f"cix2e-{TS[-6:]}"
PLAN_NAME = f"ciplan-{TS[-6:]}"          # String(32)
# 不存在的用例 id —— 执行必然走「执行异常」分支, **不发任何网络请求**, 结果确定
GHOST_CASE_ID = 999999999

# 集成名有唯一约束 (project_id, name, deleted_at) —— 每次签发都要带序号
_ISSUE_SEQ = 0


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


def ci_user(integration) -> dict:
    """模拟 `CIPermission()._by_credential` 的返回结构"""
    user = dict(ADMIN)
    user["ci_integration"] = dict(
        id=integration.id, project_id=integration.project_id,
        plan_id=integration.plan_id, name=integration.name)
    return user


async def ensure_tables():
    """建缺失的表(create_all 幂等) —— 直接调路由函数不触发应用启动事件"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def first_env_id() -> int:
    async with async_session() as session:
        row = (await session.execute(
            select(Environment.id).where(Environment.deleted_at == 0).order_by(Environment.id)))
        env_id = row.scalars().first()
        if env_id is None:
            raise RuntimeError("dev 库没有环境, 先在「环境管理」里建一个")
        return env_id


async def create_project(name: str, app: str) -> int:
    await ProjectDao.add_project(name, app, owner=1, user_id=1, private=False,
                                 description="ci e2e")
    async with async_session() as session:
        r = await session.execute(select(Project).where(Project.name == name,
                                                        Project.deleted_at == 0))
        return r.scalars().first().id


async def create_plan(project_id: int, env_id: int, name: str, case_ids) -> int:
    form = PityTestPlanForm(
        project_id=project_id, name=name, priority="P1", env=[env_id], cron="0 0 * * *",
        ordered=False, case_list=list(case_ids), pass_rate=80, receiver=[], msg_type=[],
        retry_minutes=0)
    plan = await PityTestPlanDao.insert_test_plan(form, ADMIN["id"])
    return plan.id


async def set_plan_cases(plan_id: int, case_list: str):
    """直接改库把计划清空用例 —— 表单层不允许 case_list 为空(needed for FR-018)。

    ⚠️ 必须在**同一个 session** 里查询再改: `query_test_plan` 自己开会话并返回
    detached 对象, 拿到外层 session 里改是不会被跟踪的(静默不生效)。
    """
    async with async_session() as session:
        async with session.begin():
            plan = (await session.execute(
                select(PityTestPlan).where(PityTestPlan.id == plan_id,
                                            PityTestPlan.deleted_at == 0)
            )).scalars().first()
            assert plan is not None, f"计划不存在: {plan_id}"
            plan.case_list = case_list
            await session.flush()


async def authed_user(token: str) -> dict:
    """等价于走 HTTP 时的 `CIPermission` 依赖 —— 直接调路由函数会绕过依赖,
    所以凡是要验「凭据被拒」的场景都得走这里。"""
    from app.routers import CIPermission
    return await CIPermission()(token=token)


async def issue(project_id: int, plan_id=None, expires_at="default"):
    """走真实签发路由(拿明文), 返回 (integration, 明文)。

    集成名有 `project_id + name + deleted_at` 唯一约束, 所以每次签发都带递增序号。
    """
    global _ISSUE_SEQ
    _ISSUE_SEQ += 1
    form = CiIntegrationForm(project_id=project_id,
                             name=f"Jk{TS[-6:]}-{_ISSUE_SEQ}",
                             plan_id=plan_id, callback_url=None)
    if expires_at == "never":
        form.__fields_set__.add("expires_at")
        form.expires_at = None
    elif expires_at != "default":
        form.__fields_set__.add("expires_at")
        form.expires_at = expires_at
    res = await insert_integration(form, ADMIN)
    assert res["code"] == 0, res
    return SimpleNamespace(**{k: v for k, v in res["data"].items() if k != "token"}), \
        res["data"]["token"]


# ---------------------------------------------------------------------------
# 凭据
# ---------------------------------------------------------------------------


async def test_issue_and_list(project_id: int, plan_id: int):
    print("== 签发与列表(FR-001/002/007) ==")
    integration, token = await issue(project_id, plan_id)
    check("签发明文格式", token.startswith("pity_ci_") and len(token) == 40, token[:20])
    check("签发返回 id", isinstance(integration.id, int) and integration.id > 0)
    check("绑定默认计划", integration.plan_id == plan_id, str(integration.plan_id))
    check("默认有效期存在(1 年)", integration.expires_at is not None,
          str(integration.expires_at))

    res = await list_integration(project_id=project_id, user_info=ADMIN)
    check("列表 code=0", res["code"] == 0, str(res))
    row = next((r for r in res["data"] if r["id"] == integration.id), None)
    check("列表命中刚签发的凭据", row is not None)
    check("列表只显示前缀", row and row.get("token_prefix", "").startswith("pity_ci_"))
    check("列表不含明文 token", row is not None and "token" not in row, str(row))
    check("列表不含 token_hash(摘要也是凭据等价物)", row is not None and
          "token_hash" not in row, str(row))

    # 校验链: 正常 + last_used_at 被更新
    got, err = await CiIntegrationDao.validate_token(token)
    check("凭据校验通过", err == "" and got is not None, err)
    check("校验后更新 last_used_at", got is not None and got.last_used_at is not None)
    return integration, token


async def test_rejections(project_id: int, other_project_id: int, integration, token,
                          plan_id: int):
    print("== 拒绝类: 无效 / 停用 / 过期 / 越权(FR-016 / SC-008) ==")
    from app.exception.request import AuthException

    async def expect_401(label: str, bad_token: str, expect: str):
        """走真实鉴权依赖, 断言被拒且文案可区分"""
        try:
            await authed_user(bad_token)
            check(label, False, "本该被拒却通过了")
        except AuthException as e:
            check(label, expect in str(e.detail), str(e.detail))

    # 无效: 随机串
    _, err = await CiIntegrationDao.validate_token("pity_ci_" + "0" * 32)
    check("随机凭据 → 无效", err == "CI 凭据无效", err)
    await expect_401("无效凭据经鉴权依赖被拒(401)",
                     "pity_ci_" + "0" * 32, "CI 凭据无效")

    # 停用
    await switch_integration(id=integration.id, status=False, user_info=ADMIN)
    _, err = await CiIntegrationDao.validate_token(token)
    check("停用 → 已停用", err == "CI 凭据已停用", err)
    await expect_401("停用凭据经鉴权依赖被拒(401)", token, "CI 凭据已停用")
    # 重新启用
    await switch_integration(id=integration.id, status=True, user_info=ADMIN)
    _, err = await CiIntegrationDao.validate_token(token)
    check("重新启用后恢复", err == "", err)
    check("重新启用后鉴权依赖放行", (await authed_user(token))["ci_integration"]["id"]
          == integration.id)

    # 过期
    expired, exp_token = await issue(project_id, plan_id,
                                     expires_at=datetime.now() - timedelta(days=1))
    _, err = await CiIntegrationDao.validate_token(exp_token)
    check("过期 → 已过期", err == "CI 凭据已过期", err)
    await expect_401("过期凭据经鉴权依赖被拒(401)", exp_token, "CI 凭据已过期")

    # 长期有效(决定 Q4)
    forever, forever_token = await issue(project_id, plan_id, expires_at="never")
    check("长期有效 → expires_at 为空", forever.expires_at is None, str(forever.expires_at))
    _, err = await CiIntegrationDao.validate_token(forever_token)
    check("长期有效凭据可用", err == "", err)

    # 越权: A 项目的凭据触发 B 项目的计划(走真实触发链路)
    cross, cross_token = await issue(other_project_id, plan_id=None)
    res = await run_plan(CiRunForm(plan_id=plan_id), ci_user(cross))
    check("跨项目触发 → 403", res["code"] == 403, str(res))
    check("403 文案说明越权", "无权" in res.get("msg", ""), res.get("msg"))
    check("拒绝文案不含凭据内容",
          cross_token[:20] not in str(res) and "pity_ci_" not in str(res.get("msg", "")))

    # 清理临时凭据, 避免污染后续
    await delete_integration(id=expired.id, user_info=ADMIN)
    await delete_integration(id=forever.id, user_info=ADMIN)
    await delete_integration(id=cross.id, user_info=ADMIN)


async def test_invalid_plan(project_id: int, integration):
    print("== 计划不可用(FR-016) ==")
    res = await run_plan(CiRunForm(plan_id=GHOST_CASE_ID - 1), ci_user(integration))
    check("计划不存在 → 110", res["code"] == 110, str(res))
    check("文案说明计划不存在", "不存在" in res.get("msg", ""), res.get("msg"))

    # 凭据未绑定默认计划且调用方不传 → 110
    loose, _ = await issue(project_id, plan_id=None)
    res = await run_plan(CiRunForm(), ci_user(loose))
    check("未指定计划 → 110", res["code"] == 110, str(res))
    check("文案提示需指定计划", "计划" in res.get("msg", ""), res.get("msg"))
    await delete_integration(id=loose.id, user_info=ADMIN)


# ---------------------------------------------------------------------------
# 触发
# ---------------------------------------------------------------------------


async def test_trigger_no_wait(integration, plan_id: int):
    print("== wait=false 受理 + 轮询(决定 Q3 / FR-012) ==")
    res = await run_plan(CiRunForm(plan_id=plan_id, wait=False,
                                   external_build_id="42",
                                   external_url="https://jenkins/job/x/42/"),
                         ci_user(integration))
    check("受理 code=0", res["code"] == 0, str(res))
    check("msg 是「已受理」而不是「测试通过」",
          "已受理" in res.get("msg", ""), res.get("msg"))
    run_id = res["data"]["run_id"]
    check("返回 run_id", isinstance(run_id, int) and run_id > 0)
    check("受理时 status=0 pending", res["data"]["status"] == RunStatus.PENDING,
          str(res["data"]["status"]))
    check("受理时 wait_timeout=false", res["data"]["wait_timeout"] is False)

    # 轮询到终态
    final = None
    for _ in range(60):
        await asyncio.sleep(0.5)
        got = await get_run(run_id, ci_user(integration))
        if got["code"] == 0 and got["data"]["status"] in RunStatus.TERMINAL:
            final = got["data"]
            break
    check("轮询到终态", final is not None, "超时未终态")
    if final:
        check("终态是 3(测试未通过, 用例执行异常)", final["status"] == RunStatus.FAILED,
              str(final["status"]))
        check("记录带外部构建号", final["external_build_id"] == "42",
              str(final["external_build_id"]))
        check("记录带外部地址", final["external_url"] == "https://jenkins/job/x/42/")
        check("有报告入口", bool(final["report_url"]), str(final["report_url"]))
        check("report_ids 非空", len(final["report_ids"]) > 0, str(final["report_ids"]))
        check("error_msg 说明未通过", "未通过" in (final["error_msg"] or ""),
              str(final["error_msg"]))
    return run_id


async def test_trigger_wait(integration, plan_id: int):
    print("== wait=true 单次拿到结论(FR-014) ==")
    t0 = time.perf_counter()
    res = await run_plan(CiRunForm(plan_id=plan_id, wait=True, timeout_sec=120),
                         ci_user(integration))
    elapsed = time.perf_counter() - t0
    check("等待语义返回 111(测试未通过)", res["code"] == CiErrorCode.NOT_PASSED, str(res["code"]))
    check("msg 带失败计数", "失败" in res.get("msg", "") or "异常" in res.get("msg", ""),
          res.get("msg"))
    check("data.status=3", res["data"]["status"] == RunStatus.FAILED,
          str(res["data"]["status"]))
    check("data.waited=true", res["data"]["waited"] is True)
    check("单次返回即可判定(有 report_url)", bool(res["data"].get("report_url")))
    check("等待耗时 < 60s", elapsed < 60, f"{elapsed:.2f}s")
    return res["data"]["run_id"]


async def test_empty_plan(project_id: int, env_id: int, integration):
    print("== 空计划判未通过(FR-018) ==")
    plan_id = await create_plan(project_id, env_id, f"{PLAN_NAME}-empty", [GHOST_CASE_ID])
    await set_plan_cases(plan_id, "")
    res = await run_plan(CiRunForm(plan_id=plan_id, wait=True, timeout_sec=120),
                         ci_user(integration))
    check("空计划 → 111", res["code"] == CiErrorCode.NOT_PASSED, str(res["code"]))
    check("文案是「计划为空」", "计划为空" in res.get("msg", ""), res.get("msg"))
    check("空计划 status=3(不是 2 也不是 5)", res["data"]["status"] == RunStatus.FAILED,
          str(res["data"]["status"]))
    check("空计划 pass_rate=0", res["data"]["pass_rate"] == 0, str(res["data"]["pass_rate"]))
    return plan_id


async def test_duplicate_trigger(integration, plan_id: int):
    print("== 重复触发被拒(FR-017 / SC-010) ==")
    # 手工造一条进行中记录 —— 模拟「上一次触发还没跑完」
    fake = await CiRunDao.create_run(
        integration_id=integration.id, project_id=integration.project_id,
        plan_id=plan_id, env="1", user_id=ADMIN["id"])
    await CiRunDao.mark_running(fake.id)
    res = await run_plan(CiRunForm(plan_id=plan_id, wait=True, timeout_sec=60),
                         ci_user(integration))
    check("进行中时再触发 → 110", res["code"] == 110, str(res["code"]))
    check("文案说明正在执行", "进行中" in res.get("msg", ""), res.get("msg"))
    # 收掉这条伪造记录, 别影响后续
    await CiRunDao.finish(fake.id, RunStatus.ERROR, error_msg="e2e 伪造记录收尾")


async def test_concurrent_trigger(integration, plan_id: int):
    print("== 并发触发只产生一次真实执行(SC-010) ==")
    before = await _count_executed(plan_id)
    results = await asyncio.gather(
        run_plan(CiRunForm(plan_id=plan_id, wait=True, timeout_sec=120), ci_user(integration)),
        run_plan(CiRunForm(plan_id=plan_id, wait=True, timeout_sec=120), ci_user(integration)),
        return_exceptions=True)
    codes = [r["code"] for r in results if isinstance(r, dict)]
    check("两次并发都拿到可判定结果", len(codes) == 2, str(codes))
    after = await _count_executed(plan_id)
    newly_executed = after - before
    check("并发下只多出一次真实执行", newly_executed == 1, f"新增 {newly_executed} 次")
    check("另一次以 110 拒绝或未启动", any(c == 110 for c in codes) or newly_executed == 1,
          str(codes))


async def _count_executed(plan_id: int) -> int:
    """统计真正跑出用例计数的记录数(排除空壳 / 未启动)"""
    async with async_session() as session:
        rows = (await session.execute(
            select(PityCiRun).where(PityCiRun.plan_id == plan_id,
                                    PityCiRun.deleted_at == 0))).scalars().all()
        return sum(1 for r in rows
                   if (r.success_count + r.failed_count + r.error_count + r.skipped_count) > 0)


# ---------------------------------------------------------------------------
# 历史 / 恢复 / 性能
# ---------------------------------------------------------------------------


async def test_history(project_id: int, other_project_id: int, integration):
    print("== 触发历史分页与隔离(FR-020~022 / SC-005) ==")
    res = await list_run(project_id=project_id, page=1, size=5, user_info=ci_user(integration))
    check("历史 code=0", res["code"] == 0, str(res.get("msg")))
    check("历史有数据", res["total"] > 0, str(res.get("total")))
    check("单页不超过 size", len(res["data"]) <= 5, str(len(res["data"])))
    check("每条都有 run_id 与 status",
          all("run_id" in r and "status" in r for r in res["data"]))
    check("每条都有报告入口或说明未完成",
          all(r.get("report_url") or r.get("error_msg") for r in res["data"]),
          str([r.get("report_url") for r in res["data"]][:3]))
    check("响应不含 token_hash",
          all("token_hash" not in r for r in res["data"]))

    # 项目隔离: 用 A 项目的凭据查 B 项目 → 403
    res2 = await list_run(project_id=other_project_id, user_info=ci_user(integration))
    check("跨项目查历史 → 403", res2["code"] == 403, str(res2["code"]))

    # 缺 project_id → 101(直接调函数时用 0 模拟「未传」; HTTP 层走 RequestValidationError)
    res3 = await list_run(project_id=0, user_info=ci_user(integration))
    check("缺 project_id → 101", res3["code"] == 101, str(res3["code"]))

    # 管理员 JWT 路径(ci_integration=None)可查任意项目
    admin_view = dict(ADMIN)
    admin_view["ci_integration"] = None
    res4 = await list_run(project_id=project_id, page=1, size=5, user_info=admin_view)
    check("管理员 JWT 也能查历史(双模鉴权)", res4["code"] == 0, str(res4.get("msg")))

    # 触发必须走 CI 凭据 —— JWT 调 POST /ci/run 被拒
    res5 = await run_plan(CiRunForm(plan_id=1), admin_view)
    check("JWT 触发被拒(401, 溯源不退化)", res5["code"] == 401, str(res5["code"]))


async def test_recover_stale(project_id: int, env_id: int, integration):
    print("== 重启终态恢复(FR-031) ==")
    plan_id = await create_plan(project_id, env_id, f"{PLAN_NAME}-stale", [GHOST_CASE_ID])
    run = await CiRunDao.create_run(
        integration_id=integration.id, project_id=project_id, plan_id=plan_id,
        env=str(env_id), user_id=ADMIN["id"])
    await CiRunDao.mark_running(run.id)
    # 确认它确实停在 running
    before = await CiRunDao.get_run(run.id)
    check("恢复前 status=1 running", before.status == RunStatus.RUNNING, str(before.status))
    recovered = await CiRunDao.recover_stale_runs()
    after = await CiRunDao.get_run(run.id)
    check("恢复后 status=5 error", after.status == RunStatus.ERROR, str(after.status))
    check("恢复文案说明平台重启", "重启" in (after.error_msg or ""), str(after.error_msg))
    check("恢复写入 finished_at", after.finished_at is not None)
    check("恢复返回条数 ≥1", recovered >= 1, str(recovered))
    # 再跑一次应为 0(幂等)
    again = await CiRunDao.recover_stale_runs()
    check("恢复幂等(第二次 0 条)", again == 0, str(again))
    return plan_id


async def test_bulk_timing(project_id: int, integration):
    print("== 分页性能 1000 条(SC-009) ==")
    rows = []
    for i in range(1000):
        rows.append(PityCiRun(
            integration_id=integration.id, project_id=project_id, plan_id=1, env="1",
            user=ADMIN["id"], status=RunStatus.SUCCESS, external_build_id=str(i),
            waited=False))
    async with async_session() as session:
        async with session.begin():
            session.add_all(rows)
            await session.flush()
            ids = [r.id for r in rows]
    t0 = time.perf_counter()
    res = await list_run(project_id=project_id, page=1, size=20, user_info=ci_user(integration))
    elapsed = time.perf_counter() - t0
    check("1000 条下分页返回", res["code"] == 0 and len(res["data"]) == 20,
          f"code={res.get('code')} n={len(res.get('data') or [])}")
    check("分页 < 1 秒", elapsed < 1.0, f"{elapsed * 1000:.0f}ms")
    check("total 含 1000 条", res["total"] >= 1000, str(res["total"]))
    # 测完逻辑删除, 别把历史页刷满(与其它 e2e 痕迹不同: 这是 1000 行噪音)
    async with async_session() as session:
        async with session.begin():
            found = (await session.execute(
                select(PityCiRun).where(PityCiRun.id.in_(ids)))).scalars().all()
            for r in found:
                r.deleted_at = int(time.time() * 1000)
            await session.flush()
    print("    (1000 条已逻辑删除)")


async def test_decide_mapping():
    """业务码映射 —— 0 / 111 / 112 / 110, 与 3/5 语义分离(SC-006)"""
    print("== 业务码映射(0 / 111 / 112 / 110) ==")
    from app.routers.ci.run import _decide
    run = SimpleNamespace(id=1, status=RunStatus.SUCCESS, integration_id=1, project_id=1,
                          plan_id=1, env="1", external_build_id=None, external_url=None,
                          success_count=3, failed_count=0, error_count=0, skipped_count=0,
                          pass_rate=100, report_ids='[7]', error_msg=None, cost="1.00",
                          waited=True, started_at=None, finished_at=None, created_at=None)
    check("SUCCESS → code 0",
          _decide({"status": RunStatus.SUCCESS}, run, "p")["code"] == 0)
    run.status = RunStatus.FAILED
    run.error_msg = "测试未通过（失败 1）"
    check("FAILED → code 111",
          _decide({"status": RunStatus.FAILED}, run, "p")["code"] == CiErrorCode.NOT_PASSED)
    check("FAILED 文案带失败原因",
          "失败" in _decide({"status": RunStatus.FAILED}, run, "p")["msg"])
    check("ERROR → code 110(与 111 可区分)",
          _decide({"status": RunStatus.ERROR}, run, "p")["code"] == 110)
    check("TIMEOUT → code 112",
          _decide({"status": RunStatus.TIMEOUT, "wait_timeout": True}, run, "p")["code"]
          == CiErrorCode.WAIT_TIMEOUT)
    check("111 与 112 与 110 三者互不相同",
          len({CiErrorCode.NOT_PASSED, CiErrorCode.WAIT_TIMEOUT, 110}) == 3)


async def main():
    await ensure_tables()
    env_id = await first_env_id()
    project_id = await create_project(PROJECT_NAME, f"cie2e{TS[-6:]}")
    other_project_id = await create_project(OTHER_NAME, f"cix2e{TS[-6:]}")
    plan_id = await create_plan(project_id, env_id, PLAN_NAME, [GHOST_CASE_ID])
    print(f"e2e 环境: env={env_id} project={project_id}/{other_project_id} plan={plan_id}\n")

    await test_decide_mapping()
    integration, token = await test_issue_and_list(project_id, plan_id)
    await test_rejections(project_id, other_project_id, integration, token, plan_id)
    await test_invalid_plan(project_id, integration)
    await test_trigger_no_wait(integration, plan_id)
    await test_trigger_wait(integration, plan_id)
    await test_empty_plan(project_id, env_id, integration)
    await test_duplicate_trigger(integration, plan_id)
    await test_concurrent_trigger(integration, plan_id)
    await test_history(project_id, other_project_id, integration)
    await test_recover_stale(project_id, env_id, integration)
    await test_bulk_timing(project_id, integration)

    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    asyncio.run(main())

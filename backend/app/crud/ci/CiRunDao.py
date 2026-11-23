"""
CI 触发记录 DAO —— 一次外部触发的完整生命周期

**状态机**(`data-model.md` §3.1):
`0 pending → 1 running → {2 success | 3 failed | 4 timeout | 5 error}`,
其中 `4 timeout` 只在「等待超时且最终没跑完」时保留; 正常跑完会被回填成 2/3。
**记录绝不允许永久停在 0/1** —— 重启时由 `recover_stale_runs()` 收敛到 5(spec FR-031)。

**防重**(FR-017): `find_in_flight(plan_id)` 查同计划是否已有 0/1 状态的记录。
与 `pity_test_plan.state` 双层判定 —— 前者覆盖「有一份 CI 执行在跑」,
后者覆盖「计划正被 cron / 手工执行」(research D7)。

**通过判定**(FR-013 / FR-018): 与 `executor.run_multiple` 同源 ——
`total > 0 且 failed == 0 且 error == 0` 才算通过; **空计划判未通过**。
"""
import json
import re
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.enums.CiEnum import ERROR_MSG_MAX_LEN, RunStatus
from app.models import async_session
from app.models.ci import PityCiRun


@ModelWrapper(PityCiRun)
class CiRunDao(Mapper):

    # ------------------------------------------------------------------
    # 纯函数(可无 DB 单测)
    # ------------------------------------------------------------------

    @staticmethod
    def decide_status(success: int, failed: int, error: int, skipped: int) -> Tuple[int, str]:
        """
        由用例计数判定终态。

        :return: `(status, error_msg)` —— 通过时 `error_msg` 为 `""`。
        **空计划判未通过**(FR-018): 一条用例都没跑, 不得说「通过」。
        """
        total = success + failed + error + skipped
        if total == 0:
            return RunStatus.FAILED, "计划为空，无法判定"
        if failed == 0 and error == 0:
            return RunStatus.SUCCESS, ""
        parts = []
        if failed:
            parts.append(f"失败 {failed}")
        if error:
            parts.append(f"异常 {error}")
        return RunStatus.FAILED, "测试未通过（" + " / ".join(parts) + "）"

    @staticmethod
    def pass_rate(success: int, total: int) -> int:
        """通过率(整数百分比, 向下取整); 空计划保持 0"""
        if total <= 0:
            return 0
        return int(success * 100 / total)

    @staticmethod
    def encode_report_ids(report_ids) -> str:
        """多环境多条报告 id → JSON 数组字符串(列是 TEXT)"""
        return json.dumps(list(report_ids or []), ensure_ascii=False)

    @staticmethod
    def decode_report_ids(raw) -> List[int]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return [int(x) for x in data] if isinstance(data, list) else []
        except Exception:
            return []

    # `error_msg` 会进三处: pity_ci_run(库) → GET /ci/run/{id} 响应 → 触发历史 UI。
    # 单纯截断不够 —— 异常文本可能带出目标 URL 的 query(常含 token/签名)或
    # `password=` 形式的凭据片段。落库前先 scrub, 才对得起 data-model §5 的「已脱敏」。
    #
    # `(?:bearer\s+)?` 是必要的: `Authorization: Bearer <jwt>` 只吃掉 `Bearer` 的话,
    # 后面的 JWT 会原样留下 —— 那才是值本身。
    _SECRET_KV = re.compile(
        r"(?i)\b(password|passwd|pwd|token|api_key|apikey|secret|access_key|authorization)"
        r"\b\s*[=:]\s*(?:bearer\s+)?\S+")
    _URL_QUERY = re.compile(r"(https?://[^\s\"'<>]+)\?[^\s\"'<>]*")

    @staticmethod
    def clip_error(msg) -> Optional[str]:
        """脱敏 + 截断到 500(data-model.md §5) —— 防异常堆栈把 TEXT 撑爆, 也防凭据落库"""
        if msg is None:
            return None
        text = str(msg)
        # URL query 常带 token / 签名 —— 只留 scheme+host+path
        text = CiRunDao._URL_QUERY.sub(lambda m: f"{m.group(1)}?***", text)
        # `token=xxx` / `Authorization: Bearer xxx` 形式的凭据片段
        text = CiRunDao._SECRET_KV.sub(lambda m: f"{m.group(1)}=***", text)
        return text[:ERROR_MSG_MAX_LEN]

    # ------------------------------------------------------------------
    # 写入 / 回填
    # ------------------------------------------------------------------

    @classmethod
    async def create_run(cls, integration_id: int, project_id: int, plan_id: int, env: str,
                         user_id: int, external_build_id: str = None,
                         external_url: str = None, waited: bool = False) -> PityCiRun:
        model = PityCiRun(integration_id=integration_id, project_id=project_id,
                          plan_id=plan_id, env=env, user=user_id, status=RunStatus.PENDING,
                          external_build_id=external_build_id, external_url=external_url,
                          waited=waited)
        return await cls.insert(model=model, log=True)

    @classmethod
    async def mark_running(cls, run_id: int):
        await cls._update(run_id, status=RunStatus.RUNNING, started_at=datetime.now())

    @classmethod
    async def finish(cls, run_id: int, status: int, success: int = 0, failed: int = 0,
                     error: int = 0, skipped: int = 0, report_ids=None, cost: str = None,
                     error_msg: str = None, env: str = None):
        """回填终态与计数(多环境汇总后的值)"""
        total = success + failed + error + skipped
        values = dict(status=status, success_count=success, failed_count=failed,
                      error_count=error, skipped_count=skipped,
                      pass_rate=CiRunDao.pass_rate(success, total),
                      report_ids=CiRunDao.encode_report_ids(report_ids),
                      cost=cost, finished_at=datetime.now(),
                      error_msg=CiRunDao.clip_error(error_msg))
        if env is not None:
            values["env"] = env
        await cls._update(run_id, **values)

    @classmethod
    async def _update(cls, run_id: int, **values):
        async with async_session() as session:
            async with session.begin():
                sql = select(PityCiRun).where(PityCiRun.id == run_id)
                data = (await session.execute(sql)).scalars().first()
                if data is None:
                    raise Exception(f"CI 触发记录不存在: {run_id}")
                for key, value in values.items():
                    setattr(data, key, value)
                data.updated_at = datetime.now()
                await session.flush()

    @classmethod
    async def recover_stale_runs(cls) -> int:
        """
        重启后把残留的进行中记录收敛到终态(**lifespan 第 5 步**, spec FR-031)。

        单进程部署(gunicorn -w 1)下, 进程重启 = 所有在跑的执行真的消失, 没有别的
        worker 接手。标 `5 error`(平台执行失败) 而不是 `3 failed`(测试未通过) ——
        语义正确, 且与 FR-015 一致。

        :return: 收敛的条数
        """
        now = datetime.now()
        async with async_session() as session:
            async with session.begin():
                sql = select(PityCiRun).where(
                    PityCiRun.status.in_(RunStatus.IN_FLIGHT),
                    PityCiRun.deleted_at == 0)
                rows = list((await session.execute(sql)).scalars().all())
                for row in rows:
                    row.status = RunStatus.ERROR
                    row.error_msg = "平台重启导致执行中断"
                    row.finished_at = now
                    row.updated_at = now
                await session.flush()
                return len(rows)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @classmethod
    async def get_run(cls, run_id: int) -> Optional[PityCiRun]:
        async with async_session() as session:
            sql = select(PityCiRun).where(PityCiRun.id == run_id, PityCiRun.deleted_at == 0)
            return (await session.execute(sql)).scalars().first()

    @classmethod
    async def find_in_flight(cls, plan_id: int) -> Optional[PityCiRun]:
        """
        同计划是否已有 CI 执行在跑(FR-017 防重)。

        单进程 asyncio 下, 调用方必须保证「查 + 插」之间没有 `await` 切换点,
        否则存在 TOCTOU 窗口 —— 窗口内的并发由 `@lock("test_plan")` 的 Redis 锁兜底
        (抢不到锁时 `run_test_plan` 返回 `None`, `ci_runner` 据此报 110)。
        """
        async with async_session() as session:
            sql = select(PityCiRun).where(
                PityCiRun.plan_id == plan_id,
                PityCiRun.status.in_(RunStatus.IN_FLIGHT),
                PityCiRun.deleted_at == 0).order_by(PityCiRun.id.desc())
            return (await session.execute(sql)).scalars().first()

    @classmethod
    async def list_runs(cls, project_id: int, page: int = 1, size: int = 20,
                        plan_id: int = None, status: int = None,
                        start_time: datetime = None, end_time: datetime = None
                        ) -> Tuple[List[PityCiRun], int]:
        """触发历史分页 —— 走复合索引 (project_id, created_at)(SC-009)"""
        async with async_session() as session:
            sql = select(PityCiRun).where(
                PityCiRun.project_id == project_id,
                PityCiRun.deleted_at == 0)
            if plan_id is not None:
                sql = sql.where(PityCiRun.plan_id == plan_id)
            if status is not None:
                sql = sql.where(PityCiRun.status == status)
            if start_time is not None:
                sql = sql.where(PityCiRun.created_at >= start_time)
            if end_time is not None:
                sql = sql.where(PityCiRun.created_at <= end_time)
            sql = sql.order_by(PityCiRun.created_at.desc(), PityCiRun.id.desc())
            total = len((await session.execute(sql)).scalars().all())
            sql = sql.offset((page - 1) * size).limit(size)
            return list((await session.execute(sql)).scalars().all()), total

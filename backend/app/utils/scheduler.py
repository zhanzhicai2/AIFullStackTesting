from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.executor import Executor
from app.handler.fatcory import PityResponse
from app.utils.logger import Log

log = Log("Scheduler")


class Scheduler(object):
    scheduler: AsyncIOScheduler = None

    @staticmethod
    def init(scheduler):
        Scheduler.scheduler = scheduler

    @staticmethod
    def configure(**kwargs):
        Scheduler.scheduler.configure(**kwargs)

    @staticmethod
    def start():
        Scheduler.scheduler.start()

    @staticmethod
    def add_test_plan(plan_id, plan_name, cron):
        try:
            job = Scheduler.scheduler.add_job(func=Executor.run_test_plan, args=(plan_id,),
                                              name=plan_name, id=str(plan_id),
                                              trigger=CronTrigger.from_crontab(cron))
        except Exception:
            # cron 表达式非法等 —— 异常照旧抛给路由, 但先留痕, 否则排查时
            # 只知道「保存失败」, 不知道是 cron 写错了
            log.exception(f"添加测试计划任务失败: plan_id={plan_id} name={plan_name} cron={cron}")
            raise
        log.info(f"添加测试计划任务: plan_id={plan_id} name={plan_name} cron={cron}")
        return job

    @staticmethod
    def edit_test_plan(plan_id, plan_name, cron):
        """
        通过测试计划id，更新测试计划任务的cron，name等数据
        :param plan_id:
        :param plan_name:
        :param cron:
        :return:
        """
        job = Scheduler.scheduler.get_job(str(plan_id))
        if job is None:
            # 新增job
            return Scheduler.add_test_plan(plan_id, plan_name, cron)
        Scheduler.scheduler.modify_job(job_id=str(plan_id), trigger=CronTrigger.from_crontab(cron), name=plan_name)
        Scheduler.scheduler.pause_job(str(plan_id))
        Scheduler.scheduler.resume_job(str(plan_id))
        log.info(f"更新测试计划任务: plan_id={plan_id} name={plan_name} cron={cron}")

    @staticmethod
    def pause_resume_test_plan(plan_id, status):
        """
        暂停或恢复测试计划，会影响到next_run_at
        :param plan_id:
        :param status:
        :return:
        """
        if status:
            Scheduler.scheduler.resume_job(job_id=str(plan_id))
            log.info(f"恢复测试计划任务: plan_id={plan_id}")
        else:
            Scheduler.scheduler.pause_job(job_id=str(plan_id))
            log.info(f"暂停测试计划任务: plan_id={plan_id}")

    @staticmethod
    def remove(plan_id):
        """
        删除job，当删除测试计划时，调用此方法
        :param plan_id:
        :return:
        """
        Scheduler.scheduler.remove_job(str(plan_id))
        log.info(f"删除测试计划任务: plan_id={plan_id}")

    @staticmethod
    def list_test_plan(data: List):
        ans = []
        for d, follow in data:
            temp = PityResponse.model_to_dict(d)
            temp['follow'] = follow is not None
            job = Scheduler.scheduler.get_job(str(temp.get('id')))
            if job is None:
                # 说明job初始化失败了 —— 之前完全静默, 前端只看到 state=2,
                # 没人知道调度器里压根没这个 job
                log.warning(f"测试计划任务不存在(初始化失败?): plan_id={temp.get('id')} "
                            f"name={temp.get('name')}")
                temp["state"] = 2
                ans.append(temp)
                continue
            if job.next_run_time is None:
                # 说明job被暂停了
                temp["state"] = 3
            else:
                temp["next_run"] = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            ans.append(temp)
        return ans

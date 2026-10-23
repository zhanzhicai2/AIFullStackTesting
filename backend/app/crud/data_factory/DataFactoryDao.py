import json
import time
from copy import deepcopy
from datetime import datetime
from typing import List

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.enums.OperationEnum import OperationType
from app.middleware.RedisManager import RedisHelper
from app.models import async_session
from app.models.data_factory import PityDataFactory
from app.models.testcase_data import PityTestcaseData
from app.schema.data_factory import PityDataFactoryForm


@ModelWrapper(PityDataFactory)
class DataFactoryDao(Mapper):

    @classmethod
    async def list_dataset(cls, page: int = 1, size: int = 10, env: int = None, name: str = "",
                           project_id: int = None):
        """
        分页查询数据集, name 走模糊匹配
        """
        query = dict()
        if env is not None:
            query['env'] = env
        if name:
            # query_wrapper 约定: 值以 % 开头/结尾时自动转 like
            query['name'] = f"%{name}%"
        if project_id is not None:
            query['project_id'] = project_id
        return await cls.list_with_pagination(page, size, _sort=[PityDataFactory.id.desc()], **query)

    @classmethod
    async def query_dataset(cls, id: int):
        return await cls.query_record(id=id)

    @classmethod
    async def insert_dataset(cls, form: PityDataFactoryForm, user_id: int):
        async with async_session() as session:
            query = await session.execute(
                select(PityDataFactory).where(PityDataFactory.env == form.env,
                                              PityDataFactory.name == form.name,
                                              PityDataFactory.deleted_at == 0))
            if query.scalars().first() is not None:
                raise Exception(f"数据集: {form.name}在该环境下已存在")
        # 走 Mapper.insert, 自带事务/操作日志/缓存清理
        model = PityDataFactory(**form.dict(), user=user_id)
        return await cls.insert(model=model, log=True)

    @classmethod
    @RedisHelper.up_cache("dao")
    async def update_dataset(cls, form: PityDataFactoryForm, user_id: int):
        """
        编辑数据集。

        没有用 Mapper.update_record_by_id: 它的 not_null 模式会跳过空字符串,
        导致"目标表""备注"这类字段清空不掉。这里显式逐字段赋值。
        """
        fields = ('name', 'env', 'project_id', 'database_id', 'table_name',
                  'columns', 'count', 'seed', 'remark', 'status')
        async with async_session() as session:
            async with session.begin():
                query = await session.execute(
                    select(PityDataFactory).where(PityDataFactory.id == form.id,
                                                  PityDataFactory.deleted_at == 0))
                target = query.scalars().first()
                if target is None:
                    raise Exception("数据集不存在")
                # 同名校验: 改名字时不能撞上别的数据集
                if form.name and form.name != target.name:
                    duplicated = await session.execute(
                        select(PityDataFactory).where(PityDataFactory.env == form.env,
                                                      PityDataFactory.name == form.name,
                                                      PityDataFactory.id != form.id,
                                                      PityDataFactory.deleted_at == 0))
                    if duplicated.scalars().first() is not None:
                        raise Exception(f"数据集: {form.name}在该环境下已存在")
                old = deepcopy(target)
                changed = []
                for field in fields:
                    # project_id / database_id / table_name 允许置空, 其余字段以表单为准
                    value = getattr(form, field, None)
                    if getattr(target, field) != value:
                        changed.append(field)
                        setattr(target, field, value)
                target.update_user = user_id
                target.updated_at = datetime.now()
                await session.flush()
                session.expunge(target)
                await cls.insert_log(session, user_id, OperationType.UPDATE, target, old, form.id,
                                     changed=changed)
                return target

    @classmethod
    async def delete_dataset(cls, session, id: int, user_id: int):
        return await cls.delete_record_by_id(session, user_id, id, log=True)

    @classmethod
    async def bind_case(cls, env: int, case_id: int, name_prefix: str, seed: int, rows: List[dict],
                        user_id: int, replace: bool = True):
        """
        把生成的数据物化成用例测试数据, 接入平台已有的数据驱动机制。

        平台 Executor.run_single 会按 (env, case_id) 取所有 pity_testcase_data,
        把每条的 json_data 当作请求变量注入, 并发跑 N 次 -> N 条测试结果。
        这里不改动 pity_testcase_data 表结构, 只负责批量写入。

        name_prefix 形如 "数据工厂-12"(含数据集id), 用于整批清理;
        单条记录名为 "{name_prefix}-{seed}-{序号}", 换 seed 重绑不会撞名。
        """
        async with async_session() as session:
            async with session.begin():
                if replace:
                    # 先软删同前缀的旧数据, 避免重复绑定时数据翻倍
                    old = await session.execute(
                        select(PityTestcaseData).where(PityTestcaseData.env == env,
                                                      PityTestcaseData.case_id == case_id,
                                                      PityTestcaseData.name.like(f"{name_prefix}%"),
                                                      PityTestcaseData.deleted_at == 0))
                    for item in old.scalars().all():
                        item.deleted_at = int(time.time() * 1000)
                        item.update_user = user_id
                records = []
                for index, row in enumerate(rows):
                    name = f"{name_prefix}-{seed}-{index + 1}"
                    record = PityTestcaseData(env=env, case_id=case_id, name=name,
                                              json_data=json.dumps(row, ensure_ascii=False),
                                              user_id=user_id)
                    session.add(record)
                    records.append(record)
                await session.flush()
                for record in records:
                    session.expunge(record)
                if records:
                    await cls.insert_log(session, user_id, OperationType.EXECUTE, records[0], key=case_id)
                return len(records)

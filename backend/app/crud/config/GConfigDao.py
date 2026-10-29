from typing import List

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.middleware.RedisManager import RedisHelper
from app.models import async_session
from app.models.gconfig import GConfig
from app.schema.gconfig import GConfigForm


@ModelWrapper(GConfig)
class GConfigDao(Mapper):

    @classmethod
    @RedisHelper.up_cache("dao")
    async def insert_gconfig(cls, form: GConfigForm, user_id: int) -> None:
        try:
            async with async_session() as session:
                async with session.begin():
                    query = await session.execute(
                        select(GConfig).where(GConfig.env == form.env, GConfig.key == form.key,
                                              GConfig.deleted_at == 0))
                    data = query.scalars().first()
                    if data is not None:
                        raise Exception(f"变量: {data.key}已存在")
                    config = GConfig(**form.dict(), user=user_id)
                    session.add(config)
        except Exception as e:
            cls.__log__.error(f"新增变量: {data.key}失败, {e}")
            raise Exception(f"新增变量: {data.key}失败")

    @staticmethod
    @RedisHelper.cache("dao", 1800, True)
    async def async_get_gconfig_by_key(key: str, env: int) -> GConfig:
        try:
            filters = [GConfig.key == key, GConfig.deleted_at == 0, GConfig.enable == True, GConfig.env == env]
            async with async_session() as session:
                sql = select(GConfig).where(*filters)
                result = await session.execute(sql)
                return result.scalars().first()
        except Exception as e:
            raise Exception(f"查询全局变量失败: {str(e)}")

    @staticmethod
    async def list_gconfig(env: int) -> List[GConfig]:
        """
        get available gconfig
        """
        try:
            filters = [GConfig.deleted_at == 0, GConfig.enable == True, GConfig.env == env]
            async with async_session() as session:
                sql = select(GConfig).where(*filters)
                result = await session.execute(sql)
                return result.scalars().all()
        except Exception as e:
            raise Exception(f"查询全局变量失败: {str(e)}")

    @staticmethod
    async def list_all_keys() -> List[str]:
        """
        所有**启用中**的全局变量名(跨环境)。

        AI 工作台的规则 8 用它做豁免: 断言 `actually` 引用了全局变量时,
        不该判成"取值不可得"(契约 dsl.md §5 的说明)。

        跨环境取并集是**故意**的 —— 豁免宁可放宽(少拦一条合法断言),
        也不能收紧(误删一条合法断言)。执行时到底能不能取到, 由环境决定。
        """
        try:
            async with async_session() as session:
                sql = select(GConfig.key).where(GConfig.deleted_at == 0, GConfig.enable == True)
                result = await session.execute(sql)
                return [key for key in result.scalars().all() if key]
        except Exception as e:
            raise Exception(f"查询全局变量失败: {str(e)}")

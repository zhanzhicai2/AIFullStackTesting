"""
UI 执行节点 DAO

v1 只有内置的本地节点 —— 平台启动时注册一个 `local` 节点。
分布式节点是 v2, 但表与接口形状先定好(data-model.md §2.4)。
"""
from typing import List, Optional

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ui_case import PityUINode


@ModelWrapper(PityUINode)
class UINodeDao(Mapper):

    @classmethod
    async def list_nodes(cls) -> List[PityUINode]:
        async with async_session() as session:
            sql = select(PityUINode).where(PityUINode.deleted_at == 0).order_by(PityUINode.id.asc())
            result = await session.execute(sql)
            return list(result.scalars().all())

    @classmethod
    async def query_node(cls, node_id: int) -> Optional[PityUINode]:
        async with async_session() as session:
            sql = select(PityUINode).where(PityUINode.id == node_id, PityUINode.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def query_local_node(cls) -> Optional[PityUINode]:
        """内置本地节点 —— 名字固定, 重复注册时复用"""
        async with async_session() as session:
            sql = select(PityUINode).where(PityUINode.node_type == "local",
                                           PityUINode.name == "内置本地节点",
                                           PityUINode.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def register_node(cls, name: str, user_id: int, node_type: str = "local",
                            browser: str = "chromium", headless: bool = True,
                            max_concurrency: int = 2, version: str = None) -> PityUINode:
        """自注册 —— 已存在同名同类型的节点则复用并刷新状态"""
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUINode).where(PityUINode.node_type == node_type,
                                               PityUINode.name == name,
                                               PityUINode.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    data = PityUINode(name=name, user=user_id, node_type=node_type,
                                      browser=browser, headless=headless,
                                      max_concurrency=max_concurrency, version=version)
                    session.add(data)
                else:
                    data.status = 1
                    data.browser = browser
                    data.headless = headless
                    data.max_concurrency = max_concurrency
                    data.version = version
                    data.update_user = user_id
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def delete_node(cls, node_id: int, user_id: int):
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUINode).where(PityUINode.id == node_id, PityUINode.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("节点不存在")
                cls.delete_model(data, user_id)
                await session.flush()
                session.expunge(data)
                return True

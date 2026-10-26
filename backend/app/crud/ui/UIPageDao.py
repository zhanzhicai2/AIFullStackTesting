"""
UI 页面树 DAO

页面是元素引用的键(「页面名.元素名」的前半段), 同一项目下构成一棵树。
删除页面**不级联删除元素** —— 元素可能仍被其他页面引用或已写进用例步骤,
删除页面时元素转为停用并提示用户处理引用(见 data-model.md §8)。
"""
from typing import List, Optional

from sqlalchemy import func, select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ui_case import PityUIElement, PityUIPage


@ModelWrapper(PityUIPage)
class UIPageDao(Mapper):

    @classmethod
    async def list_pages(cls, project_id: int) -> List[PityUIPage]:
        """列出项目下的所有页面(不含软删)"""
        async with async_session() as session:
            sql = select(PityUIPage).where(PityUIPage.project_id == project_id,
                                           PityUIPage.deleted_at == 0).order_by(PityUIPage.id.asc())
            result = await session.execute(sql)
            return list(result.scalars().all())

    @classmethod
    async def query_page(cls, page_id: int) -> Optional[PityUIPage]:
        async with async_session() as session:
            sql = select(PityUIPage).where(PityUIPage.id == page_id, PityUIPage.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def query_page_by_name(cls, project_id: int, name: str, parent: Optional[int] = None
                                  ) -> Optional[PityUIPage]:
        """按「项目 + 名称 + 层级」查页面 —— 建页面/录制导入时的去重依据"""
        async with async_session() as session:
            sql = select(PityUIPage).where(PityUIPage.project_id == project_id,
                                           PityUIPage.name == name,
                                           PityUIPage.deleted_at == 0)
            if parent is None:
                sql = sql.where(PityUIPage.parent.is_(None))
            else:
                sql = sql.where(PityUIPage.parent == parent)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def list_page_tree(cls, project_id: int) -> List[dict]:
        """页面树, 每个节点带 element_count(该页面下的启用元素数)"""
        pages = await cls.list_pages(project_id)
        async with async_session() as session:
            sql = select(PityUIElement.page_id, func.count(PityUIElement.id)).where(
                PityUIElement.project_id == project_id,
                PityUIElement.deleted_at == 0,
                PityUIElement.status == 1,
            ).group_by(PityUIElement.page_id)
            result = await session.execute(sql)
            count_map = {row[0]: row[1] for row in result.all()}
        nodes = dict()
        for p in pages:
            nodes[p.id] = {
                "id": p.id,
                "project_id": p.project_id,
                "name": p.name,
                "url": p.url,
                "parent": p.parent,
                "description": p.description,
                "element_count": count_map.get(p.id, 0),
                "children": [],
            }
        roots = list()
        for p in pages:
            node = nodes[p.id]
            parent = nodes.get(p.parent) if p.parent else None
            if parent is None:
                roots.append(node)
            else:
                parent["children"].append(node)
        return roots

    @classmethod
    async def check_parent(cls, project_id: int, parent: Optional[int], self_id: Optional[int] = None
                           ) -> Optional[str]:
        """
        校验上级页面: 必须同项目, 且不得成环。
        :return: None 表示合法, 否则返回错误原因
        """
        if parent is None:
            return None
        if self_id is not None and parent == self_id:
            return "上级页面不能是自己"
        async with async_session() as session:
            sql = select(PityUIPage).where(PityUIPage.id == parent, PityUIPage.deleted_at == 0)
            result = await session.execute(sql)
            target = result.scalars().first()
            if target is None:
                return "上级页面不存在"
            if target.project_id != project_id:
                return "上级页面必须属于同一个项目"
            # 向上回溯, 看是否绕回自己
            current = target
            visited = set()
            while current is not None:
                if current.id in visited:
                    return "上级页面存在环"
                visited.add(current.id)
                if self_id is not None and current.id == self_id:
                    return "上级页面存在环"
                if current.parent is None:
                    break
                sql = select(PityUIPage).where(PityUIPage.id == current.parent, PityUIPage.deleted_at == 0)
                result = await session.execute(sql)
                current = result.scalars().first()
        return None

    @classmethod
    async def insert_page(cls, name: str, project_id: int, user_id: int, url: str = None,
                          parent: Optional[int] = None, description: str = "") -> PityUIPage:
        exist = await cls.query_page_by_name(project_id, name, parent)
        if exist is not None:
            raise Exception(f"同级下已存在名为「{name}」的页面")
        err = await cls.check_parent(project_id, parent)
        if err:
            raise Exception(err)
        model = PityUIPage(name=name, user=user_id, project_id=project_id,
                           url=url, parent=parent, description=description)
        return await cls.insert(model=model, log=True)

    @classmethod
    async def update_page(cls, page_id: int, project_id: int, user_id: int, name: str = None,
                          url: str = None, parent: Optional[int] = None,
                          description: str = None) -> PityUIPage:
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUIPage).where(PityUIPage.id == page_id, PityUIPage.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("页面不存在")
                if data.project_id != project_id:
                    raise Exception("页面不属于当前项目")
                if name is not None and name != data.name:
                    exist = await cls.query_page_by_name(project_id, name, data.parent)
                    if exist is not None and exist.id != page_id:
                        raise Exception(f"同级下已存在名为「{name}」的页面")
                    data.name = name
                if url is not None:
                    data.url = url
                if description is not None:
                    data.description = description
                if parent != data.parent:
                    err = await cls.check_parent(project_id, parent, self_id=page_id)
                    if err:
                        raise Exception(err)
                    data.parent = parent
                data.updated_at = data.updated_at
                data.update_user = user_id
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def delete_page(cls, page_id: int, user_id: int):
        """
        删除页面(软删), **不级联删除元素** —— 元素转为停用并把名称返回给前端提示。
        :return: (被停用的元素数量, 元素名称列表)
        """
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUIPage).where(PityUIPage.id == page_id, PityUIPage.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("页面不存在")
                cls.delete_model(data, user_id)
                await session.flush()
                session.expunge(data)
                # 元素转停用 —— 不删, 引用它的用例仍需保留步骤
                sql = select(PityUIElement).where(PityUIElement.page_id == page_id,
                                                  PityUIElement.deleted_at == 0)
                result = await session.execute(sql)
                elements = list(result.scalars().all())
                names = []
                for e in elements:
                    if e.status != 0:
                        e.status = 0
                        e.update_user = user_id
                    names.append(e.name)
                await session.flush()
                return len(elements), names

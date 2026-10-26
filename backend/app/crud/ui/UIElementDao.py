"""
UI 元素库 DAO

元素 = 一条定位策略。去重规则: 同项目同页面同 strategy 同 locator 同 name_attr 即为同一元素
(data-model.md §2.2 的唯一约束)。注意 name_attr 可空时 MySQL 的唯一约束对 NULL 失效,
所以去重在这里显式做。

元素引用的键是「页面名.元素名」, 解析见 resolve_reference()。
**已停用的元素与不存在的元素同等处理** —— 引用它们一律判为无效。
"""
from typing import List, Optional, Tuple

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ui_case import PityUIElement, PityUIPage


@ModelWrapper(PityUIElement)
class UIElementDao(Mapper):

    @classmethod
    async def list_elements(cls, project_id: int = None, page_id: int = None,
                            status: int = None) -> List[PityUIElement]:
        async with async_session() as session:
            sql = select(PityUIElement).where(PityUIElement.deleted_at == 0)
            if project_id is not None:
                sql = sql.where(PityUIElement.project_id == project_id)
            if page_id is not None:
                sql = sql.where(PityUIElement.page_id == page_id)
            if status is not None:
                sql = sql.where(PityUIElement.status == status)
            sql = sql.order_by(PityUIElement.id.asc())
            result = await session.execute(sql)
            return list(result.scalars().all())

    @classmethod
    async def query_element(cls, element_id: int) -> Optional[PityUIElement]:
        async with async_session() as session:
            sql = select(PityUIElement).where(PityUIElement.id == element_id,
                                              PityUIElement.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def query_element_by_locator(cls, project_id: int, page_id: int, strategy: str,
                                        locator: str, name_attr: str = None
                                        ) -> Optional[PityUIElement]:
        """按去重键查元素 —— 同页面同策略同定位值同 name_attr 即为同一元素"""
        async with async_session() as session:
            sql = select(PityUIElement).where(PityUIElement.project_id == project_id,
                                              PityUIElement.page_id == page_id,
                                              PityUIElement.strategy == strategy,
                                              PityUIElement.locator == locator,
                                              PityUIElement.deleted_at == 0)
            if name_attr is None:
                sql = sql.where(PityUIElement.name_attr.is_(None))
            else:
                sql = sql.where(PityUIElement.name_attr == name_attr)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def insert_element(cls, name: str, strategy: str, locator: str, project_id: int, page_id: int,
                             user_id: int, name_attr: str = None, description: str = "",
                             status: int = 1) -> Tuple[PityUIElement, bool]:
        """
        新建元素(幂等): 已存在同去重键的元素则直接复用。
        :return: (元素, 是否命中去重)
        """
        exist = await cls.query_element_by_locator(project_id, page_id, strategy, locator, name_attr)
        if exist is not None:
            return exist, True
        model = PityUIElement(name=name, strategy=strategy, locator=locator, user=user_id,
                              project_id=project_id, page_id=page_id, name_attr=name_attr,
                              description=description, status=status)
        result = await cls.insert(model=model, log=True)
        return result, False

    @classmethod
    async def update_element(cls, element_id: int, project_id: int, user_id: int, name: str = None,
                              strategy: str = None, locator: str = None, name_attr: str = None,
                              description: str = None, page_id: int = None) -> PityUIElement:
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUIElement).where(PityUIElement.id == element_id,
                                                  PityUIElement.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("元素不存在")
                if data.project_id != project_id:
                    raise Exception("元素不属于当前项目")
                new_strategy = strategy if strategy is not None else data.strategy
                new_locator = locator if locator is not None else data.locator
                new_name_attr = name_attr if name_attr is not None else data.name_attr
                new_page_id = page_id if page_id is not None else data.page_id
                exist = await cls.query_element_by_locator(project_id, new_page_id, new_strategy,
                                                            new_locator, new_name_attr)
                if exist is not None and exist.id != element_id:
                    raise Exception("已存在相同的定位策略与定位值")
                if name is not None:
                    data.name = name
                if strategy is not None:
                    data.strategy = strategy
                if locator is not None:
                    data.locator = locator
                if name_attr is not None:
                    data.name_attr = name_attr
                if description is not None:
                    data.description = description
                if page_id is not None:
                    data.page_id = page_id
                data.update_user = user_id
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def delete_element(cls, element_id: int, project_id: int, user_id: int):
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUIElement).where(PityUIElement.id == element_id,
                                                  PityUIElement.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("元素不存在")
                if data.project_id != project_id:
                    raise Exception("元素不属于当前项目")
                cls.delete_model(data, user_id)
                await session.flush()
                session.expunge(data)
                return True

    @classmethod
    async def update_status(cls, element_id: int, project_id: int, user_id: int, status: int
                             ) -> PityUIElement:
        """启用 / 停用元素。停用不删除 —— 引用它的用例保留步骤, 执行时该步判失败"""
        if status not in (0, 1):
            raise Exception("元素状态只能是 0(停用) 或 1(启用)")
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUIElement).where(PityUIElement.id == element_id,
                                                  PityUIElement.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("元素不存在")
                if data.project_id != project_id:
                    raise Exception("元素不属于当前项目")
                data.status = status
                data.update_user = user_id
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def resolve_reference(cls, project_id: int, reference: str) -> Tuple[Optional[PityUIElement], str]:
        """
        解析元素引用「页面名.元素名」。

        规则(contracts/steps.md §4.1):
        - 在**当前项目**下找到名称匹配的页面
        - 该页面下名称匹配且 **status = 1(启用)** 的元素
        - 找不到页面 / 找不到元素 / 元素已停用 —— 一律视为**无效引用**

        :return: (元素, 错误原因); 元素为 None 时错误原因非空
        """
        if not reference or "." not in reference:
            return None, f"元素引用格式应为「页面名.元素名」, 当前为「{reference}」"
        async with async_session() as session:
            sql = select(PityUIPage).where(PityUIPage.project_id == project_id,
                                           PityUIPage.deleted_at == 0)
            result = await session.execute(sql)
            pages = list(result.scalars().all())
        # 页面名本身可能含「.」, 所以逐个页面做前缀匹配, 而不是简单 split
        for page in pages:
            prefix = f"{page.name}."
            if not reference.startswith(prefix):
                continue
            element_name = reference[len(prefix):]
            if not element_name:
                continue
            async with async_session() as session:
                sql = select(PityUIElement).where(PityUIElement.project_id == project_id,
                                                  PityUIElement.page_id == page.id,
                                                  PityUIElement.name == element_name,
                                                  PityUIElement.deleted_at == 0)
                result = await session.execute(sql)
                element = result.scalars().first()
            if element is None:
                return None, f"引用的元素「{reference}」不存在"
            if element.status != 1:
                return None, f"引用的元素「{reference}」已停用"
            return element, ""
        return None, f"引用的元素「{reference}」不存在或已停用"

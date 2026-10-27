"""
UI 用例 DAO

用例主体在既有的 `pity_testcase`(request_type = 4), 这里只存 UI 专有数据:
起始地址、视口、单步超时与步骤 DSL。
"""
import json
from typing import Optional

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ui_case import PityUICase


@ModelWrapper(PityUICase)
class UICaseDao(Mapper):

    @classmethod
    async def query_ui_case(cls, case_id: int) -> Optional[PityUICase]:
        async with async_session() as session:
            sql = select(PityUICase).where(PityUICase.case_id == case_id, PityUICase.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def insert_ui_case(cls, case_id: int, base_url: str, steps: str, user_id: int,
                             viewport: str = "1280x720", browser: str = "chromium",
                             timeout: int = 30, screenshot: bool = True,
                             locale: str = "en-US") -> PityUICase:
        exist = await cls.query_ui_case(case_id)
        if exist is not None:
            raise Exception("该用例已存在 UI 配置")
        model = PityUICase(case_id=case_id, base_url=base_url, steps=steps, user=user_id,
                           viewport=viewport, browser=browser, timeout=timeout,
                           screenshot=screenshot, locale=locale)
        return await cls.insert(model=model, log=True)

    @classmethod
    async def update_ui_case(cls, case_id: int, user_id: int, base_url: str = None,
                             steps: str = None, viewport: str = None, browser: str = None,
                             timeout: int = None, screenshot: bool = None,
                             locale: str = None) -> PityUICase:
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUICase).where(PityUICase.case_id == case_id, PityUICase.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("UI 用例配置不存在")
                if base_url is not None:
                    data.base_url = base_url
                if steps is not None:
                    data.steps = steps
                if viewport is not None:
                    data.viewport = viewport
                if locale is not None:
                    data.locale = locale
                if browser is not None:
                    data.browser = browser
                if timeout is not None:
                    data.timeout = timeout
                if screenshot is not None:
                    data.screenshot = screenshot
                data.update_user = user_id
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def delete_ui_case(cls, case_id: int, user_id: int):
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUICase).where(PityUICase.case_id == case_id, PityUICase.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    return False
                cls.delete_model(data, user_id)
                await session.flush()
                session.expunge(data)
                return True

    @classmethod
    async def load_steps(cls, case_id: int) -> list:
        """取出步骤 DSL 数组(存的是 JSON 字符串)"""
        data = await cls.query_ui_case(case_id)
        if data is None:
            return []
        try:
            steps = json.loads(data.steps)
        except Exception:
            return []
        return steps if isinstance(steps, list) else []

    @classmethod
    async def query_project_id(cls, case_id: int) -> Optional[int]:
        """
        用例所属项目 —— `pity_testcase` 本身没有 project_id,
        通过用例所在目录(`pity_testcase_directory`)拿到项目。
        """
        from app.models.test_case import TestCase
        from app.models.testcase_directory import PityTestcaseDirectory
        async with async_session() as session:
            sql = select(PityTestcaseDirectory.project_id).select_from(
                TestCase).outerjoin(PityTestcaseDirectory,
                                    PityTestcaseDirectory.id == TestCase.directory_id).where(
                TestCase.id == case_id, TestCase.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def update_case_info(cls, case_id: int, user_id: int, name: str = None,
                               priority: str = None, url: str = None) -> None:
        """更新 `pity_testcase` 上的 UI 用例主体字段(名称 / 优先级 / 地址)"""
        from app.models.test_case import TestCase
        async with async_session() as session:
            async with session.begin():
                sql = select(TestCase).where(TestCase.id == case_id, TestCase.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("用例不存在")
                if name is not None:
                    data.name = name
                if priority is not None:
                    data.priority = priority
                if url is not None:
                    data.url = url
                data.update_user = user_id
                await session.flush()

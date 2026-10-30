"""
Mock 规则 DAO

规则按 `project_id` 隔离 —— 所有查询/写入都带项目维度, 跨项目操作一律拒绝
(「元素不属于当前项目」同款语义, 见 UIElementDao)。

**不变量(data-model.md §2.2)**: `path_type` 必须与 `path` 内容一致 —— 本 DAO 在
insert / update 时统一用 `mock_engine.derive_path_type()` 推导并回填, 防止手工
写库造成漂移。

**查重提示(FR-007)**: 同项目同方法同**精确**路径已存在规则时, insert 返回
`(rule, warn_msg)`, warn_msg 非空给前端就地提示, 不阻断创建(靠优先级区分返回)。
"""
from typing import List, Optional, Tuple

from sqlalchemy import select

from app.core.mock_engine import derive_path_type
from app.crud import Mapper, ModelWrapper
from app.crud.project.ProjectDao import ProjectDao
from app.enums.MockEnum import PATH_TYPE_EXACT
from app.models import async_session
from app.models.mock import PityMockRule
from app.models.project import Project


@ModelWrapper(PityMockRule)
class MockRuleDao(Mapper):

    @classmethod
    async def list_rules(cls, project_id: int, method: str = None, path: str = None,
                         status: int = None, page: int = 1, size: int = 20
                         ) -> Tuple[List[PityMockRule], int]:
        """规则列表(分页 + 筛选): 只返回该项目的规则"""
        async with async_session() as session:
            sql = select(PityMockRule).where(
                PityMockRule.project_id == project_id,
                PityMockRule.deleted_at == 0,
            )
            if method:
                sql = sql.where(PityMockRule.method == method)
            if path:
                sql = sql.where(PityMockRule.path.like(f"%{path}%"))
            if status is not None:
                sql = sql.where(PityMockRule.status == status)
            sql = sql.order_by(PityMockRule.id.desc())
            total_sql = sql
            total = len((await session.execute(total_sql)).scalars().all())
            sql = sql.offset((page - 1) * size).limit(size)
            result = await session.execute(sql)
            return list(result.scalars().all()), total

    @classmethod
    async def query_rule(cls, rule_id: int, project_id: int) -> Optional[PityMockRule]:
        """按 id + 项目查规则 —— 跨项目视为不存在"""
        async with async_session() as session:
            sql = select(PityMockRule).where(
                PityMockRule.id == rule_id,
                PityMockRule.project_id == project_id,
                PityMockRule.deleted_at == 0,
            )
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def find_exact_rule(cls, project_id: int, method: str, path: str
                              ) -> Optional[PityMockRule]:
        """同项目同方法同精确路径的既有规则(FR-007 查重提示用)"""
        async with async_session() as session:
            sql = select(PityMockRule).where(
                PityMockRule.project_id == project_id,
                PityMockRule.method == method,
                PityMockRule.path == path,
                PityMockRule.path_type == PATH_TYPE_EXACT,
                PityMockRule.deleted_at == 0,
            )
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def insert_rule(cls, name: str, method: str, path: str, user_id: int, project_id: int,
                          priority: int = 0, status_code: int = 200, response_headers: str = None,
                          response_body: str = None, delay: int = 0, status: int = 1,
                          remark: str = "") -> Tuple[PityMockRule, str]:
        """
        新建规则。同项目同方法同精确路径已存在时返回 warning 文案(不阻断)。
        :return: (规则, warning 文案)
        """
        warn = ""
        exist = await cls.find_exact_rule(project_id, method, path)
        if exist is not None:
            warn = "已存在相同方法+路径的规则, 注意优先级"
        model = PityMockRule(name=name, method=method, path=path, user=user_id,
                             project_id=project_id, priority=priority, status_code=status_code,
                             response_headers=response_headers, response_body=response_body,
                             delay=delay, status=status, remark=remark)
        # 不变量: path_type 由 path 推导并固化
        model.path_type = derive_path_type(path)
        result = await cls.insert(model=model, log=True)
        return result, warn

    @classmethod
    async def update_rule(cls, rule_id: int, project_id: int, user_id: int, name: str = None,
                          method: str = None, path: str = None, priority: int = None,
                          status_code: int = None, response_headers: str = None,
                          response_body: str = None, delay: int = None, status: int = None,
                          remark: str = None) -> PityMockRule:
        """更新规则 —— 重新推导 path_type; 校验项目归属"""
        async with async_session() as session:
            async with session.begin():
                sql = select(PityMockRule).where(
                    PityMockRule.id == rule_id, PityMockRule.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("规则不存在")
                if data.project_id != project_id:
                    raise Exception("规则不属于当前项目")
                if path is not None:
                    data.path = path
                    # 不变量: 路径变了, path_type 必须重推导
                    data.path_type = derive_path_type(path)
                if name is not None:
                    data.name = name
                if method is not None:
                    data.method = method
                if priority is not None:
                    data.priority = priority
                if status_code is not None:
                    data.status_code = status_code
                if response_headers is not None:
                    data.response_headers = response_headers
                if response_body is not None:
                    data.response_body = response_body
                if delay is not None:
                    data.delay = delay
                if status is not None:
                    data.status = status
                if remark is not None:
                    data.remark = remark
                data.update_user = user_id
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def delete_rule(cls, rule_id: int, project_id: int, user_id: int) -> bool:
        """逻辑删除 —— 立即从对外匹配移除(FR-013)"""
        async with async_session() as session:
            async with session.begin():
                sql = select(PityMockRule).where(
                    PityMockRule.id == rule_id, PityMockRule.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("规则不存在")
                if data.project_id != project_id:
                    raise Exception("规则不属于当前项目")
                cls.delete_model(data, user_id)
                await session.flush()
                return True

    @classmethod
    async def update_status(cls, rule_id: int, project_id: int, user_id: int, status: int
                            ) -> PityMockRule:
        """启用 / 停用 —— 停用立即退出对外匹配, 启用立即恢复(FR-012)"""
        if status not in (0, 1):
            raise Exception("规则状态只能是 0(停用) 或 1(启用)")
        async with async_session() as session:
            async with session.begin():
                sql = select(PityMockRule).where(
                    PityMockRule.id == rule_id, PityMockRule.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("规则不存在")
                if data.project_id != project_id:
                    raise Exception("规则不属于当前项目")
                data.status = status
                data.update_user = user_id
                await session.flush()
                session.expunge(data)
                return data

    @classmethod
    async def list_enabled_rules(cls, project_id: int) -> List[PityMockRule]:
        """对外匹配的候选集: 该项目下启用且未删除的规则"""
        async with async_session() as session:
            sql = select(PityMockRule).where(
                PityMockRule.project_id == project_id,
                PityMockRule.deleted_at == 0,
                PityMockRule.status == 1,
            )
            result = await session.execute(sql)
            return list(result.scalars().all())

    @classmethod
    async def query_project_by_app(cls, app: str) -> Optional[Project]:
        """
        按 app 定位项目(FR-018): app 可重复时取**最早创建**的 —— 按 id 升序取第一条。
        项目 app 为空 / 不存在 → None(对外服务返回 404)。
        """
        if not app:
            return None
        async with async_session() as session:
            sql = (select(Project)
                   .where(Project.app == app, Project.deleted_at == 0)
                   .order_by(Project.id.asc()))
            result = await session.execute(sql)
            return result.scalars().first()

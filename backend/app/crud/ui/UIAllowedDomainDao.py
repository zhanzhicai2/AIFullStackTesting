"""
允许域名白名单 DAO —— SSRF 安全边界

**白名单为空 = 该项目不允许访问任何站点**(不是"允许全部")。
增删权限收紧到 ADMIN(见 contracts/api.md §1.2), 这是安全边界而不是普通配置。
"""
import re
from typing import List, Optional

from sqlalchemy import select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ui_case import PityUIAllowedDomain

# 裸域名: 允许 *.example.com 形式的子域通配, 不允许协议、路径、端口、@、空格
DOMAIN_PATTERN = re.compile(r"^(\*\.)?([a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)"
                             r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)+$")


@ModelWrapper(PityUIAllowedDomain)
class UIAllowedDomainDao(Mapper):

    @staticmethod
    def validate_domain(domain: str) -> str:
        """
        校验域名必须是**裸域名** —— 不含协议、不含路径、不含端口。
        :return: 规范化后的小写域名
        """
        if not domain or not domain.strip():
            raise Exception("域名不能为空")
        value = domain.strip().lower()
        if "://" in value:
            raise Exception("域名不能包含协议, 请只填裸域名, 例如 example.com")
        if "/" in value:
            raise Exception("域名不能包含路径, 请只填裸域名, 例如 example.com")
        if ":" in value:
            raise Exception("域名不能包含端口, 请只填裸域名, 例如 example.com")
        if "@" in value or " " in value:
            raise Exception("域名格式不合法")
        if not DOMAIN_PATTERN.match(value):
            raise Exception(f"域名「{domain}」格式不合法, 请填写裸域名, 例如 example.com 或 *.example.com")
        return value

    @classmethod
    async def list_domains(cls, project_id: int, env: int = None) -> List[PityUIAllowedDomain]:
        async with async_session() as session:
            sql = select(PityUIAllowedDomain).where(PityUIAllowedDomain.project_id == project_id,
                                                     PityUIAllowedDomain.deleted_at == 0)
            if env is not None:
                # env 为 None 的记录表示所有环境都生效, 一并返回
                sql = sql.where((PityUIAllowedDomain.env == env) | (PityUIAllowedDomain.env.is_(None)))
            sql = sql.order_by(PityUIAllowedDomain.id.asc())
            result = await session.execute(sql)
            return list(result.scalars().all())

    @classmethod
    async def list_domain_names(cls, project_id: int, env: int = None) -> List[str]:
        """只取域名列表 —— 执行期的白名单匹配用这个"""
        domains = await cls.list_domains(project_id, env)
        return [d.domain for d in domains]

    @classmethod
    async def query_domain(cls, domain_id: int) -> Optional[PityUIAllowedDomain]:
        async with async_session() as session:
            sql = select(PityUIAllowedDomain).where(PityUIAllowedDomain.id == domain_id,
                                                    PityUIAllowedDomain.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def insert_domain(cls, domain: str, project_id: int, user_id: int, env: int = None
                             ) -> PityUIAllowedDomain:
        value = cls.validate_domain(domain)
        exist = await cls.query_domain_by_value(project_id, value, env)
        if exist is not None:
            raise Exception(f"域名「{value}」已存在")
        model = PityUIAllowedDomain(domain=value, user=user_id, project_id=project_id, env=env)
        return await cls.insert(model=model, log=True)

    @classmethod
    async def query_domain_by_value(cls, project_id: int, domain: str, env: int = None
                                     ) -> Optional[PityUIAllowedDomain]:
        async with async_session() as session:
            sql = select(PityUIAllowedDomain).where(PityUIAllowedDomain.project_id == project_id,
                                                     PityUIAllowedDomain.domain == domain,
                                                     PityUIAllowedDomain.deleted_at == 0)
            if env is None:
                sql = sql.where(PityUIAllowedDomain.env.is_(None))
            else:
                sql = sql.where(PityUIAllowedDomain.env == env)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def delete_domain(cls, domain_id: int, user_id: int):
        async with async_session() as session:
            async with session.begin():
                sql = select(PityUIAllowedDomain).where(PityUIAllowedDomain.id == domain_id,
                                                        PityUIAllowedDomain.deleted_at == 0)
                result = await session.execute(sql)
                data = result.scalars().first()
                if data is None:
                    raise Exception("域名不存在")
                cls.delete_model(data, user_id)
                await session.flush()
                session.expunge(data)
                return True

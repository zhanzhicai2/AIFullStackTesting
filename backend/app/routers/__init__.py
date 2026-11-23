from collections import namedtuple
from typing import Dict, List, Type, TypeVar

from fastapi import Header, APIRouter, Depends
from pydantic import BaseModel
from starlette import status

from app.crud import Mapper
from app.crud.auth.UserDao import UserDao
from app.enums.CiEnum import TOKEN_PREFIX
from app.exception.request import AuthException, PermissionException
from app.handler.fatcory import PityResponse
from app.middleware.Jwt import UserToken
from app.models import async_session
from config import Config

FORBIDDEN = "对不起, 你没有足够的权限"


class Permission:
    def __init__(self, role: int = Config.MEMBER):
        self.role = role

    async def __call__(self, token: str = Header(...)):
        if not token:
            raise AuthException(status.HTTP_200_OK, "用户信息身份认证失败, 请检查")
        try:
            user_info = UserToken.parse_token(token)
            if user_info.get("role", 0) < self.role:
                raise PermissionException(status.HTTP_200_OK, FORBIDDEN)
            user = await UserDao.query_user(user_info['id'])
            if user is None:
                raise Exception("用户不存在")
            user_info = PityResponse.model_to_dict(user, "password")
        except PermissionException as e:
            raise e
        except Exception as e:
            raise AuthException(status.HTTP_200_OK, str(e))
        return user_info


class CIPermission:
    """
    CI 端点鉴权 —— **双模**: 外部流水线的长期凭据, 或平台管理员的 JWT。

    **为什么需要双模**: `/ci/run/{id}` 与 `/ci/run/list` 同时服务两端 ——
    - 外部 CI 轮询结果 → 用 `pity_ci_` 凭据(spec US2 / SC-004)
    - 平台用户在 `/ci` 页看触发历史 → 用登录 JWT(spec US3)

    只认凭据的话, 前端发 JWT 一律 401, 历史页永远是空的。

    **与 `Permission()` 的关系**(research D2):
    - 读**同名的 `token` header**(平台既有约定), CI 接入示例因此与前端写法一致
    - **`Permission()` 本体一行不改** —— JWT 分支直接**调用**它, 不重复实现一遍解析
    - 返回结构是 `Permission()` 的**超集**: 既有 `user_info['id']` / `['role']` 照旧可用,
      额外多一个 `ci_integration` 键:凭据路径带作用域, **JWT 路径为 `None`**

    凭据路径的校验链(`contracts/api.md` §1.3 第 1~5、7 步; 第 6 步「项目作用域」在
    路由层做, 因为目标 plan_id 在请求体里): 前缀 → 摘要等值查 → 未删除 → 启用 →
    未过期 → 更新 last_used_at。四种拒绝的 `msg` 各不相同, **都不回显凭据内容**。
    """

    async def __call__(self, token: str = Header(...)):
        if token and token.startswith(TOKEN_PREFIX):
            return await self._by_credential(token)
        # JWT 分支: 复用 Permission(限定 MANAGER —— /ci 页含凭据, 与页面 authority 一致)
        user_info = await Permission(Config.MANAGER)(token=token)
        user_info["ci_integration"] = None
        return user_info

    @staticmethod
    async def _by_credential(token: str):
        # 延迟导入: app/routers/__init__.py 被全站 import, 顶层引 DAO 容易成环
        from app.crud.ci.CiIntegrationDao import CiIntegrationDao

        try:
            integration, err = await CiIntegrationDao.validate_token(token)
            if integration is None:
                raise AuthException(status.HTTP_200_OK, err or "CI 凭据无效")
            user = await UserDao.query_user(integration.create_user)
            if user is None:
                raise AuthException(status.HTTP_200_OK, "凭据签发人不存在, 无法识别操作身份")
            user_info = PityResponse.model_to_dict(user, "password")
        except AuthException as e:
            raise e
        except Exception as e:
            raise AuthException(status.HTTP_200_OK, str(e))
        user_info["ci_integration"] = dict(
            id=integration.id,
            project_id=integration.project_id,
            plan_id=integration.plan_id,
            name=integration.name,
        )
        return user_info


async def get_session():
    """
    获取异步session
    :return:
    """
    async with async_session() as session:
        yield session

_router: Dict[str, APIRouter] = {}
T = TypeVar("T", bound=BaseModel)
DAO = TypeVar("DAO", bound=Mapper)
CurdParams = namedtuple("parameters", ["name", "type_", "default", "like"])


class PityRouter(object):
    """
    pity路由基类，支持单标crud
    """

    def __init__(self, router: APIRouter, schema: Type[T], dao: Type[DAO], business, path, prefix="",
                 tags: List[str] = None, query_list: List[CurdParams] = None):
        self.router = router
        self.schema = schema
        self.dao = dao
        self.tags = tags
        self.business = business
        self.prefix = prefix
        self.path = path
        self.query_list = query_list

    @staticmethod
    def get_query_parameters(query: List[CurdParams]):
        params = ",".join(
            [f"{x.name}: {x.type_}" + (f" = '{x.default}'" if x.default is not None else "") for x in query])
        return params

    @staticmethod
    def get_query_sentence(query: List[CurdParams]):
        return ",".join([f"""{x.name}={x.name if not x.like else f"f'%{{{x.name}}}%'"}""" for x in query])

    def add_all(self):
        query = [] if self.query_list is None else self.query_list

        async def create(data: self.schema, user_info=Depends(AuthUser())):  # type: ignore
            model = data.dict()
            model.pop('id', None)
            result = await self.dao.insert(self.dao.model(**model, user=user_info.name))
            return PityResponse.success(result)

        params = ",".join([f"{x.name}: {x.type_}" for x in query])
        if params:
            params += ', '
        loc = dict(Permission=Permission, Depends=Depends, Response=PityResponse, self=self)
        list_func = f"""
    async def list_data({PityRouter.get_query_parameters(query)}):
        result = await self.dao.list_record({PityRouter.get_query_sentence(query)})
        return Response.ok(Response.model_to_list(result))
            """
        exec(list_func, loc)

        async def update(data: self.schema, user_info=Depends(AuthUser())):  # type: ignore
            result = await self.dao.update_by_id(data, user_info.name)
            return PityResponse.success(PityResponse.model_to_dict(result))

        async def delete(id: int, user_info=Depends(Permission())):
            await self.dao.delete_by_id(id)
            return PityResponse.success()

        self.router.add_api_route(f"{self.prefix}/{self.path}", create, tags=self.tags,
                                  summary=f"添加{self.business}", methods=['PUT'])

        self.router.add_api_route(f"{self.prefix}/{self.path}", update, tags=self.tags,
                                  summary=f"编辑{self.business}", methods=['POST'])

        self.router.add_api_route(f"{self.prefix}/{self.path}", delete, tags=self.tags,
                                  summary=f"删除{self.business}", methods=['DELETE'])

        self.router.add_api_route(f"{self.prefix}/{self.path}", loc.get("list_data"), tags=self.tags,
                                  summary=f"获取{self.business}", methods=['GET'])

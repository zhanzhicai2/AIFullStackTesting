"""
CI 集成配置(凭据)管理路由 —— 前缀 `/ci`(**由 `app/routers/ci/__init__.py` 统一加**),
**需管理员**

**权限(constitution 安全要求「新增写入通道收紧角色」)**:
全部 `Depends(Permission(Config.MANAGER))` —— 凭据是安全材料, 只有 admin /
superAdmin 能签发、启停、删除(spec FR-028)。普通成员连列表都看不到。

**明文只出现一次(FR-002 / SC-007)**:
`insert` 是**唯一**返回 `token` 明文的端点; `list` / `update` / `switch` / `delete`
一律 `model_to_dict(..., "token_hash")`, 响应里既没有明文也没有摘要。

**`expires_at` 三态(决定 Q4)**: 用 `form.__fields_set__` 判定键是否被显式提供 ——
pydantic v1 下「不传」与「传 null」都会落成 `None`, 无法区分, 只能看字段集合:
- 不含该键        → `default_expires_at()`(now + 1 年)
- 含键且为 `None` → 长期有效
- 含键且有值      → 按该值
"""
from fastapi import APIRouter, Depends

from app.crud.ci.CiIntegrationDao import CiIntegrationDao
from app.crud.test_case.TestPlan import PityTestPlanDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.ci import CiIntegrationForm
from config import Config

router = APIRouter()

# 列表响应**不含**摘要(spec FR-002)
_LIST_IGNORE = ("token_hash",)


async def _check_plan_owned(plan_id: int, project_id: int):
    """绑定的测试计划必须属于同一项目 —— 否则绑定关系会变成跨项目的口子"""
    if plan_id is None:
        return
    plan = await PityTestPlanDao.query_test_plan(plan_id)
    if plan is None:
        raise Exception("测试计划不存在或已删除")
    if plan.project_id != project_id:
        raise Exception("测试计划不属于当前项目")


@router.get("/integration/list", description="CI 集成配置列表")
async def list_integration(project_id: int, page: int = 1, size: int = 20,
                           user_info=Depends(Permission(Config.MANAGER))):
    try:
        data, total = await CiIntegrationDao.list_integrations(project_id=project_id,
                                                               page=page, size=size)
        return PityResponse.success_with_size(PityResponse.model_to_list(data, *_LIST_IGNORE),
                                              total=total)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/integration/insert", description="签发 CI 凭据(明文仅此一次返回)")
async def insert_integration(form: CiIntegrationForm,
                             user_info=Depends(Permission(Config.MANAGER))):
    try:
        if form.id:
            return PityResponse.failed("新建不需要 id")
        await _check_plan_owned(form.plan_id, form.project_id)
        # 三态判定: 见模块 docstring
        if "expires_at" in form.__fields_set__:
            expires_at = form.expires_at          # None = 长期有效
        else:
            expires_at = CiIntegrationDao.default_expires_at()
        data, token = await CiIntegrationDao.issue(
            project_id=form.project_id, name=form.name, user_id=user_info["id"],
            plan_id=form.plan_id, callback_url=form.callback_url, expires_at=expires_at)
        payload = PityResponse.model_to_dict(data, *_LIST_IGNORE)
        payload["token"] = token        # ← 明文, 全站唯一一处
        return PityResponse.success(payload)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/integration/update", description="编辑集成配置(不接受任何凭据字段)")
async def update_integration(form: CiIntegrationForm,
                             user_info=Depends(Permission(Config.MANAGER))):
    try:
        if not form.id:
            return PityResponse.failed("缺少集成配置 id")
        await _check_plan_owned(form.plan_id, form.project_id)
        data = await CiIntegrationDao.update_integration(
            integration_id=form.id, project_id=form.project_id, user_id=user_info["id"],
            name=form.name, plan_id=form.plan_id, callback_url=form.callback_url)
        return PityResponse.success(PityResponse.model_to_dict(data, *_LIST_IGNORE))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/integration/switch", description="启停 CI 凭据(停用即吊销, 立即生效)")
async def switch_integration(id: int, status: bool,
                             user_info=Depends(Permission(Config.MANAGER))):
    try:
        # 先按 id 取出归属项目, 再带项目做切换 —— DAO 层的项目校验不被绕过
        current = await CiIntegrationDao.query_by_id(id)
        if current is None:
            return PityResponse.failed("集成配置不存在")
        data = await CiIntegrationDao.switch(integration_id=id, project_id=current.project_id,
                                             user_id=user_info["id"], enabled=status)
        return PityResponse.success(PityResponse.model_to_dict(data, *_LIST_IGNORE))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/integration/delete", description="删除 CI 凭据(逻辑删除, 保留触发记录可回溯)")
async def delete_integration(id: int, user_info=Depends(Permission(Config.MANAGER))):
    try:
        # 同上: 先按 id 取归属项目, 再带项目删除(契约 §2.5 只收 id)
        current = await CiIntegrationDao.query_by_id(id)
        if current is None:
            return PityResponse.failed("集成配置不存在")
        await CiIntegrationDao.delete(integration_id=id, project_id=current.project_id,
                                      user_id=user_info["id"])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)

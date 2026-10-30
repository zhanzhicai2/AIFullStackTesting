"""
Mock 规则管理路由(前缀 /mock, 需鉴权)

**权限说明(constitution 安全要求「新增写入通道收紧角色」)**:
- 全部接口 `Depends(Permission())`(登录 + 角色 ≥ MEMBER) —— 与用例/元素同级
  (2 号 UI 元素 DAO 同款), mock 规则是普通业务数据, 不是安全边界(不控制出网、不执行代码)
- 读操作追加 `ProjectRoleDao.read_permission` —— 私有项目非成员 → 403(平台既有语义)
- DAO 层按 project_id 隔离, 跨项目操作一律拒绝

**注册顺序硬约束**: 本路由 MUST 在 `service.py`(对外 catch-all)之前注册 —— 否则
`/mock/rule/list` 被当成「app=rule」的对外请求吞掉(见 main.py)。
"""
import json
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends

from app.core import mock_engine, mock_render
from app.core.mock_render import MockRequestSnapshot
from app.crud.mock.MockRuleDao import MockRuleDao
from app.crud.project.ProjectRoleDao import ProjectRoleDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.mock import MockRuleForm, MockRulePreviewForm, MockRuleStatusForm

router = APIRouter(prefix="/mock")


@router.get("/rule/list", description="规则列表(分页)")
async def list_rule(project_id: int, method: str = None, path: str = None, status: int = None,
                    page: int = 1, size: int = 20, user_info=Depends(Permission())):
    try:
        await ProjectRoleDao.read_permission(project_id, user_info["id"], user_info["role"])
        data, total = await MockRuleDao.list_rules(project_id=project_id, method=method,
                                                   path=path, status=status, page=page, size=size)
        return PityResponse.success_with_size(PityResponse.model_to_list(data), total=total)
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/rule/detail", description="规则详情")
async def rule_detail(id: int, project_id: int, user_info=Depends(Permission())):
    try:
        await ProjectRoleDao.read_permission(project_id, user_info["id"], user_info["role"])
        data = await MockRuleDao.query_rule(id, project_id)
        if data is None:
            return PityResponse.failed("规则不存在")
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/rule/insert", description="新建规则")
async def insert_rule(form: MockRuleForm, user_info=Depends(Permission())):
    try:
        await ProjectRoleDao.read_permission(form.project_id, user_info["id"], user_info["role"])
        data, warn = await MockRuleDao.insert_rule(
            name=form.name, method=form.method, path=form.path, user_id=user_info["id"],
            project_id=form.project_id, priority=form.priority, status_code=form.status_code,
            response_headers=form.response_headers, response_body=form.response_body,
            delay=form.delay, status=form.status, remark=form.remark)
        msg = warn if warn else "操作成功"
        return PityResponse.success(PityResponse.model_to_dict(data), msg=msg)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/rule/update", description="修改规则")
async def update_rule(form: MockRuleForm, user_info=Depends(Permission())):
    try:
        if not form.id:
            return PityResponse.failed("缺少规则 id")
        await ProjectRoleDao.read_permission(form.project_id, user_info["id"], user_info["role"])
        data = await MockRuleDao.update_rule(
            rule_id=form.id, project_id=form.project_id, user_id=user_info["id"],
            name=form.name, method=form.method, path=form.path, priority=form.priority,
            status_code=form.status_code, response_headers=form.response_headers,
            response_body=form.response_body, delay=form.delay, status=form.status,
            remark=form.remark)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/rule/delete", description="删除规则(逻辑删除)")
async def delete_rule(id: int, project_id: int, user_info=Depends(Permission())):
    try:
        await ProjectRoleDao.read_permission(project_id, user_info["id"], user_info["role"])
        await MockRuleDao.delete_rule(id, project_id, user_info["id"])
        return PityResponse.success(True)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/rule/status", description="启用 / 停用规则")
async def update_rule_status(form: MockRuleStatusForm, user_info=Depends(Permission())):
    try:
        await ProjectRoleDao.read_permission(form.project_id, user_info["id"], user_info["role"])
        data = await MockRuleDao.update_status(form.id, form.project_id, user_info["id"], form.status)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/rule/preview", description="规则调试(就地模拟一次匹配)")
async def preview_rule(form: MockRulePreviewForm, user_info=Depends(Permission())):
    """
    就地模拟: 用填写的请求快照跑一遍匹配 + 渲染, 展示命中规则与最终响应。
    不经过对外服务、不产生真实延迟等待(spec FR-009)。
    """
    try:
        await ProjectRoleDao.read_permission(form.project_id, user_info["id"], user_info["role"])
        rules = await MockRuleDao.list_enabled_rules(form.project_id)
        parsed = urlparse(form.path)
        path_only = parsed.path
        query = parse_qs(parsed.query)
        body = {}
        if form.body:
            body = json.loads(form.body) if isinstance(form.body, str) else form.body
        headers = {}
        if form.headers:
            headers = json.loads(form.headers) if isinstance(form.headers, str) else form.headers
        rule = mock_engine.match_rule(form.method, path_only, rules)
        if rule is None:
            return PityResponse.success(dict(matched=False, rule=None,
                                             reason="没有规则会命中该请求"))
        snapshot = MockRequestSnapshot(path=mock_engine.normalize_path(path_only),
                                       query=query, body=body, headers=headers)
        rendered = mock_render.render(rule.response_body or "", snapshot)
        return PityResponse.success(dict(
            matched=True,
            rule=dict(id=rule.id, name=rule.name, method=rule.method, path=rule.path,
                      priority=rule.priority, status_code=rule.status_code),
            status_code=rule.status_code,
            response_headers=rule.response_headers,
            response_body=rendered,
            delay=rule.delay,
        ))
    except Exception as e:
        return PityResponse.failed(e)

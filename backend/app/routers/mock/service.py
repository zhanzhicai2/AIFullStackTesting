"""
Mock 对外服务路由(前缀 /mock, **无鉴权**)

**形态(spec 决策, 用户确认)**: 纯静态 mock 服务 —— 命中规则返回配置的静态响应,
未命中返回 404。**不发任何外部请求、不执行任何代码** —— 从机制上排除 SSRF 与任意执行面
(回归脚本 `mock_selftest.py` 对源码做 AST 静态扫描保证: 无 aiohttp/httpx/requests、无 eval/exec)。

**无鉴权是设计取舍(spec Assumptions)**: 被测系统无法携带平台 JWT, 基地址对知晓 `app`
的任何人开放 —— 因此**不挂** `request_info`(记操作日志)依赖, 只留下垃圾与噪音;
且不得在 mock 响应中放置真实凭据(使用说明已标注)。

**注册顺序硬约束**: 本路由 MUST 在管理路由(`admin.py`)之后注册 —— 否则 `/mock/rule/list`
被当成「app=rule」的对外请求吞掉。见 `main.py`。
"""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.core import mock_engine, mock_render
from app.core.mock_render import MockRequestSnapshot
from app.crud.mock.MockRuleDao import MockRuleDao
from app.enums.MockEnum import METHODS

# 对外支持的七种方法(ANY 是规则侧的通配, 不是 HTTP 方法; TRACE/CONNECT 不支持)
ALLOWED_METHODS = [m for m in METHODS if m != "ANY"]

router = APIRouter(prefix="/mock")


def _not_found() -> JSONResponse:
    """未命中 / 项目不存在 / app 为空 —— 统一 404, 不泄露任何项目或规则信息(FR-006)"""
    return JSONResponse(status_code=404,
                        content={"code": 404, "data": None, "msg": "mock rule not found"})


def _looks_like_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def _parse_query(request: Request) -> dict:
    """同名 query 参数保留多值(list), 渲染器取第一个 —— 与调试入口语义一致"""
    query: dict = {}
    for key in request.query_params.keys():
        query[key] = request.query_params.getlist(key)
    return query


@router.api_route("/{full_path:path}", methods=ALLOWED_METHODS,
                  description="Mock 服务入口(无鉴权)")
async def mock_entry(full_path: str, request: Request):
    """
    Mock 服务入口: `/mock/{app}/...`。

    处理链: app 定位项目(最早创建, FR-018)→ 项目内启用规则 → 确定性匹配
    (mock_engine.match_rule)→ 命中则按配置 sleep 延迟后返回状态码/头/体(变量渲染),
    未命中 404。
    """
    try:
        # full_path 形如 "app/api/user/1"(不含前导 /mock/)
        app, _, sub_path = full_path.partition("/")
        project = await MockRuleDao.query_project_by_app(app)
        if project is None:
            return _not_found()
        rules = await MockRuleDao.list_enabled_rules(project.id)
        method = request.method.upper()

        # 请求体: 仅 Content-Type 为 JSON 时解析(供 $request.body.* 变量);
        # 非 JSON 体按空处理, 不阻断 mock 返回
        body: dict = {}
        if "application/json" in request.headers.get("content-type", ""):
            raw = await request.body()
            if raw:
                try:
                    body = json.loads(raw)
                except Exception:
                    body = {}

        rule = mock_engine.match_rule(method, sub_path, rules)
        if rule is None:
            return _not_found()

        snapshot = MockRequestSnapshot(path=mock_engine.normalize_path(sub_path),
                                       query=_parse_query(request),
                                       body=body,
                                       headers=dict(request.headers))

        if rule.delay:
            await asyncio.sleep(rule.delay / 1000.0)

        rendered = mock_render.render(rule.response_body or "", snapshot)

        headers: dict = {}
        if rule.response_headers:
            try:
                headers = json.loads(rule.response_headers)
            except Exception:
                headers = {}
        # Content-Type 缺省时按响应体形态推断
        if "content-type" not in {k.lower() for k in headers.keys()}:
            headers["Content-Type"] = "application/json" if _looks_like_json(rendered) \
                else "text/plain; charset=utf-8"

        # HEAD 请求返回空体(HTTP 语义)
        content = rendered if method != "HEAD" else None
        return Response(content=content, status_code=rule.status_code, headers=headers)
    except Exception:
        # 服务端异常统一 500 —— 不把内部细节暴露给对外调用方
        return JSONResponse(status_code=500,
                            content={"code": 500, "data": None, "msg": "mock service error"})

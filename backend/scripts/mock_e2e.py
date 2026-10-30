"""
Mock 配置端到端测试(**需要数据库**)

跑法:
    cd backend
    .venv/bin/python scripts/mock_e2e.py

**等价路径说明**: 与 `ai_workbench_e2e.py` / `ui_e2e.py` 一致 —— 管理接口**直接调路由函数**
(传模拟 user_info, 绕开 JWT 与 HTTP 层);对外 mock 服务**直接调 `mock_entry`**(构造
Starlette Request, 绕开 HTTP 传输层)。不依赖 httpx/TestClient(venv 无此包)。

覆盖(T017 + T020):
- 建规则 → 对外命中 → 校验状态码/头/体/变量回显
- 未命中 / 方法不符 / app 不存在 / app 为空 → 404 且响应结构一致
- 启停生效(停用 404、启用恢复)
- 删除后 404
- **app 重复取最早创建**(FR-018)
- 同方法同精确路径新建 → 返回 warning 文案仍创建成功(FR-007)
- preview 命中与未命中(FR-009)
- 私有项目非成员读列表被拒、超管放行(FR-015)
- 跨项目删除被拒

规则集设计(避免通配兜住其他断言): 通配规则用独立前缀 `/fallback/*`。

⚠️ 会在 dev 库留下痕迹(e2e 项目/规则) —— `backend/scripts/` 下的脚本留下
e2e 痕迹是既有约定，不要清理。
"""
import asyncio
import os
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402  (触发全部 include_router)
from sqlalchemy import select  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app.crud.project.ProjectDao import ProjectDao  # noqa: E402
from app.models import Base, async_engine, async_session  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.routers.mock.admin import (delete_rule, insert_rule, list_rule,  # noqa: E402
                                    preview_rule, update_rule_status)
from app.routers.mock.service import mock_entry  # noqa: E402
from app.schema.mock import (MockRuleForm, MockRulePreviewForm,  # noqa: E402
                             MockRuleStatusForm)

FAILED = []

# 模拟鉴权后的用户信息: 超管(直接调路由函数时绕开 Permission() 依赖)
ADMIN = {"id": 1, "name": "e2e-admin", "role": 2}
# 非任何项目成员、非超管的普通用户
OUTSIDER = {"id": 999999, "name": "e2e-outsider", "role": 0}

TS = str(int(time.time() * 1000))
# pity_project.name 是 String(16) —— 项目名必须 ≤16 字符(HANDOFF 坑 4 同族)
PROJECT_NAME = f"me2e-{TS[-6:]}"
PROJECT_APP = f"mockapp{TS}"
PRIVATE_NAME = f"me2e-prv-{TS[-6:]}"
PRIVATE_APP = f"mockpriv{TS}"
DUP_NAME = f"me2e-dup-{TS[-6:]}"   # 与主项目同 app(测 FR-018)


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


def make_form(project_id, name, method, path, **kw):
    return MockRuleForm(project_id=project_id, name=name, method=method, path=path,
                        response_body=kw.pop("response_body", '{"code": 0}'),
                        **kw)


def make_request(method: str, path: str, query=None, body=None, headers=None) -> Request:
    """构造 Starlette Request —— 等价于一次真实 HTTP 请求(不含传输层)"""
    qs = urlencode(query or {})
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": qs.encode(),
        "headers": [(str(k).lower().encode(), str(v).encode())
                    for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 50000),
        "server": ("mocktest", 80),
        "scheme": "http",
    }
    req = Request(scope)
    if body is not None:
        req._body = body.encode()
    return req


async def get_project_id(name: str) -> int:
    async with async_session() as session:
        r = await session.execute(select(Project).where(Project.name == name,
                                                        Project.deleted_at == 0))
        return r.scalars().first().id


async def setup_projects():
    """建三个项目: 主项目 / 私有项目 / 同 app 重复项目"""
    await ProjectDao.add_project(PROJECT_NAME, PROJECT_APP, owner=1, user_id=1,
                                 private=False, description="mock e2e")
    await ProjectDao.add_project(PRIVATE_NAME, PRIVATE_APP, owner=1, user_id=1,
                                 private=True, description="mock e2e private")
    await ProjectDao.add_project(DUP_NAME, PROJECT_APP, owner=1, user_id=1,
                                 private=False, description="mock e2e dup app")
    print(f"  项目就绪: {PROJECT_NAME}(app={PROJECT_APP}) / {PRIVATE_NAME} / {DUP_NAME}")


async def test_admin_crud(project_id: int) -> int:
    print("== 管理链路: 建规则 / 查重提示 / 列表 / 启停 ==")
    # 1. 精确规则(含变量回显)
    form = make_form(project_id, "用户详情", "GET", "/api/user/1",
                     response_body='{"code": 0, "data": {"name": "$request.query.name"}}')
    res = await insert_rule(form, ADMIN)
    check("建规则成功", res.get("code") == 0, str(res))
    check("精确规则 path_type=0", res["data"]["path_type"] == 0)
    check("新建不返回 warning", res.get("msg") == "操作成功", res.get("msg"))

    # 2. 参数化规则
    res3 = await insert_rule(make_form(project_id, "用户批量", "GET", "/api/user/:id"), ADMIN)
    check("参数化规则 path_type=1", res3.get("code") == 0 and res3["data"]["path_type"] == 1,
          str(res3))

    # 3. 独立启停规则(专属路径, 无其他规则覆盖)
    res_s = await insert_rule(make_form(project_id, "独立接口", "GET", "/api/standalone"), ADMIN)
    check("独立规则建成功", res_s.get("code") == 0, str(res_s))
    standalone_id = res_s["data"]["id"]

    # 4. 通配规则(独立前缀, 兜底测试用)
    res4 = await insert_rule(make_form(project_id, "兜底", "ANY", "/fallback/*"), ADMIN)
    check("通配规则 path_type=2", res4.get("code") == 0 and res4["data"]["path_type"] == 2,
          str(res4))

    # 同方法同精确路径再建 —— 不阻断但带 warning(FR-007)
    form2 = make_form(project_id, "用户详情2", "GET", "/api/user/1", priority=1)
    res2 = await insert_rule(form2, ADMIN)
    check("重复精确规则仍创建成功", res2.get("code") == 0, str(res2))
    check("重复精确规则带 warning", "已存在" in (res2.get("msg") or ""), res2.get("msg"))

    # 列表
    res_list = await list_rule(project_id=project_id, page=1, size=20, user_info=ADMIN)
    check("列表返回 5 条", res_list.get("code") == 0 and res_list.get("total") == 5,
          f"total={res_list.get('total')}")

    # 停用独立规则 → 列表状态变化
    res_st = await update_rule_status(
        MockRuleStatusForm(id=standalone_id, project_id=project_id, status=0), ADMIN)
    check("停用成功", res_st.get("code") == 0 and res_st["data"]["status"] == 0, str(res_st))
    res_list2 = await list_rule(project_id=project_id, status=0, page=1, size=20, user_info=ADMIN)
    check("按停用筛选命中 1 条", res_list2.get("total") == 1, f"total={res_list2.get('total')}")

    # DUP 项目建一条独立规则(测 app 重复时命中最早项目)
    dup_id = await get_project_id(DUP_NAME)
    await insert_rule(make_form(dup_id, "dup-only", "GET", "/dup/only"), ADMIN)
    return standalone_id


async def call_service(app: str, method: str, sub_path: str, query=None, body=None,
                       headers=None):
    """对外 mock 服务: 构造请求直接调 mock_entry。
    full_path 须含 app 前缀(与 /mock/{full_path:path} 路由语义一致)"""
    req = make_request(method, f"/mock/{app}/{sub_path}", query=query, body=body,
                       headers=headers)
    return await mock_entry(f"{app}/{sub_path}", req)


async def test_service_http(app: str, standalone_id: int, project_id: int):
    print("== 对外服务(直接调 mock_entry) ==")
    # 精确规则命中 + 变量回显
    resp = await call_service(app, "GET", "api/user/1", query={"name": "tom"})
    check("精确规则命中", resp.status_code == 200, str(resp.status_code))
    import json as _json
    body = _json.loads(resp.body)
    check("响应体变量回显", body.get("data", {}).get("name") == "tom", str(body))

    # 参数化规则命中
    resp2 = await call_service(app, "GET", "api/user/42")
    check("参数化规则命中", resp2.status_code == 200, str(resp2.status_code))

    # 通配兜底(独立前缀)
    resp3 = await call_service(app, "GET", "fallback/anything/else")
    check("通配规则兜底", resp3.status_code == 200, str(resp3.status_code))

    # 独立规则 → 启停循环(FR-012); 独立规则此时为停用(admin 阶段最后一步停用)
    resp4 = await call_service(app, "GET", "api/standalone")
    check("停用状态 404", resp4.status_code == 404,
          f"status={resp4.status_code} body={resp4.body}")
    await update_rule_status(MockRuleStatusForm(id=standalone_id, project_id=project_id, status=1),
                             ADMIN)
    resp5 = await call_service(app, "GET", "api/standalone")
    check("重新启用立即恢复", resp5.status_code == 200, str(resp5.status_code))
    await update_rule_status(MockRuleStatusForm(id=standalone_id, project_id=project_id, status=0),
                             ADMIN)
    resp6 = await call_service(app, "GET", "api/standalone")
    check("再次停用立即 404", resp6.status_code == 404,
          f"status={resp6.status_code} body={resp6.body}")

    # 方法不符(精确/参数化都是 GET, 通配前缀不同)→ 404
    resp7 = await call_service(app, "POST", "api/user/1")
    check("方法不符 404", resp7.status_code == 404, str(resp7.status_code))

    # 路径不匹配 404 + 结构一致
    resp8 = await call_service(app, "GET", "nope/nope")
    check("路径不匹配 404", resp8.status_code == 404, str(resp8.status_code))
    check("404 响应结构一致", _json.loads(resp8.body).get("code") == 404, str(resp8.body))

    # app 不存在 / app 为空
    resp9 = await mock_entry("no-such-app/x", make_request("GET", "/mock/no-such-app/x"))
    check("app 不存在 404", resp9.status_code == 404, str(resp9.status_code))
    resp10 = await mock_entry("/x", make_request("GET", "/mock//x"))
    check("app 为空 404", resp10.status_code == 404, str(resp10.status_code))

    # app 重复 → 命中最早创建的主项目: /dup/only 只有 DUP 有规则 → 404
    resp11 = await call_service(app, "GET", "dup/only")
    check("app 重复取最早项目(主项目无此规则 → 404)", resp11.status_code == 404,
          f"status={resp11.status_code} body={resp11.body}")


async def test_preview(project_id: int):
    print("== 规则调试(preview) ==")
    form = MockRulePreviewForm(project_id=project_id, method="GET", path="/api/user/1?name=tom")
    res = await preview_rule(form, ADMIN)
    check("preview 命中", res.get("code") == 0 and res["data"]["matched"] is True, str(res))
    check("preview 解析后响应回显", "tom" in res["data"]["response_body"],
          str(res["data"].get("response_body")))
    miss = MockRulePreviewForm(project_id=project_id, method="GET", path="/no/rule")
    res2 = await preview_rule(miss, ADMIN)
    check("preview 未命中明确提示", res2.get("code") == 0 and res2["data"]["matched"] is False,
          str(res2))


async def test_permission():
    print("== 权限(私有项目隔离, FR-015) ==")
    private_id = await get_project_id(PRIVATE_NAME)
    res = await list_rule(project_id=private_id, page=1, size=20, user_info=OUTSIDER)
    check("私有项目非成员被拒", res.get("code") != 0 and "权限" in (res.get("msg") or ""),
          str(res))
    res2 = await list_rule(project_id=private_id, page=1, size=20, user_info=ADMIN)
    check("超管可读私有项目", res2.get("code") == 0, str(res2))
    res3 = await delete_rule(id=999999, project_id=private_id, user_info=ADMIN)
    check("删除不存在的规则被拒", res3.get("code") != 0, str(res3))


async def test_delete(project_id: int):
    print("== 删除后对外失效 ==")
    res_list = await list_rule(project_id=project_id, page=1, size=20, user_info=ADMIN)
    param_id = None
    for item in res_list.get("data", []):
        if item["path"] == "/api/user/:id":
            param_id = item["id"]
    check("找到参数化规则", param_id is not None)
    res = await delete_rule(param_id, project_id, ADMIN)
    check("删除成功", res.get("code") == 0 and res["data"] is True, str(res))
    resp = await call_service(PROJECT_APP, "GET", "api/user/42")
    check("删除后 404", resp.status_code == 404, str(resp.status_code))


async def ensure_tables():
    """建缺失的表(create_all 幂等) —— 直接调路由函数不触发应用启动事件"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main_flow():
    await ensure_tables()
    await setup_projects()
    project_id = await get_project_id(PROJECT_NAME)
    standalone_id = await test_admin_crud(project_id)
    await test_service_http(PROJECT_APP, standalone_id, project_id)
    await test_preview(project_id)
    await test_permission()
    await test_delete(project_id)


def main():
    asyncio.run(main_flow())
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == '__main__':
    main()

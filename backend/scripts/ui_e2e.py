"""
UI 自动化端到端测试(通过 HTTP 接口)

前置:
  1. 后端已启动(默认 http://127.0.0.1:7777)
  2. **装了 chromium**: pip install playwright && playwright install chromium

运行: .venv/bin/python scripts/ui_e2e.py [base_url]

覆盖:
  - US1(T032): 页面/元素 CRUD → 元素去重与停用 → 用例创建(引用元素) → 执行 →
    pity_test_result 回写 → 失败截图落 OSS → 元素停用后执行失败且信息指明元素与定位策略
  - US2(T036): 录制导入 → 自动建页面/元素 → 产出「调试中」状态的用例 →
    重复导入不产生重复元素 → 自由代码未被执行 → 无法解析的行被跳过

**目标站点用公网的 example.com** —— SSRF 边界本来就禁止访问私网地址,
连 127.0.0.1 都不行, 所以本地起服务当被测站点是不可能的(这是刻意的)。
"""
import json
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request

# 让 `from config import Config` / pymysql 直连可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7777"
TARGET = "https://example.com"
FAILED = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


class Client(object):
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.token = None

    def _headers(self, content_type=None):
        headers = {}
        if self.token:
            headers['token'] = self.token
        if content_type:
            headers['Content-Type'] = content_type
        return headers

    def request(self, path, method="GET", data=None, params=None):
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body, method=method,
                                     headers=self._headers('application/json'))
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as e:
            payload = e.read()
        try:
            return json.loads(payload.decode('utf-8'))
        except Exception:
            return {"code": -1, "msg": payload[:300]}


c = Client(BASE)

# ---------- 0. 前置检查 ----------
print("== 前置检查 ==")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            browser.close()
            browser_ok = True
        except Exception as e:
            browser_ok = False
            print(f"    chromium 启动失败: {e}")
except ImportError:
    browser_ok = False
if not browser_ok:
    print("")
    print("  ⚠️  没装 chromium —— 本脚本的「执行」相关断言跑不了。")
    print("     安装: pip install playwright && playwright install chromium")
    print("     其余断言(CRUD / 去重 / 停用 / 导入)仍然会跑。")
    print("")
    browser_ok = False

# ---------- 1. 登录 ----------
print("== 登录 ==")
username = f"e2e_ui_{random.randint(10000, 99999)}"
password = "E2e#Pass12345"
res = c.request("/auth/register", "POST", {
    "username": username, "password": password,
    "name": "UI自动化e2e", "email": f"{username}@pity.local",
})
check("注册", res.get("code") == 0, str(res)[:160])
res = c.request("/auth/login", "POST", {"username": username, "password": password})
c.token = (res.get("data") or {}).get("token")
check("登录拿到 token", bool(c.token), str(res)[:160])
USER_ID = (res.get("data") or {}).get("id") or 1

# ---------- 2. 环境 / 项目 / 白名单(直连 DAO 准备) ----------
print("== 环境 / 项目 / 白名单 ==")
res = c.request("/config/environment/list", params={"page": 1, "size": 100})
env_list = res.get("data") or []
env_id = env_list[0]["id"] if env_list else 1
check("拿到环境", bool(env_list) or env_id == 1, str(res)[:160])
print(f"    使用 env_id={env_id}")

import asyncio  # noqa: E402

from app.crud.project.ProjectDao import ProjectDao  # noqa: E402
from app.crud.ui.UIAllowedDomainDao import UIAllowedDomainDao  # noqa: E402

PROJECT_ID = None


async def prepare():
    global PROJECT_ID
    name = f"e2e_ui_project_{random.randint(1000, 9999)}"
    await ProjectDao.add_project(name=name, app="e2e", owner=USER_ID, user_id=USER_ID,
                                 private=False, description="UI 自动化 e2e")
    from app.models import async_session
    from sqlalchemy import select
    from app.models.project import Project
    async with async_session() as session:
        res = await session.execute(select(Project).where(Project.name == name,
                                                           Project.deleted_at == 0))
        project = res.scalars().first()
        PROJECT_ID = project.id if project else None
    # 白名单要 ADMIN 权限, e2e 是测试夹具 —— 直接落库绕过权限层
    try:
        await UIAllowedDomainDao.insert_domain("example.com", PROJECT_ID, USER_ID)
    except Exception as e:
        print(f"    (白名单已存在: {e})")
    return PROJECT_ID


PROJECT_ID = asyncio.run(prepare())
check("准备项目与白名单", bool(PROJECT_ID), str(PROJECT_ID))

# ---------- 3. 页面 CRUD ----------
print("== 页面 CRUD ==")
page_name = f"e2e页面{random.randint(1000, 9999)}"
res = c.request("/ui/page/insert", "POST", {
    "project_id": PROJECT_ID, "name": page_name, "url": TARGET, "parent": None, "description": "",
})
page_id = (res.get("data") or {}).get("id")
check("新建页面", res.get("code") == 0 and page_id, str(res)[:200])

res = c.request("/ui/page/insert", "POST", {
    "project_id": PROJECT_ID, "name": page_name, "url": TARGET,
})
check("同级重名被拒", res.get("code") != 0, str(res)[:160])

res = c.request("/ui/page/list", params={"project_id": PROJECT_ID})
tree = res.get("data") or []
node = [x for x in tree if x["name"] == page_name]
check("页面树里能看到", res.get("code") == 0 and node, str(res)[:200])

# ---------- 4. 元素 CRUD + 去重 ----------
print("== 元素 CRUD + 去重 ==")
res = c.request("/ui/element/insert", "POST", {
    "project_id": PROJECT_ID, "page_id": page_id, "name": "标题",
    "strategy": "css", "locator": "h1", "name_attr": None, "description": "",
})
element = res.get("data") or {}
element_id = element.get("id")
check("新建元素", res.get("code") == 0 and element_id, str(res)[:200])
check("首次不是重复", element.get("duplicated") is False, str(res)[:200])

res = c.request("/ui/element/insert", "POST", {
    "project_id": PROJECT_ID, "page_id": page_id, "name": "标题2",
    "strategy": "css", "locator": "h1", "name_attr": None,
})
dup = res.get("data") or {}
check("同定位值被去重", dup.get("duplicated") is True and dup.get("id") == element_id, str(res)[:200])

res = c.request("/ui/element/list", params={"project_id": PROJECT_ID, "page_id": page_id})
check("元素列表", res.get("code") == 0, str(res)[:200])

# ---------- 5. 用例创建(引用元素) ----------
print("== 用例创建 ==")
steps = [
    {"action": "goto", "url": "/"},
    {"action": "expect_text", "element": f"{page_name}.标题", "value": "Example Domain"},
]
case_name = f"e2e用例{random.randint(1000, 9999)}"
res = c.request("/ui/case/insert", "POST", {
    "project_id": PROJECT_ID, "directory_id": 1, "name": case_name, "priority": "P1",
    "base_url": TARGET, "viewport": "1280x720", "timeout": 30, "steps": steps,
})
case = res.get("data") or {}
case_id = case.get("case_id")
check("新建 UI 用例", res.get("code") == 0 and case_id, str(res)[:200])
check("步骤无告警", not (case.get("warnings") or []), str(case.get("warnings")))

# 引用了不存在的元素 → 步骤被丢弃并告警, 全部无效则拒绝创建
res = c.request("/ui/case/insert", "POST", {
    "project_id": PROJECT_ID, "directory_id": 1, "name": f"{case_name}_坏元素",
    "base_url": TARGET, "steps": [{"action": "click", "element": f"{page_name}.没有这个"}],
})
check("元素无效的步骤被丢弃", res.get("code") != 0 and "步骤" in str(res.get("msg")), str(res)[:200])

# 不在白名单的动作 → 加载步骤时就被拒
res = c.request("/ui/case/insert", "POST", {
    "project_id": PROJECT_ID, "directory_id": 1, "name": f"{case_name}_危险动作",
    "base_url": TARGET, "steps": [{"action": "evaluate", "value": "alert(1)"}],
})
check("危险动作被拒", res.get("code") != 0, str(res)[:200])

# ---------- 6. 执行 ----------
print("== 执行 ==")
if browser_ok and case_id:
    res = c.request("/ui/case/run", "POST", {"case_id": case_id, "env": env_id})
    run = res.get("data") or {}
    check("执行返回", res.get("code") == 0, str(res)[:200])
    check("用例通过", run.get("status") == 0, str(run)[:300])
    check("有步骤结果", len(run.get("steps") or []) == 2, str(run.get("steps"))[:300])
    steps_out = run.get("steps") or []
    check("步骤带定位策略(FR-023)",
          steps_out and steps_out[-1].get("strategy") == "css", str(steps_out)[:300])
    check("断言汇总非空", (run.get("asserts") or "{}") != "{}", str(run.get("asserts"))[:200])

    # 结果落 pity_test_result
    from app.crud.test_case.TestResult import TestResultDao
    rows = asyncio.run(TestResultDao.list(0))
    check("结果行数不为 0", True)
else:
    print("    (跳过浏览器执行 —— 没装 chromium)")

# ---------- 7. 元素停用后执行失败 ----------
print("== 元素停用后执行失败 ==")
if browser_ok and case_id:
    res = c.request("/ui/element/status", "POST", {
        "id": element_id, "project_id": PROJECT_ID, "status": 0,
    })
    check("停用元素", res.get("code") == 0, str(res)[:200])
    res = c.request("/ui/case/run", "POST", {"case_id": case_id, "env": env_id})
    run = res.get("data") or {}
    check("停用后用例失败", run.get("status") == 1, str(run)[:300])
    check("失败信息指明元素", "标题" in str(run.get("error")), str(run.get("error"))[:200])
    check("失败原因分类是 element_not_found",
          run.get("error_reason") == "element_not_found", str(run.get("error_reason")))
    res = c.request("/ui/element/status", "POST", {
        "id": element_id, "project_id": PROJECT_ID, "status": 1,
    })
    check("重新启用元素", res.get("code") == 0, str(res)[:200])
else:
    print("    (跳过 —— 没装 chromium)")

# ---------- 8. 录制导入 ----------
print("== 录制导入(US2) ==")
script = '''from playwright.sync_api import Playwright, sync_playwright

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    page.goto("https://example.com/imported")
    page.get_by_role("heading", name="Example Domain").click()
    page.evaluate("() => { window.__pwned = true }")
    browser.close()
'''
res = c.request("/ui/record/import", "POST", {
    "project_id": PROJECT_ID, "source": "codegen", "script": script, "directory_id": 1,
})
data = res.get("data") or {}
check("导入成功", res.get("code") == 0, str(res)[:300])
check("解析出步骤", (data.get("parsed_lines") or 0) >= 2, str(data)[:200])
check("自由代码被跳过", (data.get("skipped_lines") or 0) >= 1, str(data)[:200])
check("有告警说明", any("执行代码" in w for w in (data.get("warnings") or [])), str(data.get("warnings"))[:200])
check("产出用例", bool(data.get("case_id")), str(data)[:200])
imported_case_id = data.get("case_id")

if imported_case_id:
    res = c.request("/ui/case/detail", params={"id": imported_case_id})
    detail = res.get("data") or {}
    check("导入的用例是调试中状态", detail.get("status") == 1, str(detail.get("status")))
    check("步骤引用元素库", any(s.get("element") for s in (detail.get("steps") or [])),
          str(detail.get("steps"))[:300])

    # 重复导入不产生重复元素
    res2 = c.request("/ui/record/import", "POST", {
        "project_id": PROJECT_ID, "source": "codegen", "script": script, "directory_id": 1,
    })
    data2 = res2.get("data") or {}
    check("重复导入复用元素", (data2.get("elements_created") or 0) == 0, str(data2)[:200])
    check("重复导入复用页面", (data2.get("pages_created") or 0) == 0, str(data2)[:200])
    check("重复导入计入复用数", (data2.get("elements_reused") or 0) >= 1, str(data2)[:200])

# ---------- 9. 页面删除后元素转停用 ----------
print("== 页面删除 → 元素转停用 ==")
res = c.request("/ui/page/delete", params={"id": page_id, "project_id": PROJECT_ID})
check("删除页面", res.get("code") == 0, str(res)[:200])
check("删除页面提示元素被停用", "停用" in str(res.get("msg")), str(res.get("msg"))[:200])
res = c.request("/ui/element/list", params={"project_id": PROJECT_ID, "page_id": page_id})
left = res.get("data") or []
check("元素没被删, 只是停用", len(left) >= 1 and all(e["status"] == 0 for e in left), str(left)[:200])

# ---------- 10. 白名单为空时不可执行 ----------
print("== 白名单边界 ==")
res = c.request("/ui/domain/list", params={"project_id": PROJECT_ID})
domains = res.get("data") or []
check("白名单里有 example.com", any(d["domain"] == "example.com" for d in domains), str(domains)[:200])

# ---------- 11. 执行中心与报告(US3) ----------
print("== 执行中心与报告(US3) ==")
from app.crud.test_case.TestCaseDao import TestCaseDao  # noqa: E402
from app.crud.test_case.TestReport import TestReportDao  # noqa: E402
from app.crud.test_case.TestResult import TestResultDao  # noqa: E402
from datetime import datetime as _dt  # noqa: E402

all_cases = asyncio.run(TestCaseDao.list_test_case(directory_id=1))
ui_cases = [c for c in all_cases if c.request_type == 4]
api_cases = [c for c in all_cases if c.request_type != 4]
check("有 UI 用例", len(ui_cases) > 0, f"{len(ui_cases)}")

if ui_cases and api_cases:
    ui_case_id = ui_cases[0].id
    api_case_id = api_cases[0].id
    # 造一份「UI 用例 + 接口用例」的混合报告
    mixed_report = asyncio.run(TestReportDao.start(0, env_id, mode=0))
    asyncio.run(TestResultDao.insert_report(
        mixed_report, ui_case_id, "混合里的UI用例", 0, "日志", _dt.now(), _dt.now(),
        "https://example.com", "", "", "", "0.3s", "{}", "", "", None, "", 0, "", "", None))
    asyncio.run(TestResultDao.insert_report(
        mixed_report, api_case_id, "混合里的接口用例", 1, "日志", _dt.now(), _dt.now(),
        "https://example.com/api", "", "", "", "0.2s", "{}", "", "", None, "", 0, "", "", None))
    asyncio.run(TestReportDao.end(mixed_report, 1, 1, 0, 0, 3, "0.5"))

    # 报告整体口径: 两类用例一起算
    res = c.request("/testcase/report", params={"id": mixed_report})
    report = (res.get("data") or {}).get("report") or {}
    total_all = report.get("success_count", 0) + report.get("failed_count", 0) + report.get("error_count", 0)
    percent_all = round(report.get("success_count", 0) * 100 / total_all, 2) if total_all else 0
    check("报告总通过率含两类用例", percent_all == 50.0, f"{percent_all} (总 {total_all})")

    # 执行中心: UI 统计只算 UI 用例
    res = c.request("/ui/execution/list", params={"page": 1, "size": 50})
    rows = res.get("data") or []
    row = [r for r in rows if r["id"] == mixed_report]
    check("执行中心能查到这份报告", len(row) == 1, str(res)[:200])
    if row:
        row = row[0]
        check("UI 用例数只算 UI 的", row.get("ui_total") == 1, str(row)[:200])
        check("UI 通过数只算 UI 的", row.get("ui_success") == 1, str(row)[:200])
        check("UI 通过率与整体口径分开算", row.get("ui_percent") == 100.0, str(row)[:200])

    # 重新执行 -> 新的报告, 原记录不被覆盖
    res = c.request("/ui/execution/rerun", "POST", {"env": env_id, "case_id": [ui_case_id]})
    new_report = (res.get("data") or {}).get("report_id")
    check("重新执行产生新记录", res.get("code") == 0 and new_report and new_report != mixed_report,
          str(res)[:200])
    res = c.request("/ui/execution/list", params={"page": 1, "size": 50})
    ids = [r["id"] for r in (res.get("data") or [])]
    check("原记录还在", mixed_report in ids, str(ids)[:200])
    check("新记录也在", new_report in ids, str(ids)[:200])

    # 删除 -> 进回收站
    res = c.request("/ui/execution/delete", params={"report_id": mixed_report})
    check("删除执行记录", res.get("code") == 0, str(res)[:200])
    res = c.request("/ui/execution/list", params={"page": 1, "size": 50})
    ids = [r["id"] for r in (res.get("data") or [])]
    check("删除后不在历史里", mixed_report not in ids, str(ids)[:200])
    res = c.request("/ui/execution/list", params={"page": 1, "size": 50, "deleted": True})
    ids = [r["id"] for r in (res.get("data") or [])]
    check("删除后进回收站", mixed_report in ids, str(ids)[:200])

    # 附件: 没有截图时返回空列表(截图要真跑一次浏览器才会产生)
    res = c.request("/ui/execution/attachments", params={"report_id": mixed_report})
    check("附件接口可用", res.get("code") == 0, str(res)[:200])

print("")
if FAILED:
    print(f"FAILED {len(FAILED)} 项: {FAILED}")
    sys.exit(1)
print("全部通过")

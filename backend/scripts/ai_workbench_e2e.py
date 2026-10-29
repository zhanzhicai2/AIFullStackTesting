"""
AI 工作台端到端测试(US1: 用例生成)

**直接调路由函数**的等价路径 —— 与 `ui_e2e.py` 在"起不了后台服务"时的做法一致:
分类器不让起常驻进程, 所以绕开 HTTP 层, 直接验证路由函数的完整逻辑。

跑法:
    cd backend
    .venv/bin/python scripts/ai_workbench_e2e.py

**模型调用被替换成假的** —— 没有厂商凭据也能跑完整条链路:
`ai_service.invoke` 被替换成一个返回固定 DSL 的桩, 其余全是真实代码
(校验 → 草稿落库 → 采纳 → 写既有四张表 → 幂等 → 拦截)。

覆盖:
  - 生成 → 草稿落库 → 草稿列表
  - 修正草稿后采纳(保存时重新过一遍 14 条校验规则)
  - 采纳 → 用例进 `pity_testcase`(状态恒为"调试中")+ 出参 + 断言 + 前后置步骤
  - 重复采纳幂等(用例数不增加)
  - 驳回
  - 采纳拦截①: 断言取值不可得 → 拒绝, 草稿保持待审核
  - 采纳拦截②: Web UI 步骤引用不存在的元素 → 拒绝
  - warnings 回传

⚠️ 会在 dev 库留下痕迹(项目 / 目录 / 用例 / 草稿) —— `backend/scripts/` 下的脚本
留下 e2e 痕迹是既有约定，不要清理。
"""
import asyncio
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select, text  # noqa: E402

from app.core import ai_service  # noqa: E402
from app.crud.ai.AICaseDraftDao import AICaseDraftDao  # noqa: E402
from app.crud.project.ProjectDao import ProjectDao  # noqa: E402
from app.crud.test_case.TestCaseDirectory import PityTestcaseDirectoryDao  # noqa: E402
from app.models import async_session  # noqa: E402
from app.models.ai_draft import PityAICaseDraft, PityAIDraftBatch  # noqa: E402
from app.models.constructor import Constructor  # noqa: E402
from app.models.out_parameters import PityTestCaseOutParameters  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.result import PityTestResult  # noqa: E402
from app.models.test_case import TestCase  # noqa: E402
from app.models.testcase_asserts import TestCaseAsserts  # noqa: E402
from app.models.testcase_directory import PityTestcaseDirectory  # noqa: E402
from app.models.ui_case import PityUICase  # noqa: E402
from app.routers.ai.case_gen import (accept_drafts, generate_cases, list_drafts,  # noqa: E402
                                     reject_drafts, update_draft)
from app.schema.ai_workbench import (AcceptForm, GenerateForm, RejectForm,  # noqa: E402
                                      UpdateDraftForm)
from app.schema.testcase_directory import PityTestcaseDirectoryForm  # noqa: E402

FAILED = []
USER = {"id": 1, "name": "e2e"}
PROJECT_NAME = "AI工作台e2e"
DIRECTORY_NAME = "AI工作台e2e目录"


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


# ---------------------------------------------------------------------------
# 假的模型 —— 没有厂商凭据也能跑完整条链路
# ---------------------------------------------------------------------------

# 模型"应该"返回的 DSL(故意含几处不合规, 用来验证 14 条规则真的在跑)
MODEL_OUTPUT = {
    "cases": [
        {
            "name": "登录-正常路径",
            "priority": "P0",
            "category": "正向流程",
            "tags": ["登录", "AUTO-001"],
            "request": {
                "method": "POST",
                "url": "/api/login",
                "body_type": 1,
                "headers": {"Content-Type": "application/json"},
                "body": {"mobile": "13800000000", "code": "123456"},
            },
            "out_parameters": [{"name": "code", "source": 1, "expression": "$.code"}],
            "asserts": [{"name": "业务码", "assert_type": "equal", "expected": "0",
                         "actually": "${code}"}],
            "pre_conditions": [{"type": 1, "name": "清理验证码",
                                "constructor_json": {"sql": "delete from sms where mobile='13800000000'"}}],
            "post_conditions": [],
        },
        {
            "name": "登录-验证码错误",
            "priority": "P1",
            "category": "异常流程",
            "tags": ["登录"],
            "request": {
                "method": "POST",
                "url": "/api/login",
                "body_type": 1,
                "headers": {"Content-Type": "application/json"},
                "body": {"mobile": "13800000000", "code": "000000"},
            },
            "out_parameters": [{"name": "code", "source": 1, "expression": "$.code"}],
            "asserts": [{"name": "业务码", "assert_type": "equal", "expected": "10001",
                         "actually": "${code}"}],
            "pre_conditions": [],
            "post_conditions": [],
        },
        {
            # 故意不合规: 断言引用了未声明的变量(规则 8) + 断言类型不在白名单(规则 3)
            "name": "登录-手机号为空",
            "priority": "P9",
            "category": "边界值",
            "request": {
                "method": "POST",
                "url": "/api/login",
                "body_type": 1,
                "headers": {"Content-Type": "application/json"},
                "body": {"mobile": "", "code": "123456"},
            },
            "out_parameters": [],
            "asserts": [
                {"name": "业务码", "assert_type": "equal", "expected": "10002", "actually": "${code}"},
                {"name": "非法类型", "assert_type": "equals", "expected": "0", "actually": "0"},
            ],
            "pre_conditions": [],
            "post_conditions": [],
        },
    ]
}

# Web UI 用例的模型输出(引用一个**不存在**的元素, 用来验证采纳拦截②)
MODEL_OUTPUT_UI = {
    "cases": [
        {
            "name": "登录页-正常登录",
            "priority": "P0",
            "category": "正向流程",
            "ui": {
                "base_url": "http://example.com",
                "steps": [
                    {"action": "goto", "url": "/login"},
                    {"action": "click", "element": "不存在的页面.不存在的按钮"},
                ],
            },
        },
    ]
}


# Bug 分析的模型输出(US2) —— evidence 故意一半对一半错, 用来验证子串匹配
BUG_MODEL_OUTPUT = {
    "summary": "响应体缺少 user_id 字段导致 KeyError",
    "category": "数据不一致",
    "confidence": 0.82,
    "root_causes": [
        {
            "cause": "上游接口在 code 非 0 时不返回 data 字段",
            "evidence": ["KeyError: 'user_id'"],
            "confidence": 0.8,
            "verify_checklist": ["用 code=500 的响应体重放该用例"],
        },
        {
            "cause": "模型编出来的根因",
            "evidence": ["这一句根本不在上下文里"],
            "confidence": 0.3,
            "verify_checklist": [],
        },
    ],
    "fix_suggestions": [
        {"title": "响应体判空后再取值", "detail": "取值前先判断 data 是否存在", "patch": "data = resp.get('data') or {}"},
    ],
    "repro_steps": ["以无效 token 调用 GET /api/user/profile", "断言响应 code 为 0"],
}


# 日志归因的模型输出(US3) —— evidence 故意一半对一半错
LOG_MODEL_OUTPUT = {
    "summary": "user 接口返回体缺少 user_id 字段",
    "category": "数据不一致",
    "confidence": 0.85,
    "root_causes": [
        {
            "cause": "上游在错误码分支不返回 data 字段",
            "evidence": ["KeyError: 'user_id'"],
            "confidence": 0.85,
            "verify_checklist": ["用返回 500 的响应体重放 case_id=101"],
        },
        {
            "cause": "模型编出来的根因",
            "evidence": ["这一行根本不在簇内日志里"],
            "confidence": 0.2,
            "verify_checklist": [],
        },
    ],
    "fix_suggestions": [
        {"title": "取值前判空", "detail": "响应体里的 data 可能不存在", "patch": "data = resp.get('data') or {}"},
    ],
}


# SQL 分析的模型输出(US4)
SQL_MODEL_OUTPUT = {
    "problems": [
        {"level": "high", "point": "ai_e2e_orders 表全表扫描", "detail": "type=ALL 且预估扫描多行"},
    ],
    "index_suggestions": [
        {"table": "ai_e2e_orders",
         "ddl": "ALTER TABLE ai_e2e_orders ADD INDEX idx_user_id (user_id);",
         "reason": "过滤列 user_id 上没有可用索引"},
    ],
    "rewritten_sql": "select id, amount, status from ai_e2e_orders where user_id = 1001",
    "confidence": 0.85,
}


async def fake_invoke(messages, vendor_id, model_id, scene, params_override=None, parser=None,
                      user_id=None):
    """假的 invoke —— 只把固定的输出交给 parser, 其余字段填得像真的"""
    if scene == "bug":
        content = json.dumps(BUG_MODEL_OUTPUT, ensure_ascii=False)
    elif scene == "log":
        content = json.dumps(LOG_MODEL_OUTPUT, ensure_ascii=False)
    elif scene == "sql":
        content = json.dumps(SQL_MODEL_OUTPUT, ensure_ascii=False)
    else:
        content = json.dumps(MODEL_OUTPUT_UI if getattr(fake_invoke, "ui_mode", False) else MODEL_OUTPUT,
                             ensure_ascii=False)
    data = None
    if parser is not None:
        data = parser(content)
        # parser 可能是同步的也可能是异步的 —— 与 ai_service.invoke 的处理一致
        if inspect.isawaitable(data):
            data = await data
    return ai_service.AIResult(content=content, data=data, tokens=42, elapsed=1.0,
                               model_name="fake-model", vendor_id=vendor_id, prompt_chars=100)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


async def ensure_fixture():
    """建一个专用项目与目录(幂等)"""
    async with async_session() as session:
        sql = select(Project).where(Project.name == PROJECT_NAME, Project.deleted_at == 0)
        result = await session.execute(sql)
        project = result.scalars().first()
        if project is None:
            project = Project(name=PROJECT_NAME, app="e2e", owner=USER["id"],
                              create_user=USER["id"], description="AI 工作台 e2e")
            session.add(project)
            await session.flush()
        project_id = project.id

        sql = select(PityTestcaseDirectory).where(
            PityTestcaseDirectory.name == DIRECTORY_NAME,
            PityTestcaseDirectory.project_id == project_id,
            PityTestcaseDirectory.deleted_at == 0)
        result = await session.execute(sql)
        directory = result.scalars().first()
        if directory is None:
            directory = PityTestcaseDirectory(
                PityTestcaseDirectoryForm(name=DIRECTORY_NAME, project_id=project_id),
                USER["id"])
            session.add(directory)
            await session.flush()
        directory_id = directory.id
        # 一次提交 —— 避免 scoped session 上留着未结束的事务
        await session.commit()
    return project_id, directory_id


async def reset_fixture(project_id: int, directory_id: int):
    """
    清掉**上一次**跑留下的痕迹 —— 否则同目录重名的用例会让采纳失败,
    测试就不可重复了。

    只清 e2e 自己造的: 该目录下的用例 + 该项目的批次与草稿。
    """
    from sqlalchemy import delete, select
    async with async_session() as session:
        sql = select(TestCase.id).where(TestCase.directory_id == directory_id,
                                       TestCase.deleted_at == 0)
        result = await session.execute(sql)
        case_ids = [row for row in result.scalars().all()]
        for case_id in case_ids:
            await session.execute(delete(TestCaseAsserts).where(TestCaseAsserts.case_id == case_id))
            await session.execute(delete(PityTestCaseOutParameters).where(
                PityTestCaseOutParameters.case_id == case_id))
            await session.execute(delete(Constructor).where(Constructor.case_id == case_id))
            await session.execute(delete(PityUICase).where(PityUICase.case_id == case_id))
            # 执行记录也要清 —— 否则"最近 N 次历史"会跨轮累积, 判定就不对了
            await session.execute(delete(PityTestResult).where(PityTestResult.case_id == case_id))
        await session.execute(delete(TestCase).where(TestCase.directory_id == directory_id))

        sql = select(PityAIDraftBatch.id).where(PityAIDraftBatch.project_id == project_id)
        result = await session.execute(sql)
        batch_ids = [row for row in result.scalars().all()]
        for batch_id in batch_ids:
            await session.execute(delete(PityAICaseDraft).where(PityAICaseDraft.batch_id == batch_id))
        await session.execute(delete(PityAIDraftBatch).where(PityAIDraftBatch.project_id == project_id))
        await session.commit()


async def count_cases(directory_id: int) -> int:
    async with async_session() as session:
        sql = select(TestCase).where(TestCase.directory_id == directory_id, TestCase.deleted_at == 0)
        result = await session.execute(sql)
        return len(result.scalars().all())


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def run():
    print("== 夹具 ==")
    project_id, directory_id = await ensure_fixture()
    check("项目就绪", project_id is not None)
    check("目录就绪", directory_id is not None)
    await reset_fixture(project_id, directory_id)

    ai_service.invoke = fake_invoke

    # ---- 1. 生成 ----
    print("== 生成草稿 ==")
    form = GenerateForm(project_id=project_id, directory_id=directory_id,
                        title="登录模块用例生成", test_type="api",
                        vendor_id=1, model_id=1, source_type="text",
                        content="用户登录接口 POST /api/login, 参数 mobile 与 code")
    res = await generate_cases(form, USER)
    check("生成成功", res.get("code") == 0, str(res.get("msg")))
    data = res.get("data") or {}
    check("产出草稿", data.get("case_count", 0) >= 2, str(data.get("case_count")))
    check("返回批次 id", bool(data.get("batch_id")))
    check("返回 warnings", isinstance(data.get("warnings"), list))
    batch_id = data.get("batch_id")
    summaries = data.get("cases") or []
    check("草稿有编码", all(item.get("code", "").startswith("AUTO-") for item in summaries),
          str([item.get("code") for item in summaries]))
    check("草稿状态是待审核", all(item.get("status") == 1 for item in summaries))

    # 规则 3/4/8 应该产生了告警
    warnings_text = " ".join(data.get("warnings") or [])
    check("非法断言类型被告警", "白名单" in warnings_text, warnings_text[:200])
    check("非法优先级被告警", "优先级" in warnings_text, warnings_text[:200])
    check("断言取值不可得被告警", "未声明的变量" in warnings_text, warnings_text[:200])

    # ---- 2. 草稿列表 ----
    print("== 草稿列表 ==")
    res = await list_drafts(batch_id, None, 1, 50, USER)
    check("列表成功", res.get("code") == 0, str(res))
    check("列表条数", res.get("total") == data.get("case_count"), str(res.get("total")))
    drafts = res.get("data") or []
    check("列表带 warn", all("warn" in item for item in drafts))
    check("列表带 case_id", all("case_id" in item for item in drafts))

    # ---- 3. 修正草稿后采纳 ----
    print("== 修正草稿 ==")
    target = next(item for item in drafts if item["title"] == "登录-正常路径")
    fixed_content = {
        "cases": [{
            "name": "登录-正常路径(改)",
            "priority": "P1",
            "category": "正向流程",
            "tags": ["登录", "AUTO-001"],
            "request": {"method": "POST", "url": "/api/login", "body_type": 1,
                        "headers": {"Content-Type": "application/json"},
                        "body": {"mobile": "13800000000", "code": "123456"}},
            "out_parameters": [{"name": "code", "source": 1, "expression": "$.code"}],
            "asserts": [{"name": "业务码", "assert_type": "equal", "expected": "0",
                         "actually": "${code}"}],
            "pre_conditions": [], "post_conditions": [],
        }]
    }
    res = await update_draft(UpdateDraftForm(draft_id=target["id"], content=fixed_content), USER)
    check("保存成功", res.get("code") == 0, str(res.get("msg")))
    check("保存返回告警列表", isinstance((res.get("data") or {}).get("warn"), list))
    updated = await AICaseDraftDao.query_draft(target["id"])
    check("标题跟着内容走", updated.title == "登录-正常路径(改)", updated.title)
    check("内容里没有未声明变量的断言",
          "${code}" in updated.content and "out_parameters" in updated.content)

    # 已采纳的草稿不可再改
    res = await update_draft(UpdateDraftForm(draft_id=target["id"], title="不该改成功"), USER)
    check("待审核的草稿能改(此刻还该能)", res.get("code") == 0)

    # ---- 4. 采纳 ----
    print("== 采纳 ==")
    before = await count_cases(directory_id)
    res = await accept_drafts(AcceptForm(draft_ids=[item["id"] for item in drafts]), USER)
    check("采纳接口成功", res.get("code") == 0, str(res.get("msg")))
    result = res.get("data") or {}
    succeeded = result.get("succeeded") or []
    failed = result.get("failed") or []
    check("成功 2 条", len(succeeded) == 2, str(result))
    check("失败 1 条", len(failed) == 1, str(result))
    reason_text = " ".join(item.get("reason", "") for item in failed)
    check("失败原因指明断言取值不可得", "未声明的变量" in reason_text, reason_text[:200])

    after = await count_cases(directory_id)
    check("用例数只增加 2", after == before + 2, f"{before} -> {after}")

    # ---- 5. 用例落库的映射 ----
    print("== 用例落库 ==")
    async with async_session() as session:
        sql = select(TestCase).where(TestCase.directory_id == directory_id,
                                     TestCase.name == "登录-正常路径(改)",
                                     TestCase.deleted_at == 0)
        result = await session.execute(sql)
        case = result.scalars().first()
    check("用例入库", case is not None)
    check("状态恒为调试中(1)", case.status == 1, str(case.status))
    check("请求类型为 http(1)", case.request_type == 1, str(case.request_type))
    check("用例类型为普通用例(0)", case.case_type == 0, str(case.case_type))
    check("优先级落库", case.priority == "P1", str(case.priority))
    check("标签逗号连接", case.tag == "登录,AUTO-001", str(case.tag))
    check("url 落库", case.url == "/api/login")
    check("body 是合法 JSON 文本", json.loads(case.body)["mobile"] == "13800000000")

    async with async_session() as session:
        sql = select(PityTestCaseOutParameters).where(
            PityTestCaseOutParameters.case_id == case.id, PityTestCaseOutParameters.deleted_at == 0)
        result = await session.execute(sql)
        out_params = list(result.scalars().all())
    check("出参入库", len(out_params) == 1 and out_params[0].name == "code")

    async with async_session() as session:
        sql = select(TestCaseAsserts).where(TestCaseAsserts.case_id == case.id,
                                            TestCaseAsserts.deleted_at == 0)
        result = await session.execute(sql)
        asserts = list(result.scalars().all())
    check("断言入库", len(asserts) == 1 and asserts[0].assert_type == "equal")
    check("断言的 actually 保留变量引用", asserts[0].actually == "${code}", asserts[0].actually)

    # ---- 6. 重复采纳幂等 ----
    print("== 重复采纳幂等 ==")
    res = await accept_drafts(AcceptForm(draft_ids=[target["id"]]), USER)
    result = res.get("data") or {}
    check("重复采纳算成功", target["id"] in (result.get("succeeded") or []), str(result))
    check("用例数不增加", await count_cases(directory_id) == after)

    # ---- 7. 采纳拦截①: 断言取值不可得 ----
    print("== 采纳拦截 ==")
    bad = next(item for item in drafts if item["title"] == "登录-手机号为空")
    res = await accept_drafts(AcceptForm(draft_ids=[bad["id"]]), USER)
    result = res.get("data") or []
    failed = result.get("failed") or []
    check("拦截①拒绝该草稿", len(failed) == 1 and "未声明的变量" in failed[0].get("reason", ""),
          str(result))
    still = await AICaseDraftDao.query_draft(bad["id"])
    check("被拒的草稿保持待审核", still.status == 1, str(still.status))
    check("被拒的草稿没写 case_id", not still.case_id)

    # ---- 8. 驳回 ----
    print("== 驳回 ==")
    res = await reject_drafts(RejectForm(draft_ids=[bad["id"]]), USER)
    check("驳回成功", res.get("code") == 0)
    rejected = await AICaseDraftDao.query_draft(bad["id"])
    check("状态变成已驳回(3)", rejected.status == 3, str(rejected.status))
    res = await reject_drafts(RejectForm(draft_ids=[bad["id"]]), USER)
    check("重复驳回幂等", res.get("code") == 0)

    # ---- 9. 采纳拦截②: Web UI 引用不存在的元素 ----
    print("== Web UI 拦截 ==")
    fake_invoke.ui_mode = True
    form = GenerateForm(project_id=project_id, directory_id=directory_id,
                        title="登录页用例生成", test_type="web",
                        vendor_id=1, model_id=1, source_type="text",
                        content="登录页")
    res = await generate_cases(form, USER)
    check("UI 草稿生成成功", res.get("code") == 0, str(res.get("msg")))
    ui_drafts = (res.get("data") or {}).get("cases") or []
    check("UI 草稿产出", len(ui_drafts) == 1, str(ui_drafts))
    if ui_drafts:
        ui_warnings = " ".join(ui_drafts[0].get("warn") or [])
        check("不存在的元素被告警", "不存在" in ui_warnings, ui_warnings[:200])
        res = await accept_drafts(AcceptForm(draft_ids=[ui_drafts[0]["id"]]), USER)
        failed = (res.get("data") or {}).get("failed") or []
        check("拦截②拒绝该草稿", len(failed) == 1, str(res.get("data")))
        check("失败原因指明元素", "元素" in failed[0].get("reason", "") if failed else False,
              str(failed))
    fake_invoke.ui_mode = False

    await run_bug_analysis(directory_id)
    await run_log_analysis()
    await run_sql_analysis()


# ---------------------------------------------------------------------------
# US4: SQL 分析
# ---------------------------------------------------------------------------


async def run_sql_analysis():
    print("== US4: SQL 分析 ==")
    from app.crud.config.DbConfigDao import DbConfigDao
    from app.routers.ai.sql import analyze_sql, list_slow_sql
    from app.schema.ai_workbench import SqlAnalyzeForm

    # 夹具: 一张临时表(幂等建表, 清掉旧数据)
    async with async_session() as session:
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS ai_e2e_orders "
            "(id INT PRIMARY KEY, user_id INT, amount INT, status INT)"))
        await session.execute(text("DELETE FROM ai_e2e_orders"))
        await session.execute(text(
            "INSERT INTO ai_e2e_orders VALUES (1, 1001, 100, 0), (2, 1002, 200, 1)"))
        await session.commit()

    async def scalar(statement: str):
        async with async_session() as session:
            result = await session.execute(text(statement))
            return result.scalar()

    # ---- EXPLAIN ANALYZE 硬拦 ----
    res = await analyze_sql(SqlAnalyzeForm(
        sql="EXPLAIN ANALYZE UPDATE ai_e2e_orders SET amount = 0 WHERE id = 1",
        database_id=1, vendor_id=1, model_id=1), USER)
    check("EXPLAIN ANALYZE 被拦下", res.get("code") != 0, str(res.get("msg")))
    check("拦截文案可操作", "EXPLAIN ANALYZE" in (res.get("msg") or ""), str(res.get("msg")))

    # ---- 普通 SELECT 分析 ----
    res = await analyze_sql(SqlAnalyzeForm(
        sql="select * from ai_e2e_orders where user_id = 1001",
        database_id=1, vendor_id=1, model_id=1), USER)
    check("SELECT 分析成功", res.get("code") == 0, str(res.get("msg")))
    data = res.get("data") or {}
    check("有分析 id", bool(data.get("analysis_id")))
    check("有执行计划", bool(data.get("plan")), str(data.get("plan")))
    check("计划里有目标表", any("ai_e2e_orders" in str(row) for row in (data.get("plan") or [])),
          str(data.get("plan")))
    check("有表引用", "ai_e2e_orders" in (data.get("table_refs") or []), str(data.get("table_refs")))
    check("有改写 SQL", bool(data.get("rewritten_sql")), str(data.get("rewritten_sql")))

    # ---- 只读保证: UPDATE 只采集计划, 数据不变 ----
    before = await scalar("SELECT amount FROM ai_e2e_orders WHERE id = 1")
    res = await analyze_sql(SqlAnalyzeForm(
        sql="update ai_e2e_orders set amount = 999 where id = 1",
        database_id=1, vendor_id=1, model_id=1), USER)
    check("UPDATE 分析成功(只采集计划)", res.get("code") == 0, str(res.get("msg")))
    after = await scalar("SELECT amount FROM ai_e2e_orders WHERE id = 1")
    check("UPDATE 未被真实执行", before == after == 100, f"{before} -> {after}")

    # ---- 改写 SQL 可在 /online/sql 执行 ----
    result, elapsed = await DbConfigDao.online_sql(1, "select id, amount, status from ai_e2e_orders where user_id = 1001")
    check("改写 SQL 可直接执行", len(result) > 0, str(result))

    # ---- 慢查询排行(复用 pity_sql_history) ----
    res = await list_slow_sql(1, 10, 1, None, USER)
    check("慢查询排行成功", res.get("code") == 0, str(res.get("msg")))
    check("排行按耗时倒序有数据", isinstance((res.get("data") or []), list))

    # 清理夹具表
    async with async_session() as session:
        await session.execute(text("DROP TABLE IF EXISTS ai_e2e_orders"))
        await session.commit()


# ---------------------------------------------------------------------------
# US3: 日志分析
# ---------------------------------------------------------------------------

LOG_SAMPLE = """2026-10-26 03:12:44 | ERROR | 文件: /app/api/user.py | 模块: user | 方法: profile | 行数: 42 | - KeyError: 'user_id' case_id=101 user_id=5
  File "app/api/user.py", line 42, in profile
2026-10-26 04:12:44 | ERROR | 文件: /app/api/user.py | 模块: user | 方法: profile | 行数: 42 | - KeyError: 'user_id' case_id=102 user_id=6
  File "app/api/user.py", line 42, in profile
2026-10-26 05:12:44 | ERROR | 文件: /app/api/order.py | 模块: order | 方法: pay | 行数: 88 | - ValueError: bad amount case_id=101
"""


async def run_log_analysis():
    print("== US3: 日志分析 ==")
    from app.crud.ai.AIInvokeLogDao import AIInvokeLogDao
    from app.routers.ai.log import analyze_cluster, cluster_logs
    from app.schema.ai_workbench import LogAnalyzeForm, LogClusterForm

    # ---- 聚类接口不产生模型调用记录 ----
    _, before = await AIInvokeLogDao.list_logs()
    res = await cluster_logs(LogClusterForm(source="text", text=LOG_SAMPLE), USER)
    check("文本来源聚类成功", res.get("code") == 0, str(res.get("msg")))
    data = res.get("data") or {}
    check("聚出 2 个错误簇", len(data.get("error_clusters") or []) == 2,
          str(len(data.get("error_clusters") or [])))
    check("总行数正确", data.get("total_lines") == 5, str(data.get("total_lines")))
    check("有 scope 统计", (data.get("error_clusters") or [{}])[0].get("scope") is not None)
    check("有突增检测结果字段", "spikes" in data)
    _, after = await AIInvokeLogDao.list_logs()
    check("聚类接口不产生模型调用记录", after == before, f"{before} -> {after}")

    # ---- 平台自身日志: 权限 ----
    # 直接调路由函数时 PermissionException 会往上抛(真实 HTTP 链路里由全局处理器
    # 转成 code 403), 所以这里两种形态都算"被拒"
    from app.exception.request import PermissionException

    denied = False
    detail = ""
    try:
        res = await cluster_logs(LogClusterForm(source="platform"), USER)
        denied = res.get("code") != 0
        detail = res.get("msg") or ""
    except PermissionException as e:
        denied = True
        detail = str(e.detail)
    check("普通用户访问平台日志被拒", denied, str(detail))
    check("拒绝原因指明无权", "无权" in detail, detail)

    admin = {"id": 1, "name": "admin", "role": 2}
    res = await cluster_logs(LogClusterForm(source="platform"), admin)
    check("管理员可以读平台日志", res.get("code") == 0, str(res.get("msg")))

    # ---- 文件来源 ----
    res = await cluster_logs(LogClusterForm(source="file", file_id=99999999), USER)
    check("文件不存在时给出可操作原因", res.get("code") != 0 and "文件" in (res.get("msg") or ""),
          str(res))

    # 指向内网的 view_url 要被 SSRF 兜底拦下
    from app.models.oss_file import PityOssFile
    import time as _time
    # file_path 唯一约束对 deleted_at 生效, 但跨轮跑会撞 —— 用时间戳保证幂等
    unique_path = f"e2e/log-{_time.time_ns()}.txt"
    async with async_session() as session:
        record = PityOssFile(user=USER["id"], file_path=unique_path,
                             view_url="http://127.0.0.1:8000/log.txt", file_size="1KB")
        session.add(record)
        await session.flush()
        record_id = record.id
        await session.commit()
    res = await cluster_logs(LogClusterForm(source="file", file_id=record_id), USER)
    check("内网地址被 SSRF 兜底拦下", res.get("code") != 0 and "内网" in (res.get("msg") or ""),
          str(res))

    # ---- 归因 ----
    cluster = (data.get("error_clusters") or [])[0]
    samples = (cluster.get("sample") or "").split("\n")
    res = await analyze_cluster(LogAnalyzeForm(fingerprint=cluster["fingerprint"], samples=samples,
                                               count=cluster["count"], vendor_id=1, model_id=1), USER)
    check("归因成功", res.get("code") == 0, str(res.get("msg")))
    result = res.get("data") or {}
    check("有结论摘要", bool(result.get("summary")), str(result))
    check("有分析 id", bool(result.get("analysis_id")))


# ---------------------------------------------------------------------------
# US2: Bug 分析
# ---------------------------------------------------------------------------


async def insert_result(case_id: int, status: int, summary: str, response: str = None) -> int:
    """插一条执行记录 —— US2 的夹具"""
    from datetime import datetime

    from app.crud.test_case.TestResult import TestResultDao
    result_id = await TestResultDao.insert_report(
        report_id=999999, case_id=case_id, case_name="登录-正常路径", status=status,
        case_log="[2026-10-26 10:00:00]: 步骤结束 -> 执行失败",
        start_at=datetime(2026, 10, 26, 10, 0, 0), finished_at=datetime(2026, 10, 26, 10, 0, 5),
        url="/api/login", body='{"mobile": "13800000000"}', request_method="POST",
        request_headers='{"Content-Type": "application/json"}', cost="1.2",
        asserts=json.dumps({"业务码": {"status": status != 0, "msg": summary}}, ensure_ascii=False),
        response_headers='{"Content-Type": "application/json"}',
        response=response if response is not None else '{"code": 500, "msg": "内部错误"} KeyError: \'user_id\'',
        status_code=500, cookies="", retry=0)
    return result_id


async def insert_case(directory_id: int, name: str) -> int:
    """插一条用例 —— US2 的夹具"""
    async with async_session() as session:
        model = TestCase(name=name, request_type=1, url="/api/login", directory_id=directory_id,
                         status=1, priority="P1", create_user=USER["id"], body_type=1,
                         case_type=0, request_method="POST")
        session.add(model)
        await session.flush()
        case_id = model.id
        await session.commit()
    return case_id


async def run_bug_analysis(directory_id: int):
    print("== US2: Bug 分析 ==")
    from app.crud.ai.AIAnalysisDao import AIAnalysisDao
    from app.routers.ai.bug import analyze_bug
    from app.schema.ai_workbench import BugAnalyzeForm

    # 夹具: 三个用例, 分别对应必现 / 偶发 / 首次执行
    case_always = await insert_case(directory_id, "分析夹具-必现")
    case_mixed = await insert_case(directory_id, "分析夹具-偶发")
    case_first = await insert_case(directory_id, "分析夹具-首次")

    # ① 必现 —— 连续 3 次失败, 失败摘要一致
    fail_ids = [await insert_result(case_always, 1, "断言失败: 业务码 10001 ≠ 0") for _ in range(3)]
    # ② 偶发 —— 失败与成功交替(插入顺序由旧到新, 所以最后一条是失败)
    mixed_ids = []
    for status in [0, 1, 0, 1, 0, 1]:
        mixed_ids.append(await insert_result(case_mixed, status,
                                             "断言失败: 业务码 10001 ≠ 0" if status else ""))
    # ③ 首次执行 —— 只有一条
    first_run_id = await insert_result(case_first, 1, "断言失败: 业务码 10001 ≠ 0")

    # ---- 上下文自动组装 ----
    res = await analyze_bug(BugAnalyzeForm(result_id=fail_ids[0], vendor_id=1, model_id=1), USER)
    check("分析成功", res.get("code") == 0, str(res.get("msg")))
    data = res.get("data") or {}
    check("有结论摘要", bool(data.get("summary")), str(data))
    check("有分析 id", bool(data.get("analysis_id")))
    check("根因假设非空", len(data.get("root_causes") or []) == 2)
    causes = data.get("root_causes") or []
    check("对得上的 evidence 保留", causes[0].get("evidence") == ["KeyError: 'user_id'"], str(causes[0]))
    check("对不上的移入 unsupported", causes[1].get("unsupported") == ["这一句根本不在上下文里"],
          str(causes[1]))
    check("对不上的 evidence 被清空", causes[1].get("evidence") == [])
    check("有修复建议", len(data.get("fix_suggestions") or []) == 1)
    check("有复现步骤", len(data.get("repro_steps") or []) == 2)

    # ---- history 判定 ----
    history = data.get("history") or {}
    check("history 有 pattern", bool(history.get("pattern")), str(history))
    check("history.pattern_label 是中文", history.get("pattern_label") == "必现", str(history))
    check("history.total 正确", history.get("total", 0) >= 3, str(history))
    check("history.failed 正确", history.get("failed", 0) >= 3, str(history))
    check("history 有连续失败次数", history.get("consecutive_failures", 0) >= 3, str(history))
    check("history.note 有说明", bool(history.get("note")))

    # 偶发
    res = await analyze_bug(BugAnalyzeForm(result_id=mixed_ids[-1], vendor_id=1, model_id=1), USER)
    history = (res.get("data") or {}).get("history") or {}
    check("失败成功交替 → intermittent", history.get("pattern") == "intermittent", str(history))

    # 首次执行
    res = await analyze_bug(BugAnalyzeForm(result_id=first_run_id, vendor_id=1, model_id=1), USER)
    history = (res.get("data") or {}).get("history") or {}
    check("只有一次执行 → first_run", history.get("pattern") == "first_run", str(history))
    check("first_run 的 note 说明缺少对比数据", "历史对比数据" in (history.get("note") or ""),
          str(history.get("note")))

    # ---- 结论入库, 多次分析互不覆盖 ----
    analysis_id = data.get("analysis_id")
    res = await analyze_bug(BugAnalyzeForm(result_id=fail_ids[0], vendor_id=1, model_id=1), USER)
    second_id = (res.get("data") or {}).get("analysis_id")
    check("两次分析拿到不同的 id", analysis_id != second_id, f"{analysis_id} vs {second_id}")
    rows, total = await AIAnalysisDao.list_analyses(scene="bug", ref_type="result",
                                                     ref_id=fail_ids[0])
    check("同一对象的多次分析都在库里", total >= 2, str(total))
    ids = [row.id for row in rows]
    check("两次分析的 id 都在库里", analysis_id in ids and second_id in ids, str(ids))

    # ---- 粘贴文本模式 ----
    res = await analyze_bug(BugAnalyzeForm(text="Traceback (most recent call last):\n  File \"app.py\", line 42\nKeyError: 'user_id'",
                                            vendor_id=1, model_id=1), USER)
    check("文本模式分析成功", res.get("code") == 0, str(res.get("msg")))
    history = (res.get("data") or {}).get("history") or {}
    check("文本模式 history 是 first_run", history.get("pattern") == "first_run", str(history))
    check("文本模式 note 说明缺少历史", "历史对比数据" in (history.get("note") or ""),
          str(history.get("note")))
    check("文本模式也有结论", bool((res.get("data") or {}).get("summary")))

    # ---- 复现步骤带入用例生成 ----
    repro = (res.get("data") or {}).get("repro_steps") or []
    check("复现步骤可用于生成用例", len(repro) == 2, str(repro))


def main():
    try:
        asyncio.run(run())
    except Exception:
        import traceback
        traceback.print_exc()
        print("FAILED: 端到端脚本异常退出")
        sys.exit(1)
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == '__main__':
    main()

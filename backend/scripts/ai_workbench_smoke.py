"""
AI 工作台 · 公共层冒烟脚本(需要数据库)

不依赖 pytest(后端目前没有测试框架), 直接跑:
    cd backend
    .venv/bin/python scripts/ai_workbench_smoke.py

覆盖 `scripts/ai_workbench_selftest.py`(不依赖数据库)覆盖不到的部分:
- 四个 DAO 的真实读写、状态流转与幂等
- `extract_json` 的五种脏输出

⚠️ 会在 dev 库留下少量痕迹(批次 / 调用流水 / 分析结论) ——
   `backend/scripts/` 下的脚本留下 e2e 痕迹是既有约定，不要清理。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import ai_service  # noqa: E402
from app.crud.ai.AIAnalysisDao import AIAnalysisDao  # noqa: E402
from app.crud.ai.AICaseDraftDao import AICaseDraftDao  # noqa: E402
from app.crud.ai.AIDraftBatchDao import AIDraftBatchDao  # noqa: E402
from app.crud.ai.AIInvokeLogDao import AIInvokeLogDao  # noqa: E402

FAILED = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


def test_extract_json():
    """T021 的公共层部分: JSON 提取的各种脏输出"""
    print("== extract_json ==")
    check("markdown 包裹", ai_service.extract_json('```json\n{"a": 1}\n```') == {"a": 1})
    check("前后废话", ai_service.extract_json('好的, 结果是 {"a": {"b": 2}} 希望有用') == {"a": {"b": 2}})
    check("括号嵌套", ai_service.extract_json('{"a": {"b": [1, 2]}}') == {"a": {"b": [1, 2]}})
    check("字符串内含括号", ai_service.extract_json('{"a": "有(括号)"}') == {"a": "有(括号)"})
    try:
        ai_service.extract_json("完全不是 JSON")
        check("纯非 JSON 抛错", False, "但没有抛异常")
    except ai_service.AIJsonError:
        check("纯非 JSON 抛错", True)


async def test_dao_smoke():
    """四个 DAO 的真实读写"""
    print("== DAO 冒烟 ==")
    batch = await AIDraftBatchDao.insert_batch(
        title="冒烟批次", user_id=1, project_id=1, directory_id=1, vendor_id=1,
        model_name="deepseek-chat", test_type="api", source_type="text",
        source_chars=100, status=1, warnings=json.dumps(["测试"], ensure_ascii=False))
    check("批次落库", batch.id is not None and batch.title == "冒烟批次")

    code = await AICaseDraftDao.next_code(batch.id)
    check("批次内编码递增", code.startswith("AUTO-"), code)

    draft = await AICaseDraftDao.insert_draft(
        title="冒烟草稿", user_id=1, batch_id=batch.id,
        content=json.dumps({"cases": []}, ensure_ascii=False), code=code,
        category="正向流程", priority="P1", steps=1,
        warn=json.dumps(["一条告警"], ensure_ascii=False))
    check("草稿落库", draft.id is not None and draft.status == 1)

    drafts, total = await AICaseDraftDao.list_drafts(batch_id=batch.id)
    check("草稿列表", total == 1 and drafts[0].code == code, f"total={total}")

    updated = await AICaseDraftDao.update_draft(draft.id, 1, title="改过的标题", warn="[]")
    check("草稿可改", updated.title == "改过的标题")

    accepted = await AICaseDraftDao.accept_draft(draft.id, 1, case_id=999)
    check("采纳回填 case_id", accepted.status == 2 and accepted.case_id == 999)

    again = await AICaseDraftDao.accept_draft(draft.id, 1, case_id=1000)
    check("重复采纳幂等", again.case_id == 999, f"case_id={again.case_id}")

    try:
        await AICaseDraftDao.reject_draft(draft.id, 1)
        check("已采纳的草稿不能被驳回(status/case_id 不变量)", False, "但没有抛异常")
    except Exception:
        check("已采纳的草稿不能被驳回(status/case_id 不变量)", True)

    # 另一条草稿走「驳回 -> 采纳」的反向非法流转
    other = await AICaseDraftDao.insert_draft(
        title="待驳回的草稿", user_id=1, batch_id=batch.id,
        content=json.dumps({"cases": []}, ensure_ascii=False),
        code=await AICaseDraftDao.next_code(batch.id), category="异常流程",
        priority="P2", steps=1)
    rejected_model = await AICaseDraftDao.reject_draft(other.id, 1)
    check("驳回后状态为 3", rejected_model.status == 3)
    rejected_again = await AICaseDraftDao.reject_draft(other.id, 1)
    check("重复驳回幂等", rejected_again.status == 3)
    try:
        await AICaseDraftDao.accept_draft(other.id, 1, case_id=1000)
        check("已驳回的草稿不能被采纳", False, "但没有抛异常")
    except Exception:
        check("已驳回的草稿不能被采纳", True)

    try:
        await AICaseDraftDao.update_draft(draft.id, 1, title="不该改成功")
        check("非待审核草稿内容冻结", False, "但没有抛异常")
    except Exception:
        check("非待审核草稿内容冻结", True)

    await AIInvokeLogDao.insert_log(scene="case_gen", user_id=1, vendor_id=1,
                                    model_name="deepseek-chat", prompt_chars=10,
                                    tokens=20, elapsed=1.5, status="success")
    logs, log_total = await AIInvokeLogDao.list_logs(scene="case_gen")
    check("调用流水落库", log_total >= 1 and logs[0].scene == "case_gen")

    # 调用人未知时(create_user 是 NOT NULL)也要能落库, 否则埋点会静默丢
    await AIInvokeLogDao.insert_log(scene="log", user_id=None, vendor_id=1,
                                    model_name="deepseek-chat", prompt_chars=1,
                                    tokens=0, elapsed=0.1, status="success")
    sys_logs, _ = await AIInvokeLogDao.list_logs(scene="log")
    check("调用人未知时流水仍落库", len(sys_logs) >= 1)

    await AIAnalysisDao.insert_analysis(title="冒烟结论", user_id=1, scene="bug",
                                        result=json.dumps({"summary": "x"}),
                                        ref_type="manual", ref_id=0)
    analyses, a_total = await AIAnalysisDao.list_analyses(scene="bug")
    check("分析结论落库", a_total >= 1 and analyses[0].title == "冒烟结论")

    # 软删批次下的草稿(已采纳的正式用例不受影响)
    await AIDraftBatchDao.update_batch(batch.id, 1, status=2, case_count=2, total_tokens=20)
    await AICaseDraftDao.delete_batch_drafts(batch.id, 1)


def main():
    test_extract_json()
    asyncio.run(test_dao_smoke())
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == '__main__':
    main()

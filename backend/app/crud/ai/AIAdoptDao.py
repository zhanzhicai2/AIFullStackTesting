"""
AI 草稿采纳 —— 把草稿的 DSL 落成正式用例

**一条草稿一个事务** —— 某条采纳失败只影响该条, 其余照常成功
(research.md §3.9)。批量采纳时由路由层逐条调用, 逐条回报成败。

**幂等** —— `pity_ai_case_draft.case_id` 已非空说明之前采纳过, 直接跳过,
不重复写用例(FR-009)。

**采纳前的两道拦截**(dsl.md §5 的规则 8 与规则 13)——
断言取值取不到、或 Web UI 步骤引用了不存在的元素, 这类草稿**不得**进入
正式用例库, 否则会往回归基线里塞一条必然红的用例。

落地的四张表(逐字对齐 data-model.md §3.2):
    cases[]              → pity_testcase
    out_parameters[]     → pity_out_parameters
    asserts[]            → pity_testcase_asserts
    pre/post_conditions  → pity_constructor
    ui.steps             → pity_ui_case
"""
import json
from typing import Optional, Tuple

from sqlalchemy import select

from app.crud.ai.AICaseDraftDao import AICaseDraftDao
from app.crud.ai.AIDraftBatchDao import AIDraftBatchDao
from app.crud.test_case.TestCaseDirectory import PityTestcaseDirectoryDao
from app.models import async_session
from app.models.ai_draft import PityAICaseDraft
from app.models.constructor import Constructor
from app.models.out_parameters import PityTestCaseOutParameters
from app.models.test_case import TestCase
from app.models.testcase_asserts import TestCaseAsserts
from app.models.ui_case import PityUICase


class AIAdoptDao:
    """
    草稿采纳 —— 落库部分

    映射与校验在 `app/core/ai_prompts/case_gen.py`, 这里只管写库。
    """

    @classmethod
    async def adopt_draft(cls, draft_id: int, user_id: int) -> Tuple[Optional[int], str]:
        """
        采纳一条草稿。

        :param draft_id: 草稿 id
        :param user_id:  操作人
        :return: (case_id, 失败原因) —— 失败原因非空表示**被拒绝**, 草稿状态保持待审核
        """
        from app.core.ai_prompts import case_gen

        draft = await AICaseDraftDao.query_draft(draft_id)
        if draft is None:
            raise Exception("草稿不存在")
        if draft.case_id:
            # 幂等 —— 已经采纳过了, 不重复写
            return draft.case_id, ""
        if draft.status != 1:
            raise Exception("该草稿已驳回, 不能采纳")

        batch = await AIDraftBatchDao.query_batch(draft.batch_id)
        if batch is None:
            raise Exception("生成批次不存在")
        directory = await PityTestcaseDirectoryDao.query_directory(batch.directory_id)
        if directory is None:
            return None, "目标目录不存在或已被删除"

        case = cls._extract_case(draft)
        if case is None:
            return None, "草稿内容为空或格式非法"

        # ---- 采纳前的两道拦截 ----
        problems = await case_gen.check_adopt_blockers(case, project_id=batch.project_id)
        if problems:
            return None, "; ".join(problems)

        records = case_gen.build_case_records(case, directory_id=batch.directory_id,
                                               test_type=batch.test_type or "api")
        try:
            case_id = await cls._write_case(records, user_id)
        except Exception as e:  # noqa: BLE001 —— 一条失败不影响其余
            return None, str(e)

        # 回填草稿状态 —— 放在落库之后, 保证"case_id 有值"与"用例已入库"同时成立
        await AICaseDraftDao.accept_draft(draft_id, user_id, case_id)
        await cls._refresh_batch(batch.id, user_id)
        return case_id, ""

    @classmethod
    def _extract_case(cls, draft: PityAICaseDraft) -> Optional[dict]:
        """从草稿的 content 里取出那一条用例"""
        try:
            payload = json.loads(draft.content or "")
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        cases = payload.get("cases")
        if not isinstance(cases, list) or not cases:
            return None
        first = cases[0]
        return first if isinstance(first, dict) else None

    @classmethod
    async def _write_case(cls, records: dict, user_id: int) -> int:
        """把映射好的行数据写进既有的四张表 —— 一个事务"""
        row = records["case"]
        async with async_session() as session:
            async with session.begin():
                # 同目录下重名 —— 提前拦, 免得 DB 唯一约束报错变成 500
                query = await session.execute(
                    select(TestCase).where(TestCase.directory_id == row["directory_id"],
                                           TestCase.name == row["name"],
                                           TestCase.deleted_at == 0))
                if query.scalars().first() is not None:
                    raise Exception(f"目标目录下已存在名为「{row['name']}」的用例")

                model = TestCase(name=row["name"], request_type=row["request_type"], url=row["url"],
                                 directory_id=row["directory_id"], status=row["status"],
                                 priority=row["priority"], create_user=user_id,
                                 body_type=row["body_type"], base_path=row.get("base_path"),
                                 tag=row.get("tag"), request_headers=row.get("request_headers"),
                                 case_type=row.get("case_type", 0), body=row.get("body"),
                                 request_method=row.get("request_method"))
                session.add(model)
                await session.flush()
                case_id = model.id

                for item in records["out_parameters"]:
                    session.add(PityTestCaseOutParameters(
                        name=item["name"], source=item["source"], case_id=case_id,
                        user_id=user_id, expression=item.get("expression"),
                        match_index=item.get("match_index")))

                for item in records["asserts"]:
                    session.add(TestCaseAsserts(
                        name=item["name"], case_id=case_id, assert_type=item["assert_type"],
                        expected=item["expected"], actually=item["actually"], user_id=user_id))

                for suffix, key in ((False, "pre_conditions"), (True, "post_conditions")):
                    for order, item in enumerate(records.get(key) or []):
                        session.add(Constructor(
                            type=item["type"], name=item["name"], enable=True,
                            constructor_json=json.dumps(item["constructor_json"], ensure_ascii=False),
                            case_id=case_id, public=bool(item.get("public")), user_id=user_id,
                            value=item.get("value") or "", suffix=suffix, index=order))

                ui = records.get("ui")
                if ui:
                    session.add(PityUICase(
                        case_id=case_id, base_url=ui["base_url"], user=user_id,
                        viewport=ui.get("viewport") or "1280x720",
                        browser=ui.get("browser") or "chromium",
                        timeout=int(ui.get("timeout") or 30), screenshot=True,
                        locale=ui.get("locale") or "en-US",
                        steps=json.dumps(ui.get("steps") or [], ensure_ascii=False)))

                await session.flush()
                session.expunge_all()
        return case_id

    @classmethod
    async def _refresh_batch(cls, batch_id: int, user_id: int):
        """刷新批次的草稿数与状态"""
        count = await AICaseDraftDao.count_by_batch(batch_id)
        await AIDraftBatchDao.update_batch(batch_id, user_id, status=2, case_count=count)

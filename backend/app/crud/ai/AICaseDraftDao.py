"""
AI 用例草稿 DAO

草稿是「AI 产物」与「正式用例」之间的中间态:
- `status = 1`(待审核) → content 可改, 可采纳, 可驳回
- `status = 2`(已采纳) → content 冻结, `case_id` 已回填
- `status = 3`(已驳回) → content 冻结, 终态

**幂等**: 采纳时若 `case_id` 已非空 → 跳过(不重复写用例)。
"""
import json
from typing import List, Optional, Tuple

from sqlalchemy import func, select

from app.crud import Mapper, ModelWrapper
from app.models import async_session
from app.models.ai_draft import PityAICaseDraft


@ModelWrapper(PityAICaseDraft)
class AICaseDraftDao(Mapper):
    """
    AI 用例草稿

    草稿表是编辑期的产物, 用例表是长期资产 —— 两者生命周期解耦:
    删批次只软删草稿, 已采纳的正式用例不受影响。
    """

    @classmethod
    async def insert_draft(cls, title: str, user_id: int, batch_id: int, content: str,
                           code: str = None, category: str = "正向流程", priority: str = "P1",
                           steps: int = 1, warn: str = None, order: int = 0) -> PityAICaseDraft:
        async with async_session() as session:
            async with session.begin():
                model = PityAICaseDraft(title=title, user=user_id, batch_id=batch_id, content=content,
                                        code=code, category=category, priority=priority,
                                        steps=steps, warn=warn, order=order)
                session.add(model)
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def query_draft(cls, draft_id: int) -> Optional[PityAICaseDraft]:
        async with async_session() as session:
            sql = select(PityAICaseDraft).where(PityAICaseDraft.id == draft_id,
                                                PityAICaseDraft.deleted_at == 0)
            result = await session.execute(sql)
            return result.scalars().first()

    @classmethod
    async def list_drafts(cls, batch_id: int = None, status: int = None, page: int = 1,
                          size: int = 10) -> Tuple[List[PityAICaseDraft], int]:
        """草稿列表(分页) —— 可按批次与状态过滤"""
        async with async_session() as session:
            conditions = [PityAICaseDraft.deleted_at == 0]
            if batch_id is not None:
                conditions.append(PityAICaseDraft.batch_id == batch_id)
            if status is not None:
                conditions.append(PityAICaseDraft.status == status)
            count_sql = select(func.count(PityAICaseDraft.id)).where(*conditions)
            total = (await session.execute(count_sql)).scalar() or 0
            sql = select(PityAICaseDraft).where(*conditions).order_by(PityAICaseDraft.order.asc(),
                                                                      PityAICaseDraft.id.asc())
            sql = sql.offset(max(0, (page - 1) * size)).limit(size)
            result = await session.execute(sql)
            return list(result.scalars().all()), total

    @classmethod
    async def update_draft(cls, draft_id: int, user_id: int, content: str = None,
                           title: str = None, priority: str = None, category: str = None,
                           warn: str = None, steps: int = None) -> PityAICaseDraft:
        """
        修改草稿 —— **只允许改待审核(status=1)的草稿**。

        已采纳/已驳回的草稿内容冻结: 确定性的锚点是草稿的**当前 content 版本**,
        冻结之后"重复采纳同一版本结果一致"这句话才有意义。
        """
        async with async_session() as session:
            async with session.begin():
                sql = select(PityAICaseDraft).where(PityAICaseDraft.id == draft_id,
                                                    PityAICaseDraft.deleted_at == 0)
                result = await session.execute(sql)
                model = result.scalars().first()
                if model is None:
                    raise Exception("草稿不存在")
                if model.status != 1:
                    raise Exception("该草稿已采纳或已驳回, 内容已冻结, 不可修改")
                if content is not None:
                    model.content = content
                if title is not None:
                    model.title = title
                if priority is not None:
                    model.priority = priority
                if category is not None:
                    model.category = category
                if warn is not None:
                    model.warn = warn
                if steps is not None:
                    model.steps = steps
                model.update_user = user_id
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def accept_draft(cls, draft_id: int, user_id: int, case_id: int) -> PityAICaseDraft:
        """
        标记草稿已采纳并回填 `case_id` —— **幂等**。

        `case_id` 已非空说明之前采纳过, 直接返回(不重复写用例)。
        """
        async with async_session() as session:
            async with session.begin():
                sql = select(PityAICaseDraft).where(PityAICaseDraft.id == draft_id,
                                                    PityAICaseDraft.deleted_at == 0)
                result = await session.execute(sql)
                model = result.scalars().first()
                if model is None:
                    raise Exception("草稿不存在")
                if model.case_id:
                    return model
                if model.status == 3:
                    # 3已驳回是终态 —— 驳回的草稿不能再被采纳
                    raise Exception("该草稿已驳回, 不能采纳")
                model.status = 2
                model.case_id = case_id
                model.update_user = user_id
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def reject_draft(cls, draft_id: int, user_id: int) -> PityAICaseDraft:
        """
        标记草稿已驳回 —— 幂等(已是 3 则跳过)。

        **已采纳(status=2)的草稿不能被驳回**: 采纳时已经写进正式用例库并回填了
        `case_id`, 驳回会让 status 与 case_id 的不变量破裂
        (data-model.md §2.2: status = 2 时 case_id 必非空, status ≠ 2 时必为空),
        而且正式用例已经存在, 驳回草稿撤不掉它。
        """
        async with async_session() as session:
            async with session.begin():
                sql = select(PityAICaseDraft).where(PityAICaseDraft.id == draft_id,
                                                    PityAICaseDraft.deleted_at == 0)
                result = await session.execute(sql)
                model = result.scalars().first()
                if model is None:
                    raise Exception("草稿不存在")
                if model.status == 3:
                    return model
                if model.status == 2:
                    raise Exception("该草稿已采纳, 不能驳回")
                model.status = 3
                model.update_user = user_id
                await session.flush()
                session.expunge(model)
                return model

    @classmethod
    async def delete_batch_drafts(cls, batch_id: int, user_id: int) -> int:
        """软删批次下的全部草稿 —— 已采纳的正式用例不受影响"""
        count = 0
        async with async_session() as session:
            async with session.begin():
                sql = select(PityAICaseDraft).where(PityAICaseDraft.batch_id == batch_id,
                                                    PityAICaseDraft.deleted_at == 0)
                result = await session.execute(sql)
                for model in result.scalars().all():
                    cls.delete_model(model, user_id)
                    count += 1
                await session.flush()
        return count

    @classmethod
    async def count_by_batch(cls, batch_id: int) -> int:
        async with async_session() as session:
            sql = select(func.count(PityAICaseDraft.id)).where(PityAICaseDraft.batch_id == batch_id,
                                                                 PityAICaseDraft.deleted_at == 0)
            return (await session.execute(sql)).scalar() or 0

    @classmethod
    async def next_code(cls, batch_id: int) -> str:
        """
        批次内下一个用例编码 —— AUTO-001 / AUTO-002 ...

        编码在批次内唯一(`UniqueConstraint('batch_id','code','deleted_at')`),
        但 MySQL 的唯一约束对 NULL 不生效, 所以这里显式按最大序号 +1 生成,
        避免并发下撞码(撞了会报唯一约束错误, 500 给用户)。
        """
        async with async_session() as session:
            sql = select(PityAICaseDraft.code).where(PityAICaseDraft.batch_id == batch_id,
                                                      PityAICaseDraft.deleted_at == 0)
            result = await session.execute(sql)
            max_index = 0
            for code in result.scalars().all():
                if not code:
                    continue
                try:
                    max_index = max(max_index, int(str(code).split("-")[-1]))
                except (ValueError, IndexError):
                    continue
            return f"AUTO-{max_index + 1:03d}"

    @staticmethod
    def parse_warn(value) -> list:
        """把草稿的 `warn` 字段(JSON 数组)解出来 —— 解析失败返回空数组"""
        if not value:
            return []
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

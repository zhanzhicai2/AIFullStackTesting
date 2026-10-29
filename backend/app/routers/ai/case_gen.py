"""
用例生成路由 —— AI 工作台的 US1

前缀 `/ai`, 全部走 `PityResponse` 的 `{code, data, msg}`。
契约见 `specs/001-ai-workbench/contracts/api.md` §3。

**核心流程**: 需求文本 → 模型 → 14 条校验 → 草稿落库 → 人工审核 → 采纳进用例库。

AI 只做翻译, 落地由确定性内核做 —— 生成出来的永远是**草稿**,
不写正式用例库(FR-008)。
"""
import json
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File

from app.core import ai_service
from app.core.ai_client import ChatError
from app.core.ai_prompts import case_gen
from app.core.ai_prompts.base import MAX_DOCUMENT_CHARS, truncate
from app.crud.ai.AIAdoptDao import AIAdoptDao
from app.crud.ai.AICaseDraftDao import AICaseDraftDao
from app.crud.ai.AIDraftBatchDao import AIDraftBatchDao
from app.crud.config.GConfigDao import GConfigDao
from app.crud.project.ProjectDao import ProjectDao
from app.crud.test_case.TestCaseDirectory import PityTestcaseDirectoryDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.routers.ai.base import router
from app.schema.ai_workbench import (AcceptForm, GenerateForm, RejectForm, UpdateDraftForm)
from app.utils.document_parser import DocumentError, parse_document


@router.post("/case/generate", description="生成用例草稿")
async def generate_cases(form: GenerateForm, user_info=Depends(Permission())):
    """
    生成用例草稿 —— 产出**草稿**, 不写正式用例库。

    失败时返回 `code 110`, `msg` 是可操作的原因(哪个厂商、什么错、建议动作)。
    """
    user_id = user_info['id']
    try:
        try:
            await ProjectDao.query_project(form.project_id)
        except Exception:
            return PityResponse.failed("项目不存在")
        directory = await PityTestcaseDirectoryDao.query_directory(form.directory_id)
        if directory is None:
            return PityResponse.failed("目标目录不存在或已被删除")
        if directory.project_id != form.project_id:
            return PityResponse.failed("目标目录不属于所选项目")

        # 超长正文头尾截断 —— 静默截断会让用户误以为模型看全了
        warnings: List[str] = []
        content = form.content or ""
        content, truncated, note = truncate(content, MAX_DOCUMENT_CHARS)
        if truncated and note:
            warnings.append(note)

        # 规则 8 的豁免项 —— 全局变量名
        try:
            global_vars = set(await GConfigDao.list_all_keys())
        except Exception:
            global_vars = set()

        messages = case_gen.build_messages(form.title, content, form.test_type)

        # 调用模型 + 解析 + 校验 —— 解析失败会由 ai_service 自动纠错重试 1 次
        async def parser(text: str):
            return await case_gen.parse_cases(text, project_id=form.project_id,
                                               global_vars=global_vars)

        result = await ai_service.invoke(messages, form.vendor_id, form.model_id,
                                         scene="case_gen", params_override=form.params,
                                         parser=parser, user_id=user_id)

        cases, rule_warnings = result.data or ([], [])
        warnings.extend(rule_warnings)

        # 批次先落库(生成中), 草稿逐条落库
        batch = await AIDraftBatchDao.insert_batch(
            title=form.title, user_id=user_id, project_id=form.project_id,
            directory_id=form.directory_id, vendor_id=form.vendor_id,
            model_name=result.model_name, test_type=form.test_type,
            source_type=form.source_type, source_name=form.source_name,
            source_chars=len(content), status=1,
            warnings=json.dumps(warnings, ensure_ascii=False))

        summaries = []
        for index, case in enumerate(cases, start=1):
            code = await AICaseDraftDao.next_code(batch.id)
            draft = await AICaseDraftDao.insert_draft(
                title=case["name"], user_id=user_id, batch_id=batch.id,
                content=json.dumps({"cases": [case]}, ensure_ascii=False), code=code,
                category=case.get("category") or "正向流程", priority=case.get("priority") or "P1",
                steps=_count_steps(case), warn=json.dumps(_case_warnings(warnings, index),
                                                         ensure_ascii=False),
                order=index)
            summaries.append({
                "id": draft.id, "batch_id": batch.id, "code": draft.code, "title": draft.title,
                "category": draft.category, "priority": draft.priority, "status": draft.status,
                "steps": draft.steps, "warn": _case_warnings(warnings, index),
            })

        await AIDraftBatchDao.update_batch(batch.id, user_id, status=2, case_count=len(summaries),
                                           total_tokens=result.tokens,
                                           warnings=json.dumps(warnings, ensure_ascii=False))
        return PityResponse.success({
            "batch_id": batch.id,
            "case_count": len(summaries),
            "total_tokens": result.tokens,
            "warnings": warnings,
            "cases": summaries,
        }, msg="生成完成")
    except ChatError as e:
        # 模型调用失败 / 两次解析都失败 —— 给出可操作的原因
        return PityResponse.failed(str(e))
    except ai_service.AIJsonError as e:
        return PityResponse.failed(f"模型返回的内容无法解析为合法结构: {e}, 请重试")
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/case/draft/list", description="用例草稿列表")
async def list_drafts(batch_id: int, status: int = None, page: int = 1, size: int = 10,
                      user_info=Depends(Permission())):
    """
    草稿列表。

    响应里带 `content`(DSL JSON)—— 契约 §3.2 的字段清单里没有它,
    但草稿详情抽屉要能编辑 DSL, 没有它就得再加一个"取详情"的端点。
    这里选择直接在列表里带上, 少一次往返。
    """
    try:
        drafts, total = await AICaseDraftDao.list_drafts(batch_id=batch_id, status=status,
                                                          page=page, size=size)
        result = []
        for draft in drafts:
            item = PityResponse.model_to_dict(draft)
            item["warn"] = AICaseDraftDao.parse_warn(draft.warn)
            try:
                item["content"] = json.loads(draft.content or "{}")
            except Exception:
                item["content"] = {}
            result.append(item)
        return PityResponse.success_with_size(data=result, total=total)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/case/draft/update", description="修改单条草稿")
async def update_draft(form: UpdateDraftForm, user_info=Depends(Permission())):
    """
    修改草稿 —— **保存时重新过一遍 14 条校验规则**。

    用户手工改的内容同样要校验, 不能绕过。告警回传并写进草稿的 `warn`。
    只允许改 `status = 1`(待审核)的草稿。
    """
    user_id = user_info['id']
    try:
        draft = await AICaseDraftDao.query_draft(form.draft_id)
        if draft is None:
            return PityResponse.failed("草稿不存在")
        if draft.status != 1:
            return PityResponse.failed("该草稿已采纳或已驳回, 内容已冻结, 不可修改")
        batch = await AIDraftBatchDao.query_batch(draft.batch_id)
        if batch is None:
            return PityResponse.failed("生成批次不存在")

        content = None
        title = form.title
        priority = form.priority
        category = form.category
        steps = None
        warn = AICaseDraftDao.parse_warn(draft.warn)

        if form.content is not None:
            try:
                global_vars = set(await GConfigDao.list_all_keys())
            except Exception:
                global_vars = set()
            try:
                cases, warnings = await case_gen.parse_cases(
                    json.dumps(form.content, ensure_ascii=False),
                    project_id=batch.project_id, global_vars=global_vars)
            except ai_service.AIJsonError as e:
                return PityResponse.failed(f"草稿内容不合法: {e}")
            if len(cases) != 1:
                return PityResponse.failed("一条草稿只能包含一条用例")
            normalized = cases[0]
            content = json.dumps({"cases": [normalized]}, ensure_ascii=False)
            # 内容改了, 标题/优先级/类别跟着规范化后的值走(除非显式传了)
            title = form.title or normalized.get("name") or draft.title
            priority = form.priority or normalized.get("priority") or draft.priority
            category = form.category or normalized.get("category") or draft.category
            steps = _count_steps(normalized)
            warn = warnings

        updated = await AICaseDraftDao.update_draft(
            form.draft_id, user_id, content=content, title=title, priority=priority,
            category=category, warn=json.dumps(warn, ensure_ascii=False), steps=steps)
        return PityResponse.success({"id": updated.id, "warn": warn}, msg="保存成功")
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/case/draft/accept", description="批量采纳草稿")
async def accept_drafts(form: AcceptForm, user_info=Depends(Permission())):
    """
    批量采纳 —— **一条草稿一个事务**。

    某条失败只影响该条, 其余照常成功; 失败原因逐条回显在 `failed[].reason`。
    被拒的草稿状态保持 1(待审核), 不落正式用例库。
    """
    user_id = user_info['id']
    succeeded, failed = [], []
    for draft_id in form.draft_ids:
        try:
            case_id, reason = await AIAdoptDao.adopt_draft(draft_id, user_id)
        except Exception as e:  # noqa: BLE001 —— 一条失败不影响其余
            failed.append({"id": draft_id, "reason": str(e)})
            continue
        if reason:
            failed.append({"id": draft_id, "reason": reason})
        else:
            succeeded.append(draft_id)
    msg = f"采纳完成: 成功 {len(succeeded)} 条"
    if failed:
        msg += f", 失败 {len(failed)} 条"
    return PityResponse.success({"succeeded": succeeded, "failed": failed}, msg=msg)


@router.post("/case/draft/reject", description="批量驳回草稿")
async def reject_drafts(form: RejectForm, user_info=Depends(Permission())):
    """批量驳回 —— 幂等(已是已驳回的跳过)"""
    user_id = user_info['id']
    succeeded, failed = [], []
    for draft_id in form.draft_ids:
        try:
            await AICaseDraftDao.reject_draft(draft_id, user_id)
            succeeded.append(draft_id)
        except Exception as e:  # noqa: BLE001
            failed.append({"id": draft_id, "reason": str(e)})
    msg = f"驳回完成: 成功 {len(succeeded)} 条"
    if failed:
        msg += f", 失败 {len(failed)} 条"
    return PityResponse.success({"succeeded": succeeded, "failed": failed}, msg=msg)


@router.post("/document/parse", description="解析需求文档")
async def parse_document_endpoint(file: UploadFile = File(...),
                                   user_info=Depends(Permission())):
    """
    解析需求文档(PDF / Word / Markdown / 纯文本)。

    解析失败**降级**为纯文本读取, 仍失败才报错并建议改用文本输入。
    """
    try:
        if not file:
            return PityResponse.failed("请选择要上传的文档")
        data = await file.read()
        if not data:
            return PityResponse.failed("文件内容为空")
        parsed = parse_document(file.filename or "", data)
        return PityResponse.success(parsed.to_dict(), msg="解析成功")
    except DocumentError as e:
        return PityResponse.failed(str(e))
    except Exception as e:
        return PityResponse.failed(e)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _count_steps(case: dict) -> int:
    """步骤数 —— API 用例算 1, Web UI 用例算步骤条数"""
    ui = case.get("ui") or {}
    steps = ui.get("steps") or []
    if steps:
        return len(steps)
    return 1


def _case_warnings(warnings: List[str], index: int) -> List[str]:
    """
    把批次级告警按用例序号拆开。

    `parse_cases` 给每条告警加了 `用例 N: ` 前缀 —— 序号在批次内唯一,
    比按用例名匹配可靠(用例名可能重复)。
    """
    prefix = f"用例 {index}: "
    return [message[len(prefix):] for message in warnings if message.startswith(prefix)]

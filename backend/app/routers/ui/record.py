"""
录制导入路由

**安全边界(本 feature 新引入的第二个安全面)**:
导入的脚本是**外部输入**。平台只做**静态文本解析**(`ast`), 绝不 eval / exec /
在浏览器里跑脚本内容 —— 脚本里的 `page.evaluate(...)` 这类行会被跳过并说明原因。

导入产出的是一条**状态为「调试中」**的 UI 用例(复用既有用例状态语义, 不新建草稿表),
用户核对步骤后把状态改成「正常运行」即视为采纳。
"""
import json

from fastapi import APIRouter, Depends

from app.core.ui_executor import strip_internal, validate_steps
from app.core.ui_recorder import build_pages_and_elements, normalize_page, parse_codegen
from app.crud.test_case.TestCaseDao import TestCaseDao
from app.crud.ui.UIImportLogDao import UIImportLogDao
from app.crud.ui.UICaseDao import UICaseDao
from app.enums.RequestTypeEnum import RequestType
from app.handler.fatcory import PityResponse
from app.models.test_case import TestCase
from app.routers import Permission
from app.schema.ui_case import UIImportForm

router = APIRouter()

MAX_CASE_NAME = 32


async def _unique_case_name(name: str, directory_id: int) -> str:
    """同目录下同名要加序号 —— pity_testcase 的唯一约束是 (directory_id, name, deleted_at)"""
    base = name[:MAX_CASE_NAME]
    candidate = base
    index = 2
    while await TestCaseDao.query_record(name=candidate, directory_id=directory_id) is not None:
        suffix = f"_{index}"
        candidate = base[:MAX_CASE_NAME - len(suffix)] + suffix
        index += 1
    return candidate


@router.post("/record/import", description="导入本地录制脚本")
async def import_record(form: UIImportForm, user_info=Depends(Permission())):
    try:
        warnings = list()
        # 1. 静态解析 —— 不执行脚本里的任何内容
        actions, parse_warnings = parse_codegen(form.script)
        warnings.extend(parse_warnings)
        if not actions:
            await UIImportLogDao.insert_import_log(
                user_id=user_info['id'], project_id=form.project_id, source=form.source,
                raw_len=len(form.script), parsed_lines=0, skipped_lines=len(parse_warnings),
                status=3, message="没有解析出任何可用的步骤")
            return PityResponse.failed("没有解析出任何可用的步骤, 请检查脚本是不是 codegen 录制的",
                                        data=dict(warnings=warnings))
        # 2. 自动建页面与元素(按去重键复用)
        pages, elements, steps, stats = await build_pages_and_elements(
            form.project_id, actions, user_info['id'])
        # 3. 走一遍步骤校验 —— 与手工建单走同一条路
        valid_steps, step_warnings = await validate_steps(form.project_id, steps)
        warnings.extend(step_warnings)
        if not valid_steps:
            await UIImportLogDao.insert_import_log(
                user_id=user_info['id'], project_id=form.project_id, source=form.source,
                raw_len=len(form.script), parsed_lines=len(actions), skipped_lines=len(warnings),
                page_count=stats["pages_created"], element_count=stats["elements_created"],
                status=3, message="解析出的步骤全部无效")
            return PityResponse.failed("解析出的步骤全部无效, 用例未创建", data=dict(warnings=warnings))
        # 4. 产出「调试中」状态的 UI 用例
        #    base_url 取脚本里第一个 goto 的地址 —— 录制脚本就是从那儿开始的
        base_url = ""
        for action in actions:
            if action.kind == "goto" and action.params.get("url"):
                base_url = action.params["url"]
                break
        # 用例名取首个页面名 —— 页面已存在时(复用)也能拿到稳定的名字
        page_name = normalize_page(base_url)[0] if base_url else ""
        name = form.name or (f"录制导入-{page_name}" if page_name else "录制导入")
        name = await _unique_case_name(name, form.directory_id)
        model = TestCase(name=name, request_type=RequestType.web_ui.value,
                         url=base_url, directory_id=form.directory_id, status=1,
                         priority="P1", create_user=user_info['id'])
        model = await TestCaseDao.insert(model=model, log=True)
        await UICaseDao.insert_ui_case(case_id=model.id, base_url=base_url,
                                       steps=json.dumps(strip_internal(valid_steps), ensure_ascii=False),
                                       user_id=user_info['id'])
        # 5. 留痕
        status = 2 if warnings else 1
        log = await UIImportLogDao.insert_import_log(
            user_id=user_info['id'], project_id=form.project_id, source=form.source,
            raw_len=len(form.script), parsed_lines=len(actions), skipped_lines=len(warnings),
            page_count=stats["pages_created"], element_count=stats["elements_created"],
            case_count=1, status=status, message="\n".join(warnings))
        return PityResponse.success(dict(
            import_log_id=log.id,
            parsed_lines=len(actions),
            skipped_lines=len(warnings),
            pages_created=stats["pages_created"],
            elements_created=stats["elements_created"],
            elements_reused=stats["elements_reused"],
            case_id=model.id,
            warnings=warnings,
            steps=strip_internal(valid_steps)), msg="导入完成")
    except Exception as e:
        return PityResponse.failed(e)

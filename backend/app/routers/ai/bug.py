"""
失败分析路由 —— AI 工作台的 US2

前缀 `/ai`。契约见 `specs/001-ai-workbench/contracts/api.md` §4.1。

两种入参:
- `result_id` —— 后端自动从 `pity_test_result` 组装上下文(请求/响应/断言/日志/耗时/重试)
  并补该用例最近 N 次执行历史(判必现 vs 偶发)。**用户不用手工喂料**(FR-016)
- `text` —— 粘贴的堆栈文本, 输出结构一致(FR-021)

结论落 `pity_ai_analysis` —— **每次分析一行, 永不覆盖**(FR-036)。
"""
import json

from fastapi import APIRouter, Depends

from app.core import ai_service
from app.core.ai_client import ChatError
from app.core.ai_prompts import bug
from app.crud.ai.AIAnalysisDao import AIAnalysisDao
from app.crud.test_case.TestResult import TestResultDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.routers.ai.base import router
from app.schema.ai_workbench import BugAnalyzeForm


@router.post("/bug/analyze", description="失败用例根因分析")
async def analyze_bug(form: BugAnalyzeForm, user_info=Depends(Permission())):
    """
    分析一次失败。

    响应含 `history` 字段 —— 承载"必现 / 偶发 / 已恢复 / 首次执行"的判定。
    """
    user_id = user_info['id']
    try:
        if form.result_id:
            result = await TestResultDao.query_result(form.result_id)
            if result is None:
                return PityResponse.failed("执行记录不存在")
            context = bug.build_context(result)
            # 补该用例最近 N 次执行历史 —— 区分偶发与必现(FR-018)
            recent = await TestResultDao.list_recent_by_case(result.case_id,
                                                              bug.DEFAULT_HISTORY_SIZE)
            history = bug.build_history(recent)
            ref_type, ref_id = "result", form.result_id
            title = result.case_name or f"执行记录 #{form.result_id}"
        else:
            context = form.text or ""
            # 粘贴文本没有历史可比 —— 必须显式说明"缺少历史对比数据", 不得臆造
            history = bug.build_history([])
            ref_type, ref_id = "manual", 0
            title = "粘贴的堆栈文本"

        messages = bug.build_messages(context)

        # 解析时把上下文传进去 —— evidence 要逐条做子串匹配
        def parser(text: str):
            return bug.parse_result(text, context)

        result_data = await ai_service.invoke(messages, form.vendor_id, form.model_id,
                                              scene="bug", parser=parser, user_id=user_id)
        conclusion = result_data.data or {}

        analysis = await AIAnalysisDao.insert_analysis(
            title=title, user_id=user_id, scene="bug",
            result=json.dumps({"conclusion": conclusion, "history": history}, ensure_ascii=False),
            ref_type=ref_type, ref_id=ref_id, vendor_id=result_data.vendor_id,
            model_name=result_data.model_name, tokens=result_data.tokens)

        payload = dict(conclusion)
        payload["analysis_id"] = analysis.id
        payload["history"] = history
        return PityResponse.success(payload, msg="分析完成")
    except ChatError as e:
        return PityResponse.failed(str(e))
    except ai_service.AIJsonError as e:
        return PityResponse.failed(f"模型返回的内容无法解析为合法结构: {e}, 请重试")
    except Exception as e:
        return PityResponse.failed(e)

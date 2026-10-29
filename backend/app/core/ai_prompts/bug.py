"""
Bug 分析 —— 提示词、结论解析与上下文组装(US2)

**核心机制**: 每条根因必须引用**上下文里的原文**, 后端逐条做子串匹配,
对不上的移入 `unsupported`(前端标灰为「低可信」)。

为什么这么严: 没有原文依据的根因就是模型在编。
后端不替模型背书 —— 引用对不上的结论, 一律降级为"无依据"(spec FR-020)。

**`history` 承载的是"必现 / 偶发"的判定**:
`pattern` 必须依据**真实的执行记录**判定; 没有历史可比时必须是 `first_run`
并在 `note` 里说明"缺少历史对比数据" —— **不得臆造历史规律**(spec FR-018 + Edge Case)。
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.ai_prompts import base
from app.enums.AIWorkbenchEnum import HISTORY_PATTERN_LABELS, HISTORY_PATTERNS

# 根因类别(data-model.md §2.4 的结论 JSON)
CATEGORIES = ["参数校验", "数据不一致", "依赖超时", "配置错误", "代码缺陷", "未知"]
DEFAULT_CATEGORY = "未知"

# 默认取最近 N 次执行做历史比对
DEFAULT_HISTORY_SIZE = 10

# 结论里 evidence / recent 的长度上限 —— 都是要送进模型的
MAX_EVIDENCE_CHARS = 2000
MAX_RECENT_SUMMARY_CHARS = 200

SYSTEM_PROMPT = """你是接口测试平台 Pity 的「失败分析」助手。
你的任务是根据给定的失败上下文, 判断这次用例失败最可能的根因。

你只输出 JSON, 不要输出任何解释文字, 不要输出 markdown 代码块以外的内容。

## 输出结构

{
  "summary": "一句话结论",
  "category": "参数校验|数据不一致|依赖超时|配置错误|代码缺陷|未知",
  "confidence": 0.82,
  "root_causes": [
    {
      "cause": "根因描述",
      "evidence": ["引用上下文原文的第 1 行", "第 2 行"],
      "confidence": 0.8,
      "verify_checklist": ["如何自证这条判断"]
    }
  ],
  "fix_suggestions": [
    {"title": "建议标题", "detail": "建议详情", "patch": "可选的代码片段"}
  ],
  "repro_steps": ["可复现步骤 1", "步骤 2"]
}

## 硬性要求

1. `confidence` 必须是 0 到 1 之间的小数。
2. `evidence` 里的每一项**必须是上下文里的原文片段, 一字不差** ——
   平台会逐条做子串匹配, 对不上的引用会被标成「无依据」, 那条结论就不可信了。
   **不要改写、不要截断、不要加引号**。要引用哪一段, 就把那整段原样抄过来。
3. `root_causes` 按可信度从高到低排列, 一般 1~3 条就够, 不要凑数。
4. 没有原文依据的推测**不要写进 evidence**; 确实拿不准就降低 `confidence`,
   并在 `verify_checklist` 里写清楚"还需要什么信息才能确认"。
5. `fix_suggestions` 要具体到能照着改, `patch` 给出关键代码片段。
6. `repro_steps` 是**可复现步骤**, 从发请求到看到错误, 每步一句话。
7. 上下文里没有的信息不要编 —— 宁可少给一条根因。

## 示例

上下文里有: `KeyError: 'user_id'` 与 `"code": 500, "msg": "内部错误"`

输出:
{"summary": "响应体缺少 user_id 字段导致 KeyError",
 "category": "数据不一致",
 "confidence": 0.82,
 "root_causes": [
   {"cause": "上游接口在 code 非 0 时不返回 data 字段",
    "evidence": ["KeyError: 'user_id'", "\\"code\\": 500"],
    "confidence": 0.8,
    "verify_checklist": ["用 code=500 的响应体重放该用例"]}],
 "fix_suggestions": [
   {"title": "响应体判空后再取值", "detail": "取值前先判断 data 是否存在", "patch": "data = resp.get('data') or {}"}],
 "repro_steps": ["以无效 token 调用 GET /api/user/profile", "断言响应 code 为 0"]}
"""


def build_messages(context: str, prompt: str = "") -> list:
    """
    组装 messages —— 上下文用 `<logs>` 标签包裹(外部输入, 可能含注入)。

    :param context: 失败上下文(请求/响应/断言/日志/耗时/重试)
    :param prompt:  用户的补充说明(可选)
    """
    body = f"[任务说明] {prompt}\n\n" if prompt else ""
    body += "[失败上下文]\n"
    user = f"<logs>\n{body}{context or ''}\n</logs>\n\n请按系统消息里的规范输出 JSON:"
    return base.build_messages(SYSTEM_PROMPT, user)


# ---------------------------------------------------------------------------
# 上下文组装(T038)
# ---------------------------------------------------------------------------


def build_context(result) -> str:
    """
    从 `pity_test_result` 组装失败上下文。

    覆盖 spec FR-017 要求的六项: 请求内容 / 响应内容 / 断言失败明细 /
    执行日志 / 耗时 / 重试次数。

    :param result: PityTestResult
    :return:      上下文文本 —— **evidence 必须从这里取原文**
    """
    lines = [
        f"用例名称: {getattr(result, 'case_name', '')}",
        f"用例id: {getattr(result, 'case_id', '')}",
        f"请求方法: {getattr(result, 'request_method', '') or ''}",
        f"请求地址: {getattr(result, 'url', '') or ''}",
        f"请求头: {getattr(result, 'request_headers', '') or ''}",
        f"请求体: {getattr(result, 'body', '') or ''}",
        f"请求参数: {getattr(result, 'request_params', '') or ''}",
        f"响应状态码: {getattr(result, 'status_code', '')}",
        f"响应头: {getattr(result, 'response_headers', '') or ''}",
        f"响应体: {getattr(result, 'response', '') or ''}",
        f"断言结果: {getattr(result, 'asserts', '') or ''}",
        f"执行日志: {getattr(result, 'case_log', '') or ''}",
        f"耗时(秒): {getattr(result, 'cost', '') or ''}",
        f"重试次数: {getattr(result, 'retry', '') or ''}",
    ]
    return "\n".join(lines)


def failure_summary(result) -> str:
    """从断言结果里提炼一句失败摘要 —— 用来比较"多次失败是不是同一个表现" """
    raw = getattr(result, "asserts", "") or ""
    try:
        parsed = json.loads(raw)
    except Exception:
        return (raw or "")[:MAX_RECENT_SUMMARY_CHARS]
    if not isinstance(parsed, dict):
        return str(parsed)[:MAX_RECENT_SUMMARY_CHARS]
    messages = []
    for key, value in parsed.items():
        if isinstance(value, dict):
            msg = value.get("msg") or value.get("message") or ""
            status = value.get("status")
            if status is False or status == 0 or msg:
                messages.append(f"{key}: {msg or '断言未通过'}")
        else:
            messages.append(f"{key}: {value}")
    return "; ".join(messages)[:MAX_RECENT_SUMMARY_CHARS]


def _is_failed(result) -> bool:
    """执行记录是否失败 —— status: 0成功 1失败 2出错 3跳过"""
    status = getattr(result, "status", 0)
    return status in (1, 2)


def judge_pattern(recent: List[Any]) -> Tuple[str, str]:
    """
    判定执行历史是必现 / 偶发 / 已恢复 / 首次执行。

    :param recent: 按时间**倒序**的执行记录
    :return: (pattern, note)
    """
    if not recent:
        return "first_run", "没有历史执行记录, 缺少历史对比数据"

    failed = [item for item in recent if _is_failed(item)]
    passed = [item for item in recent if not _is_failed(item)]

    # 连续失败次数(从最近一次往前数)
    consecutive = 0
    for item in recent:
        if _is_failed(item):
            consecutive += 1
        else:
            break

    if not failed:
        # 契约要求: 无历史可比时 note 必须明确写出"缺少历史对比数据"
        return "first_run", f"最近 {len(recent)} 次执行全部成功, 没有失败历史可比, 缺少历史对比数据"

    # 最近一次成功、此前有失败 —— 已恢复
    if not _is_failed(recent[0]):
        return "recovered", f"最近一次执行成功, 此前 {len(failed)} 次失败, 问题已恢复"

    summaries = {failure_summary(item) for item in failed}
    if consecutive >= 2 and len(summaries) == 1:
        return "consistent_failure", f"最近 {len(recent)} 次执行中连续失败 {consecutive} 次, 且失败表现一致"

    if failed and passed:
        return "intermittent", f"最近 {len(recent)} 次执行中失败 {len(failed)} 次、成功 {len(passed)} 次, 失败与成功交替出现"

    if consecutive >= 2:
        return "consistent_failure", f"最近 {len(recent)} 次执行中连续失败 {consecutive} 次"

    return "first_run", f"最近 {len(recent)} 次执行中只有 1 次失败, 缺少足够的历史对比数据"


def build_history(recent: List[Any]) -> dict:
    """
    组装 `history` 结构 —— 承载 spec FR-018 要求的"历史规律"。

    :param recent: 按时间倒序的执行记录
    """
    failed = [item for item in recent if _is_failed(item)]
    passed = [item for item in recent if not _is_failed(item)]
    consecutive = 0
    for item in recent:
        if _is_failed(item):
            consecutive += 1
        else:
            break
    pattern, note = judge_pattern(recent)
    items = []
    for item in recent:
        finished_at = getattr(item, "finished_at", None)
        items.append({
            "result_id": getattr(item, "id", 0),
            "status": getattr(item, "status", 0),
            "finished_at": finished_at.strftime("%Y-%m-%d %H:%M:%S") if finished_at else "",
            "cost": getattr(item, "cost", 0),
            "summary": failure_summary(item),
        })
    return {
        "total": len(recent),
        "failed": len(failed),
        "passed": len(passed),
        "consecutive_failures": consecutive,
        "pattern": pattern,
        "pattern_label": HISTORY_PATTERN_LABELS.get(pattern, pattern),
        "note": note,
        "recent": items,
    }


# ---------------------------------------------------------------------------
# 结论解析(T037)
# ---------------------------------------------------------------------------


def _clip(value: Any, limit: int = MAX_EVIDENCE_CHARS) -> str:
    return str(value or "")[:limit]


def parse_result(text: str, context: str = "") -> dict:
    """
    解析模型输出并做结论校验。

    - 结构校验: 缺字段补默认值, 类型不对的丢弃
    - `evidence` 逐条做**上下文子串匹配**, 对不上的移入 `unsupported`
    - `confidence` 夹到 [0, 1]

    :param text:    模型返回的文本
    :param context: 上下文原文 —— evidence 必须与它逐字匹配
    :return:        规范化后的结论
    """
    from app.core.ai_service import AIJsonError, extract_json

    payload = extract_json(text)
    if not isinstance(payload, dict):
        raise AIJsonError("模型返回的 JSON 不是对象")

    result = {
        "summary": _clip(payload.get("summary"), 500),
        "category": str(payload.get("category") or DEFAULT_CATEGORY),
        "confidence": _confidence(payload.get("confidence")),
        "root_causes": [],
        "fix_suggestions": [],
        "repro_steps": [],
    }
    if result["category"] not in CATEGORIES:
        result["category"] = DEFAULT_CATEGORY

    raw_causes = payload.get("root_causes")
    if isinstance(raw_causes, list):
        for item in raw_causes:
            if not isinstance(item, dict):
                continue
            cause = str(item.get("cause") or "").strip()
            if not cause:
                continue
            evidence, unsupported = _split_evidence(item.get("evidence"), context)
            result["root_causes"].append({
                "cause": cause,
                "evidence": evidence,
                "unsupported": unsupported,
                "confidence": _confidence(item.get("confidence")),
                "verify_checklist": [str(x) for x in (item.get("verify_checklist") or [])
                                    if str(x).strip()],
            })

    raw_fixes = payload.get("fix_suggestions")
    if isinstance(raw_fixes, list):
        for item in raw_fixes:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            fix = {"title": title, "detail": _clip(item.get("detail"), 2000)}
            if item.get("patch"):
                fix["patch"] = _clip(item.get("patch"), 4000)
            result["fix_suggestions"].append(fix)

    raw_steps = payload.get("repro_steps")
    if isinstance(raw_steps, list):
        result["repro_steps"] = [str(x).strip() for x in raw_steps if str(x).strip()][:50]

    return result


def _confidence(value: Any) -> float:
    """把 confidence 夹到 [0, 1] —— 越界的值不是"很可信", 是没按格式输出"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def _split_evidence(raw: Any, context: str) -> Tuple[List[str], List[str]]:
    """
    把 evidence 分成「有原文依据」与「无依据」两拨。

    :param raw:     模型给的 evidence 列表
    :param context: 上下文原文
    :return: (匹配上的, 匹配不上的)
    """
    matched, unsupported = [], []
    if not isinstance(raw, list):
        return matched, unsupported
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        text = _clip(text)
        if context and text in context:
            matched.append(text)
        else:
            unsupported.append(text)
    return matched, unsupported

"""
日志分析 —— 提示词与结论解析(US3)

**先聚类, 再让模型解读**: 聚类与突增检测是纯 Python(`app/core/ai_prompts/clustering.py`),
**不产生任何模型调用** —— 这样日志行数与成本解耦, 10MB 日志也能处理。

模型只做一件事: 看一个错误簇的样例, 给出归因。
**结论必须引用簇内的日志行** —— 对不上的引用移入 `unsupported`(低可信)。
"""
import json
from typing import Any, Dict, List, Optional, Tuple

from app.core.ai_prompts import base
from app.enums.AIWorkbenchEnum import HISTORY_PATTERN_LABELS

# 归因类别(与 Bug 分析共用一套)
CATEGORIES = ["参数校验", "数据不一致", "依赖超时", "配置错误", "代码缺陷", "未知"]
DEFAULT_CATEGORY = "未知"

MAX_EVIDENCE_CHARS = 2000
MAX_SAMPLE_LINES = 200

SYSTEM_PROMPT = """你是接口测试平台 Pity 的「日志分析」助手。
你的任务是根据给定的**错误簇**样例, 判断这批错误最可能的根因。

你只输出 JSON, 不要输出任何解释文字, 不要输出 markdown 代码块以外的内容。

## 输出结构

{
  "summary": "一句话结论",
  "category": "参数校验|数据不一致|依赖超时|配置错误|代码缺陷|未知",
  "confidence": 0.8,
  "root_causes": [
    {
      "cause": "根因描述",
      "evidence": ["引用样例日志里的原文行"],
      "confidence": 0.8,
      "verify_checklist": ["如何自证这条判断"]
    }
  ],
  "fix_suggestions": [
    {"title": "建议标题", "detail": "建议详情", "patch": "可选的代码片段"}
  ]
}

## 硬性要求

1. `evidence` 里的每一项**必须是样例日志里的原文行, 一字不差** ——
   平台会逐条做子串匹配, 对不上的引用会被标成「无依据」。
   要引用哪一行, 就把那整行原样抄过来, 不要改写、不要截断。
2. 这个错误簇是**同一类错误**(平台已经按指纹归并过), 所以根因应该只有一个方向。
   不要为不同的样例硬凑出多个根因。
3. `confidence` 必须在 0 到 1 之间。
4. `fix_suggestions` 要具体到能照着改。
5. 样例里没有的信息不要编 —— 拿不准就降低 `confidence`。

## 示例

样例里有:
```
2026-10-26 03:12:44 | ERROR | 文件: /app/api/user.py | 行数: 42 | - KeyError: 'user_id' case_id=101
```

输出:
{"summary": "user 接口返回体缺少 user_id 字段",
 "category": "数据不一致",
 "confidence": 0.85,
 "root_causes": [
   {"cause": "上游在错误码分支不返回 data 字段",
    "evidence": ["2026-10-26 03:12:44 | ERROR | 文件: /app/api/user.py | 行数: 42 | - KeyError: 'user_id' case_id=101"],
    "confidence": 0.85,
    "verify_checklist": ["用返回 500 的响应体重放 case_id=101"]}],
 "fix_suggestions": [
   {"title": "取值前判空", "detail": "响应体里的 data 可能不存在", "patch": "data = resp.get('data') or {}"}]}
"""


def build_messages(fingerprint: str, sample: str, count: int, samples: Optional[List[str]] = None) -> list:
    """
    组装 messages —— 样例日志用 `<logs>` 标签包裹(外部输入, 可能含注入)。

    :param fingerprint: 错误簇指纹
    :param sample:      代表样例(簇里的第一条)
    :param count:       该簇出现次数
    :param samples:     簇内的日志行(evidence 要与它们逐字匹配)
    """
    lines = list(samples or [])
    if not lines and sample:
        lines = sample.splitlines()
    body = f"[错误簇指纹] {fingerprint}\n[出现次数] {count}\n\n[簇内日志行]\n"
    body += "\n".join(lines[:MAX_SAMPLE_LINES])
    user = f"<logs>\n{body}\n</logs>\n\n请按系统消息里的规范输出 JSON:"
    return base.build_messages(SYSTEM_PROMPT, user)


def _clip(value: Any, limit: int = MAX_EVIDENCE_CHARS) -> str:
    return str(value or "")[:limit]


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if number < 0 else (1.0 if number > 1 else number)


def parse_result(text: str, samples: Optional[List[str]] = None) -> dict:
    """
    解析模型输出。

    - 结构校验: 缺字段补默认值, 类型不对的丢弃
    - `evidence` 逐条做**簇内日志行的子串匹配**, 对不上的移入 `unsupported`

    :param text:    模型返回的文本
    :param samples: 簇内的日志行 —— evidence 必须与它们逐字匹配
    :return:        规范化后的结论
    """
    from app.core.ai_service import AIJsonError, extract_json

    payload = extract_json(text)
    if not isinstance(payload, dict):
        raise AIJsonError("模型返回的 JSON 不是对象")

    context = "\n".join(samples or [])
    result = {
        "summary": _clip(payload.get("summary"), 500),
        "category": str(payload.get("category") or DEFAULT_CATEGORY),
        "confidence": _confidence(payload.get("confidence")),
        "root_causes": [],
        "fix_suggestions": [],
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

    return result


def _split_evidence(raw: Any, context: str) -> Tuple[List[str], List[str]]:
    """把 evidence 分成「有原文依据」与「无依据」两拨"""
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

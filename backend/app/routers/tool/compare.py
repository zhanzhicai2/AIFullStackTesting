"""
JSON 深度对比 —— 直接复用断言引擎同款 `app/utils/json_compare.py`。

**为什么不自己在前端写一份递归 diff**: 断言引擎给出的差异文案
(`$.a.b 类型不一致, 分别为...`) 是用户在报告页已经认识的语言, 工具页再
造一套措辞, 同一个差异在两处说法不同, 反而更难对照。
"""
import json

from fastapi import APIRouter, Depends

from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.tool import JsonDiffForm
from app.utils.json_compare import JsonCompare

router = APIRouter()


@router.post("/json/diff", summary="JSON 深度对比")
def json_diff(data: JsonDiffForm, _=Depends(Permission())):
    try:
        expected = json.loads(data.expected)
    except Exception as err:
        return PityResponse.failed(f"期望值不是合法 JSON: {err}")
    try:
        actual = json.loads(data.actual)
    except Exception as err:
        return PityResponse.failed(f"实际值不是合法 JSON: {err}")

    try:
        diffs = JsonCompare().compare(expected, actual)
    except Exception as err:
        return PityResponse.failed(err)

    return PityResponse.success(data=dict(
        identical=len(diffs) == 0,
        diffs=diffs,
        # 顶层类型提示 —— 两个都不是对象时差异只会有一条, 先说清形状更省事
        expected_type=type(expected).__name__,
        actual_type=type(actual).__name__,
    ))

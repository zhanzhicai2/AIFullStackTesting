"""
AI 工作台的公共 AI 层 —— 厂商/模型解析、调用埋点、JSON 提取。

四个 AI 场景(用例生成 / Bug 分析 / 日志分析 / SQL 分析)的
「选模型 → 调模型 → 解析 → 落库」流程完全同构。不抽象就是四份重复,
改一次超时策略要改四个文件(research.md §3.2)。

```
app/core/ai_service.py
├── resolve_model(vendor_id, model_id) -> ModelRef
│     厂商/模型校验 + params 解析, 统一抛 ChatError
├── invoke(messages, vendor_id, model_id, scene, ...) -> AIResult
│     调用 + 调用流水埋点 + 解析失败纠错重试
├── extract_json(text) -> Any
│     从 data_factory/ai_parser.py 抽出(公共实现)
└── build_messages(system_prompt, user_content) -> list
```

**错误文案的统一**:`ai_client._status_message` 已经把 401/403/404/429/5xx
翻译成可操作的中文, 这里**不另写一套错误映射** —— 厂商/模型校验失败也统一
抛 `ChatError`, 由路由层转成 `PityResponse.failed()`。
"""
import json
import re
import time
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app import logger
from app.core.ai_client import ChatError, complete_chat_with_usage
from app.crud.ai.AIInvokeLogDao import AIInvokeLogDao
from app.crud.ai.AIModelDao import AIModelDao
from app.crud.ai.AIVendorDao import AIVendorDao

# 纠错重试的次数上限(包含第一次)—— research.md §3.3
MAX_ATTEMPTS = 2

# 调用流水里 error_msg 的最大长度 —— 完整错误文案很长, 流水页不需要
MAX_ERROR_MSG = 500

# 解析失败时回灌给模型的提示
RETRY_HINT = ("上一次输出无法解析为合法结构, 原因: {reason}\n"
               "请只输出约定的 JSON, 不要输出任何解释文字, 不要用 markdown 代码块包裹。")


class AIJsonError(Exception):
    """模型输出无法解析为 JSON —— 与 ChatError 分开, 便于调用方区分「调用失败」与「解析失败」"""


@dataclass
class ModelRef:
    """解析后的厂商 + 模型引用 —— 调用模型需要的全部信息"""
    vendor_id: int
    vendor_name: str
    base_url: str
    api_key: str
    model_id: int
    model_name: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AIResult:
    """一次模型调用的结果"""
    content: str = ""
    data: Any = None
    tokens: int = 0
    elapsed: float = 0.0
    model_name: str = ""
    vendor_id: int = 0
    prompt_chars: int = 0
    attempts: int = 1


# ---------------------------------------------------------------------------
# 厂商 / 模型解析
# ---------------------------------------------------------------------------


async def resolve_model(vendor_id: int, model_id: int) -> ModelRef:
    """
    解析厂商与模型, 并做全套校验。

    校验项(与模型设置页的配置语义一致):
    - 厂商存在
    - 厂商已启用 **且** 配了 API Key
    - 模型存在
    - 模型已启用 **且** `model_type == 'chat'`(embedding / rerank 不能拿去对话)

    :param vendor_id: 厂商 id
    :param model_id:  模型 id
    :return:         ModelRef
    :raise ChatError: 任一项不满足
    """
    if not vendor_id:
        raise ChatError("请先选择厂商")
    if not model_id:
        raise ChatError("请先选择模型")

    vendor = await AIVendorDao.query_vendor(vendor_id)
    if vendor is None:
        raise ChatError("模型厂商不存在")
    if not vendor.enable or not vendor.api_key:
        raise ChatError("该厂商未启用或未配置 API Key, 请联系管理员")

    model_row = None
    for item in await AIModelDao.list_model(vendor_id):
        if item.id == model_id:
            model_row = item
            break
    if model_row is None:
        raise ChatError("模型不存在")
    if not model_row.enable or model_row.model_type != "chat":
        raise ChatError("该模型未启用或不是对话模型")

    params = {}
    if model_row.params:
        try:
            parsed = json.loads(model_row.params)
            if isinstance(parsed, dict):
                params = parsed
        except Exception:
            params = {}

    return ModelRef(vendor_id=vendor.id,
                    vendor_name=vendor.name,
                    base_url=vendor.base_url,
                    api_key=vendor.api_key,
                    model_id=model_row.id,
                    model_name=model_row.name,
                    params=params)


# ---------------------------------------------------------------------------
# 调用 + 埋点
# ---------------------------------------------------------------------------


def _sanitize_error(message: str, api_key: str = "") -> str:
    """
    脱敏 —— 调用流水的 `error_msg` **不得含 API Key**, 也不得含完整 prompt 正文。

    :param message: 原始错误文案
    :param api_key: 当前厂商的 API Key(命中则替换掉)
    """
    text = message or ""
    if api_key and api_key.strip():
        text = text.replace(api_key.strip(), "***")
    # 去掉可能残留的 Authorization 头
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9\-_.]+", r"\1***", text)
    if len(text) > MAX_ERROR_MSG:
        text = text[:MAX_ERROR_MSG] + "..."
    return text


def _prompt_chars(messages: list) -> int:
    """prompt 字符数 —— 只统计长度, 不落正文"""
    total = 0
    for item in messages or []:
        if isinstance(item, dict):
            total += len(str(item.get("content") or ""))
        else:
            total += len(str(item))
    return total


async def _write_invoke_log(scene: str, user_id: Optional[int], ref: ModelRef, prompt_chars: int,
                            tokens: int, elapsed: float, status: str, error_msg: str):
    """
    写调用流水 —— 失败**不能**影响主流程(埋点挂了不该让用户的生成失败)。
    """
    try:
        await AIInvokeLogDao.insert_log(scene=scene, user_id=user_id, vendor_id=ref.vendor_id,
                                        model_name=ref.model_name, prompt_chars=prompt_chars,
                                        tokens=tokens, elapsed=elapsed, status=status,
                                        error_msg=error_msg)
    except Exception as e:  # noqa: BLE001 —— 埋点失败只记日志
        logger.bind(name=None).warning(f"写 AI 调用流水失败: {e}")


async def invoke(messages: list, vendor_id: int, model_id: int, scene: str,
                 params_override: dict = None, parser: Callable = None,
                 user_id: Optional[int] = None) -> AIResult:
    """
    调用模型, 写调用流水, 解析失败时纠错重试 1 次。

    :param messages:        OpenAI 格式的 messages
    :param vendor_id:       厂商 id
    :param model_id:        模型 id
    :param scene:           场景(case_gen / bug / log / sql), 写进调用流水
    :param params_override: 覆盖模型自身配置的参数(白名单键由 ai_client 兜底)
    :param parser:          解析回调 `parser(content) -> Any`, **可以是 async 函数**。
                            传了才会做解析与纠错重试
    :param user_id:         调用人, 写进调用流水
    :return:                AIResult
    :raise ChatError:       调用失败(重试后仍失败) 或 解析失败(重试后仍失败)
    """
    ref = await resolve_model(vendor_id, model_id)

    params = dict(ref.params or {})
    if isinstance(params_override, dict):
        for key, value in params_override.items():
            if value is not None:
                params[key] = value

    prompt_chars = _prompt_chars(messages)
    current = list(messages or [])
    start = time.time()
    attempts = 0
    last_reason = ""
    content = ""

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        try:
            content, usage = await complete_chat_with_usage(ref.base_url, ref.api_key, ref.model_name,
                                                            current, params)
        except ChatError as e:
            elapsed = time.time() - start
            # 调用本身失败: 按 research §3.3 重试 1 次(吸收瞬时网络抖动),
            # 但鉴权/配额类错误重试也没用, 直接把可操作的原因抛出去
            if attempts >= MAX_ATTEMPTS or not _is_retryable(str(e)):
                await _write_invoke_log(scene, user_id, ref, prompt_chars, 0, elapsed,
                                        "failed", _sanitize_error(str(e), ref.api_key))
                raise
            logger.bind(name=None).warning(f"AI 调用失败, 准备重试: {e}")
            continue

        elapsed = time.time() - start
        tokens = int((usage or {}).get("total_tokens") or 0)

        if parser is None:
            await _write_invoke_log(scene, user_id, ref, prompt_chars, tokens, elapsed, "success", "")
            return AIResult(content=content, tokens=tokens, elapsed=elapsed,
                            model_name=ref.model_name, vendor_id=ref.vendor_id,
                            prompt_chars=prompt_chars, attempts=attempts)

        try:
            data = parser(content)
            # parser 可以是 async 的(用例生成的 14 条校验规则要查元素库)
            if inspect.isawaitable(data):
                data = await data
        except Exception as e:  # noqa: BLE001 —— 解析失败要纠错重试
            last_reason = str(e)
            if attempts >= MAX_ATTEMPTS:
                await _write_invoke_log(scene, user_id, ref, prompt_chars, tokens, elapsed,
                                        "failed", _sanitize_error(
                                            f"模型返回的内容无法解析为合法结构, 已重试 1 次仍失败: {last_reason}",
                                            ref.api_key))
                raise ChatError("模型返回的内容无法解析为合法结构, 已重试 1 次仍失败, 请重试")
            logger.bind(name=None).warning(f"AI 输出解析失败, 准备纠错重试: {last_reason}")
            current = current + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": RETRY_HINT.format(reason=last_reason)},
            ]
            continue

        await _write_invoke_log(scene, user_id, ref, prompt_chars, tokens, elapsed, "success", "")
        return AIResult(content=content, data=data, tokens=tokens, elapsed=elapsed,
                        model_name=ref.model_name, vendor_id=ref.vendor_id,
                        prompt_chars=prompt_chars, attempts=attempts)

    # 理论上到不了这里 —— 循环里要么 return 要么 raise
    await _write_invoke_log(scene, user_id, ref, prompt_chars, 0, time.time() - start,
                            "failed", _sanitize_error(last_reason or "AI 调用失败", ref.api_key))
    raise ChatError("模型调用失败, 请重试")


def _is_retryable(message: str) -> bool:
    """
    判断厂商错误是否值得重试。

    值得重试: 超时 / 连接失败 / 5xx —— 瞬时问题。
    不值得: 401/403(API Key 不对)/ 404 / 405 / 429(配额) —— 重试也不会变好,
    立刻把可操作的原因抛给用户才是对的。
    """
    text = message or ""
    if any(code in text for code in ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 405", "HTTP 429")):
        return False
    return True


# ---------------------------------------------------------------------------
# JSON 提取(公共实现)
# ---------------------------------------------------------------------------


def extract_json(text: str) -> Any:
    """
    从模型输出里抠出 JSON —— 容忍 markdown 代码块包裹和前后废话。

    三步降级:
    1. 剥掉 ``` 包裹后直接 `json.loads`
    2. 提取第一个完整的 `{...}` 块(括号计数法, 字符串里的括号不算)
    3. 都没有 → 抛 `AIJsonError`

    :param text: 模型返回的文本
    :return:    解析出来的对象
    :raise AIJsonError: 解析失败
    """
    if not text:
        raise AIJsonError("模型没有返回内容")
    content = text.strip()
    # 去掉 ```json ... ``` 包裹
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        content = re.sub(r"\s*```\s*$", "", content)
    try:
        return json.loads(content)
    except Exception:
        pass
    # 退而求其次: 提取第一个完整的 {...} 块
    start = content.find("{")
    if start == -1:
        raise AIJsonError("模型返回的内容里没有 JSON")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(content)):
        char = content[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(content[start:index + 1])
                except Exception:
                    break
    raise AIJsonError("模型返回的 JSON 解析失败, 请重试")


# ---------------------------------------------------------------------------
# messages 组装
# ---------------------------------------------------------------------------


def build_messages(system_prompt: str, user_content: str) -> List[dict]:
    """
    组装 OpenAI 格式的 messages。

    注入声明的拼接在 `app/core/ai_prompts/base.py` 里 —— 那里才是外部文本
    标签包裹的所在地, 本函数只是转发, 免得两处各拼一次。
    """
    from app.core.ai_prompts.base import build_messages as _build
    return _build(system_prompt, user_content)

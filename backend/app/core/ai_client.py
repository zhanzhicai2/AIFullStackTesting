"""
调用 OpenAI 兼容接口拉取厂商可用模型

不复用 AsyncHttpClient: 它在 HTTP 非 200 时返回 status=False 的 dict 而非抛异常,
且会带上 MOCK_ON 的 proxy 逻辑,对调用外部厂商接口不合适。
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

import aiohttp

from app import logger

FETCH_TIMEOUT = 15      # 拉模型列表的总超时
CONNECT_TIMEOUT = 8     # 建连超时
CHAT_SOCK_TIMEOUT = 60  # 对话流每次读的超时(单次 idle 超过即认为厂商挂了)
MAX_MODEL_COUNT = 500   # 防止个别厂商返回上万条撑爆前端弹窗


class ChatError(Exception):
    """对话流异常,对外只暴露中文 message"""


class FetchModelError(Exception):
    """对外只暴露中文 message,由 router 转成 PityResponse.failed()"""


def _build_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise FetchModelError("Base URL 为空, 请先填写并保存 Base URL")
    if not url.startswith(("http://", "https://")):
        raise FetchModelError("Base URL 必须以 http:// 或 https:// 开头")
    # 兼容用户直接粘贴了完整的 /models 地址
    return url if url.endswith("/models") else f"{url}/models"


def normalize_models(payload: Any) -> List[Dict[str, Any]]:
    """
    归一化各家厂商不同的返回结构:
      OpenAI 标准  {"object":"list","data":[{"id":"gpt-4",...}]}
      部分网关    {"models":[...]} / {"result":[...]}
      裸数组      [{...}] / ["gpt-4", ...]
    取名依次尝试 id / name / model / model_name
    """
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or payload.get("result") or []
    elif isinstance(payload, list):
        items = payload
    else:
        return []

    result, seen = [], set()
    for item in items:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or item.get("model")
                        or item.get("model_name") or "").strip()
        else:
            continue
        if not name or name in seen:
            continue
        seen.add(name)
        result.append({"name": name, "model_type": "chat"})
    return result[:MAX_MODEL_COUNT]


def _status_message(status: int, text: str) -> str:
    snippet = (text or "").replace("\n", " ")[:200]
    if status in (401, 403):
        return f"API Key 无效或无权访问该厂商接口(HTTP {status}), 请检查 API Key 是否正确且已激活"
    if status == 404:
        return "该厂商未提供 GET /models 接口(HTTP 404), 请改用「+ 自定义」添加模型"
    if status == 405:
        return "该厂商不支持 GET /models 方法(HTTP 405), 请改用「+ 自定义」添加模型"
    if status == 429:
        return "请求过于频繁或账户额度已用尽(HTTP 429), 请稍后重试"
    if status >= 500:
        return f"厂商服务异常(HTTP {status}), 请稍后重试: {snippet}"
    return f"请求失败(HTTP {status}): {snippet}"


async def fetch_remote_models(base_url: str, api_key: str) -> List[Dict[str, Any]]:
    """
    拉取厂商可用模型列表
    :param base_url: OpenAI 兼容 Base URL,例如 https://api.deepseek.com/v1
    :param api_key:  API Key
    :return: [{"name": "xxx", "model_type": "chat"}, ...]
    """
    url = _build_url(base_url)
    api_key = (api_key or "").strip()
    if not api_key:
        raise FetchModelError("API Key 为空, 请先填写并保存 API Key")

    headers = {"Authorization": f"Bearer {api_key}",
               "Accept": "application/json",
               # 显式只要 gzip/deflate: 部分厂商(实测 DeepSeek)默认返回 br,
               # 而 aiohttp 优先依赖 brotlicffi, 缺失时会抛 ContentEncodingError
               "Accept-Encoding": "gzip, deflate"}
    timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT, connect=CONNECT_TIMEOUT)
    payload: Optional[Any] = None
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, ssl=False) as resp:
                # 先取 text: 部分厂商返回的 Content-Type 不是 application/json,
                # 直接用 resp.json() 会抛 ContentTypeError
                text = await resp.text()
                if resp.status != 200:
                    logger.bind(name=None).warning(f"拉取厂商模型失败 {resp.status}: {text[:200]}")
                    raise FetchModelError(_status_message(resp.status, text))
                try:
                    payload = json.loads(text)
                except Exception:
                    raise FetchModelError(f"厂商返回的不是合法 JSON(可能被网关或代理拦截): {text[:200]}")
    except FetchModelError:
        raise
    except asyncio.TimeoutError:
        raise FetchModelError(f"请求厂商接口超时({FETCH_TIMEOUT}s), 请检查网络或 Base URL 是否正确")
    except aiohttp.ContentEncodingError:
        raise FetchModelError("厂商返回了当前环境无法解码的压缩格式(br), 请联系管理员安装 brotlicffi")
    except aiohttp.ClientConnectorError:
        raise FetchModelError("无法连接到厂商地址, 请检查 Base URL / 本机网络 / 代理设置")
    except aiohttp.ClientSSLError:
        raise FetchModelError("HTTPS 证书校验失败, 请确认 Base URL 的协议与厂商一致")
    except aiohttp.ClientError as e:
        raise FetchModelError(f"请求厂商接口失败: {e}")

    models = normalize_models(payload)
    if not models:
        # 有些厂商鉴权失败也返回 200, 错误信息放在 body 里
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("msg") or payload.get("error")
            if detail:
                raise FetchModelError(f"厂商返回: {detail}")
        raise FetchModelError("未获取到模型列表, 请确认 API Key 是否可用")
    logger.bind(name=None).info(f"fetch models from {url}, got {len(models)}")
    return models

def _build_chat_url(base_url: str) -> str:
    """对话端点。兼容用户直接粘了完整的 /chat/completions 地址"""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ChatError("Base URL 为空, 请先在模型设置里填写并保存")
    if not url.startswith(("http://", "https://")):
        raise ChatError("Base URL 必须以 http:// 或 https:// 开头")
    return url if url.endswith("/chat/completions") else f"{url}/chat/completions"


async def stream_chat(base_url: str, api_key: str, model_name: str, messages: list, params: dict = None):
    """
    流式对话,异步生成器

    :param messages: OpenAI 格式 [{"role": "user", "content": "..."}, ...]
    :param params:   额外参数(temperature/max_tokens/top_p),来自模型的齿轮设置
    :yield: (增量文本, usage 或 None); 最后一帧携带 token 用量
    """
    url = _build_chat_url(base_url)
    if not (api_key or "").strip():
        raise ChatError("该厂商未配置 API Key, 请联系管理员在模型设置里补充")
    if not model_name:
        raise ChatError("未指定模型")

    payload = {"model": model_name, "messages": messages, "stream": True,
               "stream_options": {"include_usage": True}}
    # params 来自 AIModel.params(齿轮里配的参数), 只覆盖白名单键
    if isinstance(params, dict):
        for key in ("temperature", "max_tokens", "top_p", "stop", "presence_penalty", "frequency_penalty"):
            if params.get(key) is not None:
                payload[key] = params[key]

    headers = {"Authorization": f"Bearer {api_key.strip()}",
               "Content-Type": "application/json",
               # 与拉模型列表同理: 部分厂商默认返回 br, aiohttp 未必装了解码器
               "Accept-Encoding": "gzip, deflate"}
    # 注意 total=None: 拉列表的 15s 总超时会把长回复直接砍掉,
    # 流式只能约束单次 idle(sock_read)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=CONNECT_TIMEOUT, sock_read=CHAT_SOCK_TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers, ssl=False) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.bind(name=None).warning(f"对话请求失败 {resp.status}: {text[:200]}")
                    raise ChatError(_status_message(resp.status, text))
                async for raw in resp.content:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except Exception:
                        # 心跳/注释/厂商夹带的非 JSON 行, 跳过不影响
                        continue
                    # usage 可能出现在任意一帧: OpenAI 系放在 choices 为空的最后一帧,
                    # 部分厂商(含 DeepSeek)则与最后一帧的 choices 并列, 两种都要接
                    usage = obj.get("usage")
                    if usage:
                        yield "", usage
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    # reasoning_content 是部分厂商的思维链, 一并透传给前端
                    text_piece = delta.get("content") or delta.get("reasoning_content") or ""
                    if text_piece:
                        yield text_piece, None
    except (ChatError, GeneratorExit):
        raise
    except asyncio.TimeoutError:
        raise ChatError(f"生成超时({CHAT_SOCK_TIMEOUT}s 无响应), 请稍后重试")
    except aiohttp.ContentEncodingError:
        raise ChatError("厂商返回了当前环境无法解码的压缩格式(br), 请联系管理员安装 brotlicffi")
    except aiohttp.ClientConnectorError:
        raise ChatError("无法连接到厂商地址, 请检查 Base URL / 本机网络 / 代理设置")
    except aiohttp.ClientSSLError:
        raise ChatError("HTTPS 证书校验失败, 请确认 Base URL 的协议与厂商一致")
    except aiohttp.ClientError as e:
        raise ChatError(f"请求厂商接口失败: {e}")

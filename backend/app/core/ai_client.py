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

FETCH_TIMEOUT = 15      # 总超时
CONNECT_TIMEOUT = 8     # 建连超时
MAX_MODEL_COUNT = 500   # 防止个别厂商返回上万条撑爆前端弹窗


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
               "Accept": "application/json"}
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
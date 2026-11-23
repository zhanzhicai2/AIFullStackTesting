"""
日志脱敏 —— 请求体 / URL 落进日志文件之前必须过这里。

**为什么必须先有它再打通 info sink**: `main.request_info` 会把整个请求体打进
DEBUG 日志, 而 AI 日志分析(`app/routers/ai/log.py`, ADMIN 权限)读的正是平台自身
日志文件。info sink 一旦修通, 密码 / JWT / API Key 就会明文落盘 —— 等于给每个能读
日志的人发了一份凭据。

脱敏只认**键名**(递归到 dict/list 的每一层)与 URL 的 path/query, 不做值的猜测 ——
猜值要么漏(小写混合的 token 认不出)要么误伤(把正常长文本抹掉)。
"""
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# 覆盖的掩码字符
MASK = "***"

# 键名命中(忽略大小写与 `_` / `-`)即脱敏其值
SENSITIVE_KEY_PATTERN = re.compile(
    r"password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|credential|authorization|auth[_-]?header|session|cookie",
    re.IGNORECASE,
)

# 已知敏感路径前缀 —— 命中就把**最后一段**掩掉。
# 覆盖 `/auth/reset/check/<des密文>` 与 `/auth/reset/generate/<email>`
SENSITIVE_PATH_PREFIXES = ("/reset/check/", "/reset/generate/")

# 高熵 path 段兜底: 长度 ≥32 且**同时**含字母与数字。
# 要求"含字母"是为了不误伤纯数字的雪花 id(`/project/1234567890123456`)。
HIGH_ENTROPY_SEGMENT = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9_\-.=]{32,}$")

# 单个字符串落日志的上限 —— 大 body(上传的用例、JSON 响应)不该整段进日志
MAX_STRING_CHARS = 2000

# 整个请求体不读内容的阈值 —— 超过只记字节数。
# multipart 上传(用例附件、OSS 文件)可能几十 MB, 全量 decode 再脱敏纯属浪费
MAX_BODY_LOG_BYTES = 64 * 1024

# 递归深度上限 —— 防御恶意构造的深层嵌套把日志打爆
MAX_DEPTH = 6


def is_sensitive_key(key: Any) -> bool:
    """键名是否命中敏感词。非字符串键一律不敏感(交给值处理)。"""
    if not isinstance(key, str):
        return False
    return bool(SENSITIVE_KEY_PATTERN.search(key))


def sanitize_payload(payload: Any, _depth: int = 0) -> Any:
    """
    递归脱敏请求体: 敏感键的值换成 `***`, 超长字符串截断, 过深的嵌套用占位符。

    返回值只用于日志展示, **不会**回写给业务逻辑。
    """
    if _depth > MAX_DEPTH:
        return "...(层级过深, 已截断)"

    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            sanitized[key] = MASK if is_sensitive_key(key) else sanitize_payload(value, _depth + 1)
        return sanitized

    if isinstance(payload, (list, tuple)):
        return [sanitize_payload(item, _depth + 1) for item in payload]

    if isinstance(payload, str) and len(payload) > MAX_STRING_CHARS:
        return f"{payload[:MAX_STRING_CHARS]}...({len(payload)} chars)"

    return payload


def _sanitize_path(path: str) -> str:
    """path 掩码: 优先认已知敏感前缀, 都不命中再走高熵段兜底。"""
    segments = path.split("/")
    # 倒着找最近的前缀 —— 命中就掩掉末段, 如 /auth/reset/check/<token>
    for index in range(len(segments) - 1, 0, -1):
        prefix = "/".join(segments[:index]) + "/"
        if prefix.endswith(SENSITIVE_PATH_PREFIXES):
            segments[-1] = MASK
            break
    else:
        segments = [MASK if HIGH_ENTROPY_SEGMENT.match(segment) else segment for segment in segments]
    return "/".join(segments)


def sanitize_url(url: str) -> str:
    """
    URL 掩码: query 里敏感键的值 + path 里的 token / email 段。

    fragment 直接丢掉 —— hash 路由(前端 `#/user/resetPassword?token=...`)里的
    token 走 query 同一套规则, 而且 fragment 对服务端排查没有价值。
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "<无法解析的 URL>"

    query = ""
    if parsed.query:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        # safe="*" —— 否则 urlencode 会把掩码编成 %2A%2A%2A, 日志里反而认不出是掩码
        query = urlencode([(key, MASK if is_sensitive_key(key) else value) for key, value in pairs],
                          safe="*")

    return urlunparse((parsed.scheme, parsed.netloc, _sanitize_path(parsed.path), parsed.params, query, ""))

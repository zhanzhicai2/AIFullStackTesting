from typing import List, Optional

from pydantic import BaseModel, validator

from app.schema.base import PityModel

# 单次输入的字节上限 —— 这几个接口全是「粘一段文本进来算」的工具,
# 不设上限等于给内存开一个无界入口(尤其 AES/DES 要整块进内存)。
TEXT_MAX_LEN = 1024 * 1024

# 支持的哈希算法白名单 —— **不在白名单里的一律拒绝**,
# 否则 `hashlib.new(user_input)` 等于把算法选择权交给调用方。
HASH_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")


class JsonDiffForm(BaseModel):
    """JSON 深度对比 —— 期望值 vs 实际值, 由断言引擎同款 `JsonCompare` 出结果。"""

    expected: str
    actual: str

    @validator("expected", "actual")
    def text_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("expected", "actual")
    def text_not_too_long(cls, v):
        if len(v) > TEXT_MAX_LEN:
            raise ValueError(f"单边 JSON 不能超过 {TEXT_MAX_LEN} 字符")
        return v


class NetCheckForm(BaseModel):
    """内网地址判断 —— 传 IP / 域名 / URL, 解析后逐个 IP 判定是否命中内网规则。"""

    target: str

    @validator("target")
    def target_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("target")
    def target_not_too_long(cls, v):
        # 域名最长 253, URL 再长也用不上 —— 卡死即可, 别让 getaddrinfo 收到巨串
        if len(v) > 2048:
            raise ValueError("目标地址过长")
        return v


class CryptoForm(BaseModel):
    """
    对称加解密。`key` / `iv` 由调用方给 —— **不复用 `app/utils/des.py`**:
    那个模块的 KEY 是写死的 `'pityspwd'`, 服务的是邮箱 token 场景, 拿它当通用
    工具的默认密钥会让所有人在同一个密钥下加密。
    """

    action: str
    text: str
    algorithm: str = "aes"
    key: Optional[str] = None
    iv: Optional[str] = None
    # 密文/明文的编解码格式 —— 接口报文里 base64 和 hex 都常见
    encoding: str = "hex"

    @validator("action")
    def action_valid(cls, v):
        if v not in ("encrypt", "decrypt"):
            raise ValueError("action 只能是 encrypt 或 decrypt")
        return v

    @validator("algorithm")
    def algorithm_valid(cls, v):
        if v not in ("aes", "des"):
            raise ValueError("algorithm 只能是 aes 或 des")
        return v

    @validator("encoding")
    def encoding_valid(cls, v):
        if v not in ("hex", "base64"):
            raise ValueError("encoding 只能是 hex 或 base64")
        return v

    @validator("text")
    def text_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("text")
    def text_not_too_long(cls, v):
        if len(v) > TEXT_MAX_LEN:
            raise ValueError(f"文本不能超过 {TEXT_MAX_LEN} 字符")
        return v

    @validator("key", "iv")
    def key_iv_length(cls, v, field):
        if v is None:
            return v
        if len(v) == 0:
            return None
        if len(v) > 256:
            raise ValueError(f"{field.name} 过长")
        return v


class HashForm(BaseModel):
    """
    摘要计算。走后端而不是前端 —— 见 `routers/tool/crypto.py` 的模块注释。

    `key` 非空时额外算 HMAC(接口签名场景) —— 与纯摘要共用一个端点,
    因为页面上就是「同一个输入框, 填不填密钥」的区别, 拆成两个端点只会让
    调用方猜「我该用哪个」。
    """

    text: str
    algorithms: Optional[List[str]] = None
    key: Optional[str] = None

    @validator("text")
    def text_not_empty(cls, v):
        return PityModel.not_empty(v)

    @validator("text")
    def text_not_too_long(cls, v):
        if len(v) > TEXT_MAX_LEN:
            raise ValueError(f"文本不能超过 {TEXT_MAX_LEN} 字符")
        return v

    @validator("algorithms")
    def algorithms_valid(cls, v):
        if v is None:
            return v
        if not v:
            return None
        unknown = [a for a in v if a not in HASH_ALGORITHMS]
        if unknown:
            raise ValueError(f"不支持的算法: {', '.join(unknown)}")
        # 去重且保持调用方给的顺序
        seen = set()
        ordered = []
        for a in v:
            if a not in seen:
                seen.add(a)
                ordered.append(a)
        return ordered

    @validator("key")
    def key_length(cls, v):
        if v is None or v == "":
            return None
        if len(v) > 1024:
            raise ValueError("密钥过长")
        return v

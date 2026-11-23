"""
对称加解密 + 摘要计算。

**为什么 Hash 走后端而不是前端** —— 两条硬理由:
1. `crypto.subtle.digest` 只在**安全上下文**(https / localhost)可用, 平台
   内网部署走 http 时 `crypto.subtle` 直接是 `undefined`, 页面一算就崩;
2. Web Crypto **没有 MD5**, 而接口签名场景算得最多的恰恰是 MD5 ——
   前端要补 MD5 只能引第三方库或手搓实现, 都不如后端 `hashlib` 一行。

**为什么不复用 `app/utils/des.py`** —— 那个模块的 KEY 写死 `'pityspwd'`,
服务的是邮箱 token 场景。当通用工具的默认密钥用, 等于让所有人在同一个
密钥下加密, 且改它会波及 `auth/user.py` 的既有密文。

密钥长度**不自动补齐/截断**: 静默补零会让两边各自以为 key 一致, 加出来
的密文对方永远解不开, 这类问题排查起来最费时间。
"""
import base64
import binascii
import hashlib
import hmac
from typing import Optional

from Crypto.Cipher import AES, DES
from Crypto.Util.Padding import pad, unpad
from fastapi import APIRouter, Depends

from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.tool import HASH_ALGORITHMS, CryptoForm, HashForm

router = APIRouter()

# 算法 → (块大小, 允许的 key 字节数)
_BLOCK = {"des": (8, (8,)), "aes": (16, (16, 24, 32))}


def _key_bytes(key: Optional[str], algorithm: str) -> bytes:
    """校验并编码密钥 —— 长度不符直接报错, 不做任何补齐"""
    _block, allowed = _BLOCK[algorithm]
    if key is None or key == "":
        raise ValueError(f"{algorithm.upper()} 必须提供密钥, 长度为 "
                         f"{'/'.join(str(n) for n in allowed)} 字节")
    raw = key.encode("utf-8")
    if len(raw) not in allowed:
        raise ValueError(
            f"{algorithm.upper()} 密钥必须是 {'/'.join(str(n) for n in allowed)} "
            f"字节(当前 UTF-8 编码后 {len(raw)} 字节), 请检查是否含中文或空格")
    return raw


def _iv_bytes(iv: Optional[str], key: bytes, algorithm: str) -> bytes:
    """
    IV: 给了就按字节校验, 没给就派生 ——
    - DES 默认 IV = key(与 `utils/des.py` 既有密文保持可解)
    - AES 默认 IV = key 前 16 字节
    """
    block, _allowed = _BLOCK[algorithm]
    if iv is None or iv == "":
        if algorithm == "des":
            return key
        return key[:block] if len(key) >= block else key.ljust(block, b"\0")
    raw = iv.encode("utf-8")
    if len(raw) != block:
        raise ValueError(f"IV 必须是 {block} 字节(当前 {len(raw)} 字节)")
    return raw


def _decode(text: str, encoding: str) -> bytes:
    try:
        if encoding == "hex":
            return binascii.a2b_hex(text.strip())
        return base64.b64decode(text.strip(), validate=True)
    except Exception as err:
        raise ValueError(f"密文不是合法的 {encoding}: {err}")


def _encode(data: bytes, encoding: str) -> str:
    if encoding == "hex":
        return binascii.b2a_hex(data).decode()
    return base64.b64encode(data).decode()


@router.post("/hash", summary="计算文本摘要 / HMAC 签名")
def compute_hash(data: HashForm, _=Depends(Permission())):
    names = data.algorithms or list(HASH_ALGORITHMS)
    raw = data.text.encode("utf-8")

    digests = {}
    hmacs = {}
    for name in names:
        h = hashlib.new(name)
        h.update(raw)
        digests[name] = h.hexdigest()
        if data.key:
            # HMAC 与纯摘要同端点, 只是多给一个 key —— 见 HashForm 的注释
            hmacs[name] = hmac.new(
                data.key.encode("utf-8"), raw, getattr(hashlib, name)).hexdigest()

    return PityResponse.success(data=dict(
        digests=digests,
        hmacs=hmacs or None,
        bytes=len(raw),
        char_count=len(data.text),
    ))


@router.post("/crypto/symmetric", summary="DES/AES 对称加解密")
def symmetric(data: CryptoForm, _=Depends(Permission())):
    try:
        key = _key_bytes(data.key, data.algorithm)
        iv = _iv_bytes(data.iv, key, data.algorithm)
        cipher_cls = DES if data.algorithm == "des" else AES
        block, _allowed = _BLOCK[data.algorithm]

        if data.action == "encrypt":
            cipher = cipher_cls.new(key, cipher_cls.MODE_CBC, iv)
            out = cipher.encrypt(pad(data.text.encode("utf-8"), block))
            result = _encode(out, data.encoding)
        else:
            raw = _decode(data.text, data.encoding)
            if len(raw) % block != 0:
                return PityResponse.failed(
                    f"密文长度 {len(raw)} 不是 {block} 的整数倍, 无法按 "
                    f"{data.encoding} 解码后分块解密")
            cipher = cipher_cls.new(key, cipher_cls.MODE_CBC, iv)
            result = unpad(cipher.decrypt(raw), block).decode("utf-8")

        return PityResponse.success(data=dict(
            result=result,
            algorithm=data.algorithm,
            action=data.action,
            encoding=data.encoding,
        ))
    except ValueError as err:
        return PityResponse.failed(str(err))
    except Exception as err:
        return PityResponse.failed(f"{data.algorithm.upper()} {data.action} 失败: {err}")

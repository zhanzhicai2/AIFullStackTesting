"""
实用工具(`/tool/*`)自测 —— **不依赖数据库**。

覆盖: schema 白名单与长度上限、密钥/IV 校验、加解密往返、摘要已知向量、
内网判定与 URL 主机提取、JSON 差异。

跑法:
    cd backend && .venv/bin/python scripts/tool_selftest.py
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILED = []
PASSED = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILED.append(f"{name} {detail}".strip())
        print(f"  ✗ {name} {detail}")


# ---------------------------------------------------------------------------
# 1. schema 校验
# ---------------------------------------------------------------------------

def test_schema():
    print("== schema 校验 ==")
    from pydantic import ValidationError

    from app.schema.tool import CryptoForm, HashForm, JsonDiffForm, NetCheckForm

    def rejected(fn, **kw):
        try:
            fn(**kw)
            return None
        except (ValidationError, Exception) as err:  # noqa: BLE001
            return str(err)

    # action / algorithm / encoding 白名单
    check("拒绝未知 action",
          rejected(CryptoForm, action="delete", text="x") is not None)
    check("拒绝未知 algorithm",
          rejected(CryptoForm, action="encrypt", text="x", algorithm="rc4") is not None)
    check("拒绝未知 encoding",
          rejected(CryptoForm, action="encrypt", text="x", encoding="binary") is not None)
    check("放行合法表单", rejected(CryptoForm, action="encrypt", text="x") is None)

    # 空文本拒绝
    check("空 text 被拒", rejected(CryptoForm, action="encrypt", text="   ") is not None)
    check("空 target 被拒", rejected(NetCheckForm, target="  ") is not None)

    # 超长输入拒绝
    check("超长 JSON 被拒",
          rejected(JsonDiffForm, expected="x" * (1024 * 1024 + 1), actual="{}") is not None)
    check("超长 target 被拒", rejected(NetCheckForm, target="a" * 3000) is not None)

    # 哈希算法白名单 —— 不在名单里一律拒绝, 不给 hashlib.new(user_input) 的口子
    check("拒绝未知哈希算法", rejected(HashForm, text="x", algorithms=["blake2b"]) is not None)
    check("放行 md5/sha256",
          rejected(HashForm, text="x", algorithms=["md5", "sha256"]) is None)
    check("算法去重保序",
          HashForm(text="x", algorithms=["sha256", "md5", "sha256"]).algorithms == ["sha256", "md5"])
    check("空算法列表归一为 None", HashForm(text="x", algorithms=[]).algorithms is None)


# ---------------------------------------------------------------------------
# 2. 摘要已知向量
# ---------------------------------------------------------------------------

def test_hash():
    print("== 摘要已知向量 ==")
    from app.routers.tool.crypto import compute_hash
    from app.schema.tool import HashForm

    # RFC / NIST 公开向量, 输入固定为 abc
    known = {
        "md5": "900150983cd24fb0d6963f7d28e17f72",
        "sha1": "a9993e364706816aba3e25717850c26c9cd0d89d",
        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "sha512": ("ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
                   "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"),
    }
    res = compute_hash(HashForm(text="abc"))
    assert res["code"] == 0, res
    for algo, expect in known.items():
        check(f"{algo}(abc)", res["data"]["digests"][algo] == expect,
              res["data"]["digests"].get(algo, ""))

    # 中文按 UTF-8 编码 —— 前端若用 btoa 会在这里对不上
    zh = compute_hash(HashForm(text="中文"))
    assert zh["code"] == 0, zh
    import hashlib
    check("中文按 UTF-8", zh["data"]["digests"]["md5"] == hashlib.md5("中文".encode()).hexdigest())
    check("字节数按 UTF-8", zh["data"]["bytes"] == len("中文".encode("utf-8")))

    # 未填 key 时没有 hmacs
    check("无 key 时 hmacs 为 None", res["data"]["hmacs"] is None)

    # 填了 key 才有 HMAC, 且与标准实现一致
    hm = compute_hash(HashForm(text="abc", key="secret"))
    assert hm["code"] == 0, hm
    import hmac as hmac_mod
    expect_hmac = hmac_mod.new(b"secret", b"abc", hashlib.sha256).hexdigest()
    check("HMAC-SHA256", hm["data"]["digests"] is not None and
          hm["data"]["hmacs"]["sha256"] == expect_hmac, hm["data"].get("hmacs"))
    check("HMAC 不污染裸摘要", hm["data"]["digests"]["sha256"] == known["sha256"])


# ---------------------------------------------------------------------------
# 3. 对称加解密
# ---------------------------------------------------------------------------

def test_crypto():
    print("== 对称加解密 ==")
    from app.routers.tool.crypto import symmetric
    from app.schema.tool import CryptoForm

    # AES 往返
    enc = symmetric(CryptoForm(action="encrypt", text="pity测试123", algorithm="aes",
                               key="pity-aes-key-001", encoding="hex"))
    assert enc["code"] == 0, enc
    cipher = enc["data"]["result"]
    check("AES 密文为 hex", len(cipher) > 0 and all(c in "0123456789abcdef" for c in cipher))
    dec = symmetric(CryptoForm(action="decrypt", text=cipher, algorithm="aes",
                               key="pity-aes-key-001", encoding="hex"))
    assert dec["code"] == 0, dec
    check("AES 加解密往返", dec["data"]["result"] == "pity测试123", dec["data"])

    # base64 输出
    enc64 = symmetric(CryptoForm(action="encrypt", text="hello", algorithm="aes",
                                 key="pity-aes-key-001", encoding="base64"))
    assert enc64["code"] == 0, enc64
    dec64 = symmetric(CryptoForm(action="decrypt", text=enc64["data"]["result"],
                                 algorithm="aes", key="pity-aes-key-001",
                                 encoding="base64"))
    assert dec64["code"] == 0, dec64
    check("base64 往返", dec64["data"]["result"] == "hello")

    # DES 往返(默认 IV = key, 与 utils/des.py 行为一致)
    denc = symmetric(CryptoForm(action="encrypt", text="des-roundtrip", algorithm="des",
                                key="pitykey!", encoding="hex"))
    assert denc["code"] == 0, denc
    ddec = symmetric(CryptoForm(action="decrypt", text=denc["data"]["result"], algorithm="des",
                                key="pitykey!", encoding="hex"))
    assert ddec["code"] == 0, ddec
    check("DES 加解密往返", ddec["data"]["result"] == "des-roundtrip", ddec["data"])

    # 密钥长度不符必须报错, 不能静默补齐
    bad = symmetric(CryptoForm(action="encrypt", text="x", algorithm="aes", key="short"))
    check("AES 短密钥被拒", bad["code"] != 0, str(bad))
    check("报错提示字节数", "字节" in str(bad.get("msg", "")), str(bad))

    bad_des = symmetric(CryptoForm(action="encrypt", text="x", algorithm="des", key="toolongkey"))
    check("DES 非 8 字节密钥被拒", bad_des["code"] != 0, str(bad_des))

    # 缺密钥
    nokey = symmetric(CryptoForm(action="encrypt", text="x", algorithm="aes"))
    check("缺密钥被拒", nokey["code"] != 0, str(nokey))

    # IV 长度不对
    bad_iv = symmetric(CryptoForm(action="encrypt", text="x", algorithm="aes",
                                  key="pity-aes-key-001", iv="short"))
    check("AES 短 IV 被拒", bad_iv["code"] != 0, str(bad_iv))

    # 非 hex 密文解密
    not_hex = symmetric(CryptoForm(action="decrypt", text="zzzz", algorithm="aes",
                                   key="pity-aes-key-001", encoding="hex"))
    check("非 hex 密文被拒", not_hex["code"] != 0, str(not_hex))

    # 密文长度不是块整数倍
    odd = symmetric(CryptoForm(action="decrypt", text="abcd", algorithm="aes",
                               key="pity-aes-key-001", encoding="hex"))
    check("非块整数倍密文被拒", odd["code"] != 0, str(odd))


# ---------------------------------------------------------------------------
# 4. 内网判定 / URL 主机提取
# ---------------------------------------------------------------------------

def test_network():
    print("== 内网判定 ==")
    from app.routers.tool.network import _classify, _extract_host
    from app.utils.ui_security import is_blocked_ip

    # 主机提取: 裸 IP / 带端口 / 完整 URL / 带路径 / IPv6 字面量
    cases = {
        "192.168.1.1": "192.168.1.1",
        "192.168.1.1:8080": "192.168.1.1",
        "https://api.example.com/v1/users?x=1": "api.example.com",
        "example.com/a/b": "example.com",
        "example.com:3000/path": "example.com",
        "[::1]:8080": "::1",
        "http://User:Pass@Host.example.com/x": "host.example.com",
    }
    for raw, expect in cases.items():
        check(f"extract({raw!r})", _extract_host(raw) == expect,
              f"got {_extract_host(raw)!r}")

    # 网段判定与 ui_security 同源
    blocked = ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.1", "169.254.169.254",
               "0.0.0.0", "100.64.0.1", "224.0.0.1", "::1", "fe80::1", "::ffff:127.0.0.1"]
    for ip in blocked:
        hit = _classify(ip)
        check(f"{ip} 命中网段", hit is not None and hit["network"] is not None, str(hit))
        check(f"{ip} is_blocked_ip", is_blocked_ip(ip) is True)
        check(f"{ip} 标签非空", bool(hit and hit["label"]))

    public = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::6810:85e5"]
    for ip in public:
        check(f"{ip} 判为公网", is_blocked_ip(ip) is False)

    # 映射地址按内层 IPv4 判
    check("IPv4 映射地址按内层判", _classify("::ffff:192.168.1.1")["network"] == "192.168.0.0/16")
    check("映射公网地址不误杀", _classify("::ffff:8.8.8.8") is None)


# ---------------------------------------------------------------------------
# 5. JSON 差异
# ---------------------------------------------------------------------------

def test_json_diff():
    print("== JSON 差异 ==")
    from app.routers.tool.compare import json_diff
    from app.schema.tool import JsonDiffForm

    # 完全一致
    same = json_diff(JsonDiffForm(expected='{"a":1}', actual='{"a":1}'))
    assert same["code"] == 0, same
    check("一致时 identical", same["data"]["identical"] is True and same["data"]["diffs"] == [])

    # 类型不同
    t = json_diff(JsonDiffForm(expected='{"a":1}', actual='{"a":"1"}'))
    assert t["code"] == 0, t
    check("类型差异被指出", any("类型不一致" in d for d in t["data"]["diffs"]), str(t["data"]))

    # 缺字段
    m = json_diff(JsonDiffForm(expected='{"a":1,"b":2}', actual='{"a":1}'))
    assert m["code"] == 0, m
    check("缺字段被指出", any("不存在" in d for d in m["data"]["diffs"]), str(m["data"]))

    # 非法 JSON 走 110 而不是 500
    bad = json_diff(JsonDiffForm(expected="{oops", actual="{}"))
    check("非法 JSON 返回业务码", bad["code"] != 0, str(bad))
    check("错误信息说明是哪一边", "期望值" in str(bad.get("msg", "")), str(bad))

    # 数组顺序敏感(与断言引擎口径一致)
    arr = json_diff(JsonDiffForm(expected='[1,2]', actual='[2,1]'))
    assert arr["code"] == 0, arr
    check("数组顺序敏感", arr["data"]["identical"] is False, str(arr["data"]))


# ---------------------------------------------------------------------------

def main():
    test_schema()
    test_hash()
    test_crypto()
    test_network()
    test_json_diff()
    print(f"\n通过 {PASSED} 项, 失败 {len(FAILED)} 项")
    if FAILED:
        for f in FAILED:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("✅ tool_selftest 全部通过")


if __name__ == "__main__":
    main()

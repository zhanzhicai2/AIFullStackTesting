"""
内网地址判断 —— 复用 SSRF 拦截的同一套判定规则(`app/utils/ui_security.py`)。

**这是防御性工具**: 输入一个 IP / 域名 / URL, 告诉你它解析到哪些地址、
哪些命中内网/保留网段。判定规则与 UI 自动化的出网边界完全同源 ——
工具说"放行"而执行器说"拦截"是最糟的情况, 所以直接 import 网段表,
不在这里另抄一份。

DNS 解析(`resolve_host`)只发 UDP/TCP 的 DNS 查询, **不发任何 HTTP 请求**,
所以这个接口没有「拿平台当跳板访问内网」的面。
"""
import ipaddress
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.tool import NetCheckForm
from app.utils.ui_security import IPV4_BLOCKED, IPV6_BLOCKED, is_blocked_ip, resolve_host

router = APIRouter()

# 网段 → 中文标签 —— 只为工具页展示, 判定本身仍走 `is_blocked_ip`
_NETWORK_LABELS = {
    "0.0.0.0/8": "本网络",
    "10.0.0.0/8": "私有地址",
    "100.64.0.0/10": "运营商级 NAT",
    "127.0.0.0/8": "环回地址",
    "169.254.0.0/16": "链路本地(云厂商元数据)",
    "172.16.0.0/12": "私有地址",
    "192.0.0.0/24": "IETF 协议分配",
    "192.0.2.0/24": "文档示例地址",
    "192.168.0.0/16": "私有地址",
    "198.18.0.0/15": "基准测试网段",
    "198.51.100.0/24": "文档示例地址",
    "203.0.113.0/24": "文档示例地址",
    "224.0.0.0/4": "组播地址",
    "240.0.0.0/4": "保留地址",
    "::/128": "未指定地址",
    "::1/128": "环回地址",
    "fc00::/7": "唯一本地地址",
    "fe80::/10": "链路本地地址",
    "ff00::/8": "组播地址",
}


def _classify(ip: str) -> Optional[dict]:
    """命中哪个网段 —— 返回网段与标签; 没命中返回 None"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return dict(network=None, label="地址无法解析")

    # IPv4 映射地址按内层再判一次(与 is_blocked_ip 同款处理)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return _classify(str(addr.ipv4_mapped))
        if addr.sixtofour is not None:
            return _classify(str(addr.sixtofour))
        nets = IPV6_BLOCKED
    else:
        nets = IPV4_BLOCKED
    for net in nets:
        if addr in net:
            key = str(net)
            return dict(network=key, label=_NETWORK_LABELS.get(key, "保留网段"))
    return None


def _extract_host(target: str) -> str:
    """
    从输入里取出待判定的主机 —— 支持直接给 IP / 域名, 也支持粘整个 URL。

    带 scheme 的按 URL 解析; 不带 scheme 但带路径的(`example.com/a/b`)按 URL 补
    scheme 解析, 否则 urlparse 会把 `example.com` 当成 path 而不是 netloc。
    """
    raw = (target or "").strip()
    if "://" in raw:
        return (urlparse(raw).hostname or "").strip().lower()
    if "/" in raw or "?" in raw:
        return (urlparse("http://" + raw).hostname or "").strip().lower()
    # 纯 host:port 或裸 IP/域名 —— 去掉方括号(IPv6 字面量)与端口
    host = raw.split("/", 1)[0].split("?", 1)[0]
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    else:
        host = host.split(":", 1)[0]
    return host.strip().lower()


@router.post("/net/check", summary="判断 IP/域名/URL 是否指向内网")
def net_check(data: NetCheckForm, _=Depends(Permission())):
    host = _extract_host(data.target)
    if not host:
        return PityResponse.failed("无法从输入中解析出主机名")

    # IP 字面量直接用; 域名走 DNS(一个域名可能解析到多个地址, 必须逐个判)
    try:
        ipaddress.ip_address(host)
        ips: List[str] = [host]
        resolved = True
    except ValueError:
        ips = resolve_host(host)
        resolved = len(ips) > 0

    if not resolved:
        return PityResponse.failed(
            f"域名 {host} 无法解析(不存在或 DNS 不可达) —— 若它是内网服务, "
            f"请直接填写 IP 地址再试")

    detail = []
    for ip in ips:
        hit = _classify(ip)
        blocked = is_blocked_ip(ip)
        detail.append(dict(
            ip=ip,
            blocked=blocked,
            # 命中网段才有意义; 公网地址给 None, 页面据此显示「公网」
            network=hit["network"] if hit else None,
            label=hit["label"] if hit else "公网地址",
        ))

    blocked_ips = [d["ip"] for d in detail if d["blocked"]]
    return PityResponse.success(data=dict(
        target=data.target,
        host=host,
        resolved=True,
        ips=detail,
        # 任一 IP 被拦即算被拦 —— 与 `check_url` 的「逐个检查」语义一致
        blocked=len(blocked_ips) > 0,
        blocked_ips=blocked_ips,
        total=len(detail),
    ))

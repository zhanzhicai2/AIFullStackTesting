"""
SSRF 拦截 —— UI 自动化的浏览器出网边界

**这是本 feature 新引入的两个安全面之一**, 另一个是录制脚本解析。

浏览器能自由访问内网地址, 所以平台 MUST 在**每个**出网请求上做校验:
只允许 http/https, 目标域名必须在本项目白名单内, 且域名解析后的**每一个** IP
都不能落在私网/环回/链路本地/保留网段。少做一步就等于把内网暴露给被测站点。

六个检查点(逐条对应 data-model.md §7.2):

1. 协议白名单 —— 仅 http / https
2. 域名匹配 —— 项目级白名单(精确匹配或 `*.example.com` 子域通配)
3. 主机地址拦截 —— **DNS 解析后**逐个 IP 检查
4. 重定向 —— 跟随每一跳时**重新执行 1-3**
5. 子资源 —— 页面内的静态资源请求同样受 1-3 约束
6. 步骤内 URL —— 相对路径拼到 base_url 后再过 1-3; 绝对 URL 直接过 1-3

**白名单为空 = 该项目不允许访问任何站点**(不是"允许全部")—— 刻意选的失败方向。
"""
import ipaddress
import socket
from typing import Iterable, List, Optional
from urllib.parse import urlparse, urljoin

# 明确列出的网段 —— 不依赖 ipaddress.is_private 的版本差异
IPV4_BLOCKED = [
    ipaddress.ip_network("0.0.0.0/8"),        # 本网络
    ipaddress.ip_network("10.0.0.0/8"),       # 私有
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),      # 环回
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地(云厂商元数据 169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),    # 私有
    ipaddress.ip_network("192.0.0.0/24"),     # IETF 协议分配
    ipaddress.ip_network("192.0.2.0/24"),     # 文档用
    ipaddress.ip_network("192.168.0.0/16"),   # 私有
    ipaddress.ip_network("198.18.0.0/15"),    # 基准测试
    ipaddress.ip_network("198.51.100.0/24"),  # 文档用
    ipaddress.ip_network("203.0.113.0/24"),   # 文档用
    ipaddress.ip_network("224.0.0.0/4"),      # 组播
    ipaddress.ip_network("240.0.0.0/4"),      # 保留
]
IPV6_BLOCKED = [
    ipaddress.ip_network("::/128"),           # 未指定
    ipaddress.ip_network("::1/128"),          # 环回
    ipaddress.ip_network("fc00::/7"),         # 唯一本地地址
    ipaddress.ip_network("fe80::/10"),        # 链路本地
    ipaddress.ip_network("ff00::/8"),         # 组播
]

ALLOWED_SCHEMES = ("http", "https")


class UINavigationBlocked(Exception):
    """
    目标地址被 SSRF 策略拒绝。

    :param reason: 机器可读的分类, 对应 contracts/api.md §3.2 的失败原因分类
    :param message: 面向用户的中文说明
    """

    def __init__(self, message: str, reason: str = "navigation_blocked"):
        super().__init__(message)
        self.message = message
        self.reason = reason


def is_blocked_ip(ip: str) -> bool:
    """判断单个 IP 是否落在禁止网段内"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        # 解析不出来的地址一律拒绝 —— 宁可误杀也不放行
        return True
    if isinstance(addr, ipaddress.IPv6Address):
        # IPv4 映射地址(::ffff:127.0.0.1)要按内层 IPv4 再判一次
        if addr.ipv4_mapped is not None:
            return is_blocked_ip(str(addr.ipv4_mapped))
        if addr.sixtofour is not None:
            return is_blocked_ip(str(addr.sixtofour))
        return any(addr in net for net in IPV6_BLOCKED)
    return any(addr in net for net in IPV4_BLOCKED)


def domain_allowed(host: str, allowed_domains: Iterable[str]) -> bool:
    """
    判断主机名是否命中项目白名单。

    - 精确匹配: `example.com`
    - 子域通配: `*.example.com` 匹配 `a.example.com` / `a.b.example.com`
      (**不匹配** `example.com` 本身 —— 需要同时配置两条, 这是刻意保持严格的语义)
    """
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return False
    for raw in allowed_domains or []:
        rule = (raw or "").strip().lower().rstrip(".")
        if not rule:
            continue
        if rule.startswith("*."):
            suffix = rule[2:]
            if host.endswith("." + suffix) and host != suffix:
                return True
        elif host == rule:
            return True
    return False


def resolve_host(host: str) -> List[str]:
    """解析主机名, 返回全部 IP —— 一个域名可能解析到多个地址, 必须逐个检查"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    result = []
    for info in infos:
        address = info[4][0]
        if address not in result:
            result.append(address)
    return result


def check_url(url: str, allowed_domains: Iterable[str], allow_empty_list: bool = False) -> str:
    """
    校验一个绝对 URL 是否可以访问。

    :param url: 目标地址
    :param allowed_domains: 项目级允许域名列表
    :param allow_empty_list: 白名单为空时是否放行 —— **执行期一律为 False**
                            (白名单为空 = 不可执行), 仅供单元校验使用
    :return: 规范化后的 URL
    :raises UINavigationBlocked: 任何一项不通过
    """
    if not url or not url.strip():
        raise UINavigationBlocked("目标地址不能为空")
    url = url.strip()
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    # 检查点 1: 协议白名单
    if scheme not in ALLOWED_SCHEMES:
        raise UINavigationBlocked(f"仅支持 http / https 协议, 当前为「{scheme or '空'}」")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UINavigationBlocked("目标地址缺少主机名")
    # 检查点 2: 域名匹配项目白名单
    domains = list(allowed_domains or [])
    if not domains and not allow_empty_list:
        raise UINavigationBlocked("本项目尚未配置允许访问的域名")
    if domains and not domain_allowed(host, domains):
        raise UINavigationBlocked(f"目标域名 {host} 不在本项目允许列表内")
    # 检查点 3: DNS 解析后逐个 IP 检查
    ips = resolve_host(host)
    if not ips:
        # 主机名是 IP 字面量时解析不出地址, 直接按字面量判
        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            raise UINavigationBlocked(f"目标域名 {host} 无法解析")
    for ip in ips:
        if is_blocked_ip(ip):
            raise UINavigationBlocked(f"目标地址解析到内网地址({ip}), 已按安全策略拒绝")
    return url


def url_host(url: str) -> str:
    """取 URL 的主机名(小写) —— 解析不出来返回空串"""
    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:
        return ""


def resolve_step_url(base_url: str, target: str, allowed_domains: Iterable[str]) -> str:
    """
    检查点 6: 步骤里的 URL。

    - 相对路径 → 拼到 base_url 之后再过一遍校验
    - 绝对 URL → 直接过一遍校验
    """
    if not target or not target.strip():
        raise UINavigationBlocked("目标地址不能为空")
    target = target.strip()
    parsed = urlparse(target)
    if parsed.scheme:
        return check_url(target, allowed_domains)
    if not base_url:
        raise UINavigationBlocked("步骤没有提供 base_url, 无法解析相对地址")
    joined = urljoin(base_url if base_url.endswith("/") else base_url + "/", target)
    return check_url(joined, allowed_domains)

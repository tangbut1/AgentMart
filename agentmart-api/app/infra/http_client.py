"""SSRF-safe outbound HTTP client.

Rules enforced here (security requirement):
- only http/https schemes are allowed;
- the host is resolved and checked before every request: localhost,
  loopback, private, link-local, reserved and multicast addresses are
  rejected;
- the connection is pinned to the IP address that was validated, so a
  DNS answer that changes between the check and the connect (DNS
  rebinding / TOCTOU) cannot redirect the request into the private
  network. TLS SNI and certificate verification still use the original
  hostname;
- redirects are followed manually so every hop is re-validated and
  re-pinned;
- credentials never appear in logs (only method/host/status are logged).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import settings


class UnsafeURLError(ValueError):
    """URL 被安全策略拒绝（非 http/https，或指向内网/保留地址）。"""


_BLOCKED_HOSTNAMES = {
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]",
    "metadata.google.internal", "metadata.goog",
}

# 额外的 IPv6 前缀：Python 的 ipaddress 在某些版本不把它们判为 private
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("::ffff:0:0/96"),      # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),       # NAT64（可映射到 IPv4 内网）
    ipaddress.ip_network("100::/64"),           # discard-only
    ipaddress.ip_network("2001:db8::/32"),      # documentation
]

# Clash / Mihomo / Surge 的 TUN/Fake-IP 模式会把域名解析到 198.18.0.0/15，
# 再由代理把流量送到真正的公网。RFC 2544 把这段划给基准测试，Python 的
# ipaddress 因此判 is_private=True，于是开着代理的开发者一调外部接口就被
# 这里全量拒绝，报"禁止访问内网/保留地址"——那是误杀，不是真的在防内网。
#
# 但这段地址在没有 TUN 代理的机器上确实不可路由，放开着也是白连；只有在
# 运维明确知道本机走 Fake-IP 时才该放开。所以做成显式开关，默认仍旧拦死，
# 并且只放开这唯一一段，不动其它私有网段。
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _allow_fake_ip() -> bool:
    return str(
        os.environ.get("AGENTMART_ALLOW_FAKE_IP", "")
    ).strip().lower() in ("1", "true", "yes", "on")


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        # 唯一例外：本机确实跑在 Fake-IP 代理后面，且已显式打开开关
        if _allow_fake_ip() and ip.version == 4 and ip in _FAKE_IP_NETWORK:
            return False
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


def _resolve_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"无法解析主机 {host}: {exc}") from exc
    return [info[4][0] for info in infos]


@dataclass(frozen=True)
class PinnedTarget:
    """一个已校验并固定 IP 的目标地址。"""

    url: str          # 规范化后的原始 URL（保留原主机名）
    host: str         # 原主机名（用于 Host 头与 SNI）
    ip: str           # 已校验的公网 IP（实际连接目标）
    port: int
    scheme: str


def _parse(url: str) -> tuple[str, str, int, str]:
    if not url or not isinstance(url, str):
        raise UnsafeURLError("URL 为空")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"仅允许 http/https 协议，收到: {parsed.scheme or '空'}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL 缺少主机名")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return url.strip(), host, port, parsed.scheme


def validate_url(url: str) -> str:
    """校验 URL 安全性并返回规范化 URL；不安全时抛出 UnsafeURLError。"""
    normalized, host, _, _ = _parse(url)
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"禁止访问内部地址: {host}")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_is_blocked(literal):
            raise UnsafeURLError(f"禁止访问内网/保留地址: {host}")
        return normalized

    for ip_str in _resolve_ips(host):
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise UnsafeURLError(
                f"主机 {host} 解析到内网/保留地址 {ip_str}，已拒绝请求"
            )
    return normalized


def resolve_and_pin(url: str) -> PinnedTarget:
    """校验 URL，并把连接目标固定到已校验的 IP（防 DNS rebinding）。

    主机名本身是 IP 字面量时直接使用；否则解析 DNS，要求所有结果均为
    公网地址，并取第一个作为连接目标。
    """
    normalized, host, port, scheme = _parse(url)
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"禁止访问内部地址: {host}")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_is_blocked(literal):
            raise UnsafeURLError(f"禁止访问内网/保留地址: {host}")
        return PinnedTarget(url=normalized, host=host, ip=host, port=port, scheme=scheme)

    ips: list[str] = []
    for ip_str in _resolve_ips(host):
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise UnsafeURLError(
                f"主机 {host} 解析到内网/保留地址 {ip_str}，已拒绝请求"
            )
        ips.append(ip_str)
    if not ips:
        raise UnsafeURLError(f"主机 {host} 没有可用的公网地址")
    return PinnedTarget(url=normalized, host=host, ip=ips[0], port=port, scheme=scheme)


def _pinned_url(target: PinnedTarget, path_and_query: str) -> str:
    """把请求 URL 的主机名替换为已固定的 IP，保留端口与路径。"""
    host_part = f"[{target.ip}]" if ":" in target.ip else target.ip
    default = target.port == (443 if target.scheme == "https" else 80)
    authority = host_part if default else f"{host_part}:{target.port}"
    return f"{target.scheme}://{authority}{path_and_query}"


def _host_header(target: PinnedTarget) -> str:
    default = target.port == (443 if target.scheme == "https" else 80)
    host_part = f"[{target.host}]" if ":" in target.host else target.host
    return host_part if default else f"{host_part}:{target.port}"


class SafeHttpClient:
    """带 SSRF 校验、IP 固定、重试与超时的 httpx 客户端封装。"""

    def __init__(self, timeout: Optional[float] = None, max_retries: Optional[int] = None):
        self.timeout = timeout or settings.HTTP_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.HTTP_MAX_RETRIES
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "SafeHttpClient":
        # trust_env=False：不使用系统代理。代理会自行解析主机名，
        # 使我们基于 DNS 解析结果的内网地址校验被绕过，带来 SSRF 风险。
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,  # 手动跟随以便逐跳校验与重新固定 IP
            trust_env=False,
            headers={"User-Agent": DEFAULT_UA, "Accept": "application/json, text/plain, */*"},
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SafeHttpClient 需要作为异步上下文管理器使用")
        return self._client

    def _build(
        self,
        method: str,
        target: PinnedTarget,
        *,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Request:
        """构造一个连接到已固定 IP、但 Host/SNI 仍为原主机名的请求。"""
        probe = httpx.URL(target.url)
        pinned = _pinned_url(target, probe.raw_path.decode("ascii") or "/")
        request = self.client.build_request(
            method,
            pinned,
            params=params,
            data=data,
            json=json,
            headers=headers or {},
        )
        # httpx 会用 URL 主机名自动生成 Host 头；这里改回真实主机名，
        # 否则基于虚拟主机/CDN 的服务会拒绝或路由到错误站点。
        request.headers["Host"] = _host_header(target)
        # TLS SNI 与证书校验仍使用真实主机名
        request.extensions["sni_hostname"] = target.host
        return request

    async def _send_with_retry(self, request: httpx.Request) -> httpx.Response:
        attempts = max(1, self.max_retries)

        @retry(
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            reraise=True,
        )
        async def _do() -> httpx.Response:
            return await self.client.send(request)

        return await _do()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        max_redirects: int = 3,
    ) -> httpx.Response:
        """发起请求：校验 → 固定 IP → 手动逐跳跟随重定向（每跳重新校验）。"""
        current = url
        current_params = params
        for _ in range(max_redirects + 1):
            target = resolve_and_pin(current)
            request = self._build(
                method, target, params=current_params, data=data, json=json, headers=headers
            )
            logger.debug(f"HTTP {method} {target.host}{request.url.path}")
            response = await self._send_with_retry(request)
            if response.is_redirect:
                location = response.headers.get("location", "")
                if not location:
                    break
                current = validate_url(httpx.URL(current).join(location).__str__())
                # 重定向后原始查询参数已包含在 location 中
                current_params = None
                data = None
                json = None
                continue
            response.raise_for_status()
            return response
        raise httpx.TooManyRedirects("重定向次数超过限制")

    async def get_json(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        max_redirects: int = 3,
    ) -> dict:
        response = await self.request(
            "GET", url, params=params, headers=headers, max_redirects=max_redirects
        )
        return response.json()

    async def post_form(
        self,
        url: str,
        data: dict,
        headers: Optional[dict] = None,
        max_redirects: int = 3,
    ) -> dict:
        response = await self.request(
            "POST", url, data=data, headers=headers, max_redirects=max_redirects
        )
        return response.json()


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

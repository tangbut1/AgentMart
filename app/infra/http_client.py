"""SSRF-safe outbound HTTP client.

Rules enforced here (security requirement):
- only http/https schemes are allowed;
- the host is resolved and checked before every request: localhost,
  loopback, private, link-local, reserved and multicast addresses are
  rejected;
- redirects are followed manually so every hop is re-validated;
- credentials never appear in logs (only method/host/status are logged).
"""
from __future__ import annotations

import ipaddress
import socket
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


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"无法解析主机 {host}: {exc}") from exc
    return [info[4][0] for info in infos]


def validate_url(url: str) -> str:
    """校验并返回规范化 URL；不安全时抛出 UnsafeURLError。"""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("URL 为空")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"仅允许 http/https 协议，收到: {parsed.scheme or '空'}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL 缺少主机名")
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"禁止访问内部地址: {host}")

    # 主机名本身是 IP 字面量时直接判断
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_is_blocked(literal):
            raise UnsafeURLError(f"禁止访问内网/保留地址: {host}")
        return url.strip()

    for ip_str in _resolve_ips(host):
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise UnsafeURLError(
                f"主机 {host} 解析到内网/保留地址 {ip_str}，已拒绝请求"
            )
    return url.strip()


class SafeHttpClient:
    """带 SSRF 校验、重试与超时的 httpx 客户端封装。"""

    def __init__(self, timeout: Optional[float] = None, max_retries: Optional[int] = None):
        self.timeout = timeout or settings.HTTP_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.HTTP_MAX_RETRIES
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "SafeHttpClient":
        # trust_env=False：不使用系统代理。代理会自行解析主机名，
        # 使我们基于 DNS 解析结果的内网地址校验被绕过，带来 SSRF 风险。
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,  # 手动跟随以便逐跳校验
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

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _send(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        logger.debug(f"HTTP {request.method} {host}{request.url.path}")
        return await self.client.send(request)

    async def get_json(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        max_redirects: int = 3,
    ) -> dict:
        safe_url = validate_url(url)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": DEFAULT_UA},
        ) as client:
            current = safe_url
            for _ in range(max_redirects + 1):
                resp = await client.get(current, params=params, headers=headers or {})
                if resp.is_redirect:
                    location = resp.headers.get("location", "")
                    if not location:
                        break
                    current = validate_url(httpx.URL(current).join(location).__str__())
                    params = None  # 重定向后参数已包含在 location 中
                    continue
                resp.raise_for_status()
                return resp.json()
        raise httpx.TooManyRedirects("重定向次数超过限制")

    async def post_form(self, url: str, data: dict, headers: Optional[dict] = None) -> dict:
        safe_url = validate_url(url)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": DEFAULT_UA},
        ) as client:
            resp = await client.post(safe_url, data=data, headers=headers or {})
            resp.raise_for_status()
            return resp.json()


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

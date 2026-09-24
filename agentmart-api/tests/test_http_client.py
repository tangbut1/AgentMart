"""SSRF 防护测试。"""
from __future__ import annotations

import ipaddress

import pytest

from app.infra.http_client import (
    UnsafeURLError,
    _pinned_url,
    _host_header,
    resolve_and_pin,
    validate_url,
)


@pytest.mark.parametrize("url", [
    "http://localhost/api",
    "http://127.0.0.1:8000/api",
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://192.168.1.1/admin",
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/",  # 云元数据地址
    "file:///etc/passwd",
    "ftp://example.com/file",
    "gopher://example.com/",
    "javascript:alert(1)",
    "",
])
def test_rejects_unsafe_urls(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


@pytest.mark.parametrize("url", [
    "https://api.bilibili.com/x/web-interface/view",
    "http://example.com/path?query=1",
])
def test_allows_public_urls(url):
    assert validate_url(url) == url


@pytest.mark.parametrize("url", [
    "http://[::ffff:127.0.0.1]/",       # IPv4-mapped IPv6 环回
    "http://[64:ff9b::7f00:1]/",        # NAT64 映射到 127.0.0.1
    "http://[100::1]/",                 # discard-only
    "http://[2001:db8::1]/",            # documentation
    "http://224.0.0.1/",                # multicast
    "http://255.255.255.255/",
])
def test_rejects_additional_reserved_ranges(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_resolve_and_pin_rejects_private_host():
    with pytest.raises(UnsafeURLError):
        resolve_and_pin("http://127.0.0.1:8080/x")


def test_resolve_and_pin_uses_ip_literal_directly():
    target = resolve_and_pin("https://93.184.216.34/path?a=1")
    assert target.ip == "93.184.216.34"
    assert target.host == "93.184.216.34"
    assert target.port == 443


def test_resolve_and_pin_public_host_resolves_to_public_ip():
    """公网主机名必须被固定到一个公网 IP（防 DNS rebinding）。"""
    target = resolve_and_pin("https://example.com/")
    ip = ipaddress.ip_address(target.ip)
    assert not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    ), f"固定到了内网地址 {target.ip}"
    assert target.host == "example.com"


def test_pinned_url_rewrites_host_but_keeps_path_and_port():
    target = resolve_and_pin("https://93.184.216.34:8443/a/b?c=d")
    assert _pinned_url(target, "/a/b?c=d") == "https://93.184.216.34:8443/a/b?c=d"
    assert _host_header(target) == "93.184.216.34:8443"


def test_pinned_url_brackets_ipv6():
    target = resolve_and_pin("https://[2606:2800:220:1:248:1893:25c8:1946]/x")
    assert _pinned_url(target, "/x") == "https://[2606:2800:220:1:248:1893:25c8:1946]/x"
    assert _host_header(target) == "[2606:2800:220:1:248:1893:25c8:1946]"


def test_host_header_omits_default_port():
    target = resolve_and_pin("https://example.com:443/x")
    assert _host_header(target) == "example.com"

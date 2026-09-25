"""SSRF 防护测试。"""
from __future__ import annotations

import ipaddress

import pytest

from app.infra.http_client import (
    UnsafeURLError,
    _ip_is_blocked,
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


# ---- Fake-IP 代理（Clash / Mihido / Surge TUN）----
# 这类代理把域名解析到 198.18.0.0/15，再由代理转发到真正的公网。
# RFC 2544 把这段划给基准测试，Python 的 ipaddress 因此判 is_private=True，
# 早期实现把它和内网一起拒掉，导致开着代理的开发者一调外部接口就全量失败。
# 现在做成显式开关：默认仍旧拦死，只有明确打开才放开，且只放开这一段。

def _with_fake_ip(monkeypatch, value: str):
    monkeypatch.setenv("AGENTMART_ALLOW_FAKE_IP", value)


def test_fake_ip_is_blocked_by_default(monkeypatch):
    """默认必须拦住：大多数机器上 198.18.x.x 不可路由，放开了也没用。"""
    monkeypatch.delenv("AGENTMART_ALLOW_FAKE_IP", raising=False)
    ip = ipaddress.ip_address("198.18.0.1")
    assert _ip_is_blocked(ip) is True
    with pytest.raises(UnsafeURLError):
        validate_url("http://198.18.0.1/x")


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_fake_ip_allowed_only_with_explicit_switch(monkeypatch, value):
    _with_fake_ip(monkeypatch, value)
    ip = ipaddress.ip_address("198.18.0.1")
    assert _ip_is_blocked(ip) is False


@pytest.mark.parametrize("value", ["", "0", "false", "off", "banana"])
def test_fake_ip_still_blocked_for_unrecognized_values(monkeypatch, value):
    _with_fake_ip(monkeypatch, value)
    assert _ip_is_blocked(ipaddress.ip_address("198.18.0.1")) is True


def test_switch_does_not_open_other_private_ranges(monkeypatch):
    """开关只放开 198.18.0.0/15 这一段，别的内网照旧拦住。"""
    _with_fake_ip(monkeypatch, "1")
    for ip in ("192.168.1.1", "10.0.0.1", "172.16.0.1", "127.0.0.1", "169.254.169.254"):
        assert _ip_is_blocked(ipaddress.ip_address(ip)) is True, ip


def test_switch_does_not_open_addresses_outside_fake_ip_range(monkeypatch):
    """只放开 198.18.0.0/15 这一段；段外的保留地址照旧拦住。

    注意只列**本来就该被拦**的地址。公网地址（如 1.1.1.1）从来就不拦，
    拿它来断言会得到一个假阳性通过。
    """
    _with_fake_ip(monkeypatch, "1")
    for ip in ("198.51.100.7", "203.0.113.9", "192.0.2.1"):
        assert _ip_is_blocked(ipaddress.ip_address(ip)) is True, ip
    # 公网地址依旧通行（开关不影响正常访问）
    assert _ip_is_blocked(ipaddress.ip_address("1.1.1.1")) is False

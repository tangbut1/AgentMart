"""SSRF 防护测试。"""
from __future__ import annotations

import pytest

from app.infra.http_client import UnsafeURLError, validate_url


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

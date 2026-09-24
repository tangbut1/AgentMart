"""AgentMart 个人浏览器版。

版本标识 ``1.0.0-browser``：不依赖任何电商开放接口，由本机可见的浏览器
会话在用户亲自登录的官方页面上读取数据。

这是独立可运行的项目，不依赖仓库里的官方 API 架构版。
"""
from __future__ import annotations

VERSION = "1.0.0-browser"
ARCHITECTURE = "personal-browser"

__all__ = ["VERSION", "ARCHITECTURE"]

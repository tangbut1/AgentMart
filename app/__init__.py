"""AgentMart 应用包。

版本说明
--------
``VERSION`` 形如 ``<产品版本>-<架构标识>``：

- ``1.0.0-api``     官方 API 架构版。数据来自各电商平台开放接口；
                    未配置开发者凭据时明确显示「未接入」，演示数据与
                    真实数据严格分离。**电商官方 API 未实际授权接入**，
                    演示数据不是真实报价。
- ``1.0.0-browser`` 个人浏览器版。不依赖电商开放 API，由本机可见的
                    浏览器会话在用户亲自登录的官方页面上读取数据。
"""
from __future__ import annotations

VERSION = "1.0.0-api"
ARCHITECTURE = "official-api"

__all__ = ["VERSION", "ARCHITECTURE"]

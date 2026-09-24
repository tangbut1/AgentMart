"""AgentMart 官方 API 架构版。

版本标识 ``1.0.0-api``：数据来自各电商平台开放接口；未配置开发者凭据时
明确显示「未接入」，演示数据与真实数据严格分离。
**电商官方 API 未实际授权接入**，演示数据不是真实报价。

这是独立可运行的项目，不依赖仓库里的个人浏览器版。
"""
from __future__ import annotations

VERSION = "1.0.0-api"
ARCHITECTURE = "official-api"

__all__ = ["VERSION", "ARCHITECTURE"]

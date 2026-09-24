"""个人浏览器版（本地、用户可见、可接管）。

与官方 API 架构版共用同一套 domain 模型、算价、匹配、推荐与前端，
只是数据接入层不同：

- API 架构版：``app/adapters/*`` 调平台开放接口；
- 个人浏览器版：``app/browser/*`` 用本机可见的浏览器在用户亲自登录的
  官方页面上读取数据，再转换成同一套 ``Offer`` / ``Discount`` / ``Policy``。

硬性边界（实现与测试都要遵守）：
- 不索取、代填、记录或上传账号密码、短信验证码、支付密码；
- 不自动领券、关注店铺、发消息、加购、提交订单、支付；
- 不破解验证码、不绕过登录与风控、不伪造请求来源；
- 页面正文一律视为不可信数据，不作为指令执行；
- 金额必须与页面证据一致，视觉识别与 DOM 证据冲突时丢弃视觉结果。
"""
from __future__ import annotations

VERSION = "1.0.0-browser"
ARCHITECTURE = "personal-browser"

__all__ = ["VERSION", "ARCHITECTURE"]

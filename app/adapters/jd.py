"""京东适配器（京东开放平台 / 京东联盟）。

API: https://api.jd.com/routerjson  (method: jd.union.open.goods.query)
凭据: JD_APP_KEY / JD_APP_SECRET / JD_ACCESS_TOKEN（联盟推广权限）

未配置凭据时返回 NOT_CONNECTED，不产生任何数据。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import List, Optional

from loguru import logger

from ..config import settings
from ..domain.enums import (
    ConditionKind,
    DataStatus,
    DiscountKind,
    Platform,
    ShopType,
)
from ..domain.models import Discount, Offer, Policy
from ..infra.http_client import SafeHttpClient
from ..infra.ratelimit import rate_limiter
from .base import PlatformAdapter


class JDAdapter(PlatformAdapter):
    platform = Platform.JD
    adapter_name = "jd_union_api"
    display_name = "京东"
    docs_url = "https://open.jd.com/home/home#/doc/api?apiCateId=102"
    required_env = ["JD_APP_KEY", "JD_APP_SECRET", "JD_ACCESS_TOKEN"]

    def _sign(self, params: dict) -> str:
        # MD5 是京东开放平台签名协议强制要求的算法（app_secret + 排序参数 + app_secret），
        # 此处用于满足第三方 API 协议，不用于口令存储或数据完整性保护。
        sorted_params = sorted(params.items())
        sign_str = settings.JD_APP_SECRET
        for k, v in sorted_params:
            sign_str += k + str(v)
        sign_str += settings.JD_APP_SECRET
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    def _build_params(self, method: str, biz_param: dict) -> dict:
        params = {
            "app_key": settings.JD_APP_KEY,
            "method": method,
            "access_token": settings.JD_ACCESS_TOKEN,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
            "360buy_param_json": json.dumps(biz_param),
        }
        params["sign"] = self._sign(params)
        return params

    async def _search(self, keyword: str, page: int = 1, page_size: int = 20, **kwargs) -> List[Offer]:
        if not rate_limiter.allow("jd", rate_per_sec=0.5, burst=2):
            raise RuntimeError("京东接口限流中，请稍后重试")
        biz_param = {
            "keyword": keyword,
            "pageIndex": page,
            "pageSize": page_size,
            "sortName": kwargs.get("sort_by") or "default",
        }
        params = self._build_params("jd.union.open.goods.query", biz_param)
        async with SafeHttpClient() as http:
            data = await http.post_form(settings.JD_API_BASE_URL, params)
        return self._parse(data, keyword)

    def _parse(self, data: dict, keyword: str) -> List[Offer]:
        items = (
            data.get("jd_union_open_goods_query_response", {})
            .get("result", {})
            .get("data", [])
        )
        offers: List[Offer] = []
        for item in items:
            sku_id = str(item.get("skuId", ""))
            if not sku_id:
                continue
            price_info = item.get("priceInfo", {}) or {}
            price = float(price_info.get("price", 0) or 0)
            original = float(price_info.get("originalPrice", price) or price)
            shop_type = ShopType.SELF_OPERATED if item.get("isJdSale") else ShopType.UNKNOWN
            offer = Offer(
                platform=Platform.JD,
                platform_product_id=sku_id,
                title=item.get("skuName", keyword),
                url=f"https://item.jd.com/{sku_id}.html",
                list_price=price,
                shop_name=item.get("shopName") or ("京东自营" if shop_type == ShopType.SELF_OPERATED else None),
                shop_type=shop_type,
                brand=item.get("brandName"),
                images=[item.get("imageInfo", {}).get("imageUrl", "")] if item.get("imageInfo") else [],
                sales_text=str(item.get("inOrderCount30Days", "")) + "人付款" if item.get("inOrderCount30Days") else None,
                fetched_at=datetime.now(),
                verified_at=datetime.now(),
                credibility=0.8 if shop_type == ShopType.SELF_OPERATED else 0.5,
                affiliate=True,  # 联盟接口返回的链接带返佣
                policies=[],
            )
            # 佣金率等字段原样保留在 note 中，避免伪造折扣
            commission = item.get("commissionInfo", {})
            if commission:
                offer.match_notes.append(
                    f"联盟接口佣金率 {commission.get('commissionShare', '未知')}（不影响用户价格）"
                )
            if original > price:
                offer.discounts.append(Discount(
                    kind=DiscountKind.ACTIVITY,
                    label="页面直降/活动价",
                    amount=round(original - price, 2),
                    condition="商品页当前活动价",
                    condition_kind=ConditionKind.UNCONDITIONAL,
                    source_url=offer.url,
                    data_status=DataStatus.REAL,
                ))
            offers.append(offer)
        return offers

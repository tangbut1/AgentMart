"""拼多多适配器（拼多多开放平台 · 多多客）。

API: https://gw-api.pinduoduo.com/api/router  (method: pdd.ddk.goods.search)
凭据: PDD_CLIENT_ID / PDD_CLIENT_SECRET（开放平台应用 + 多多客推广权限）

未配置凭据时返回 NOT_CONNECTED，不产生任何数据。
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import List

from ..config import settings
from ..domain.enums import (
    ConditionKind,
    DataStatus,
    DiscountKind,
    Platform,
    ShopType,
)
from ..domain.models import Discount, Offer
from ..infra.http_client import SafeHttpClient
from ..infra.ratelimit import rate_limiter
from .base import PlatformAdapter


class PddAdapter(PlatformAdapter):
    platform = Platform.PDD
    adapter_name = "pdd_ddk_api"
    display_name = "拼多多"
    docs_url = "https://open.pinduoduo.com/application/document/api"
    required_env = ["PDD_CLIENT_ID", "PDD_CLIENT_SECRET"]

    def _sign(self, params: dict) -> str:
        # MD5 为拼多多开放平台签名协议强制算法，仅用于满足第三方 API 协议。
        sign_str = settings.PDD_CLIENT_SECRET
        for k in sorted(params):
            sign_str += k + str(params[k])
        sign_str += settings.PDD_CLIENT_SECRET
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    async def _search(self, keyword: str, page: int = 1, page_size: int = 20, **kwargs) -> List[Offer]:
        if not rate_limiter.allow("pdd", rate_per_sec=0.5, burst=2):
            raise RuntimeError("拼多多接口限流中，请稍后重试")
        biz = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "sort_type": kwargs.get("sort_by") or "0",
            "with_coupon": True,
        }
        params = {
            "type": "pdd.ddk.goods.search",
            "client_id": settings.PDD_CLIENT_ID,
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
            "data": json.dumps(biz, ensure_ascii=False),
        }
        params["sign"] = self._sign(params)
        async with SafeHttpClient() as http:
            data = await http.post_form(settings.PDD_API_BASE_URL, params)
        return self._parse(data)

    def _parse(self, data: dict) -> List[Offer]:
        items = (
            data.get("goods_search_response", {})
            .get("goods_list", [])
        )
        offers: List[Offer] = []
        for item in items:
            goods_id = str(item.get("goods_id", ""))
            if not goods_id:
                continue
            price = float(item.get("min_group_price", 0) or 0) / 100  # 分为单位
            normal = float(item.get("min_normal_price", price) or price) / 100
            mall = item.get("mall_id") not in (None, 0, "")
            offer = Offer(
                platform=Platform.PDD,
                platform_product_id=goods_id,
                title=item.get("goods_name", ""),
                url=f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}",
                list_price=round(price, 2),
                shop_name=item.get("mall_name"),
                shop_type=ShopType.FLAGSHIP if mall else ShopType.THIRD_PARTY,
                images=[item.get("goods_image_url", "")] if item.get("goods_image_url") else [],
                sales_text=(
                    f"已拼 {item['sales_tip']} 件" if item.get("sales_tip") else None
                ),
                fetched_at=datetime.now(),
                verified_at=datetime.now(),
                credibility=0.6 if mall else 0.45,
                affiliate=True,
            )
            coupon = item.get("coupon_discount")
            if coupon and float(coupon) > 0:
                offer.discounts.append(Discount(
                    kind=DiscountKind.COUPON,
                    label=f"店铺券 ¥{float(coupon) / 100:.2f}",
                    amount=float(coupon) / 100,
                    condition="需在商品页领取店铺券",
                    condition_kind=ConditionKind.CONDITIONAL,
                    source_url=offer.url,
                    data_status=DataStatus.REAL,
                ))
            if normal > price:
                offer.discounts.append(Discount(
                    kind=DiscountKind.ACTIVITY,
                    label="拼单价",
                    amount=round(normal - price, 2),
                    condition="商品页当前拼单活动价",
                    condition_kind=ConditionKind.UNCONDITIONAL,
                    source_url=offer.url,
                    data_status=DataStatus.REAL,
                ))
            offers.append(offer)
        return offers

"""抖音电商适配器（抖音开放平台）。

凭据: DOUYIN_CLIENT_KEY / DOUYIN_CLIENT_SECRET / DOUYIN_ACCESS_TOKEN

说明：抖音电商的商品/团购 API 按应用资质逐步开放，不同应用的可用
接口路径不同。本适配器实现通用的 client_credentials 取号流程，
商品搜索路径通过 DOUYIN_GOODS_SEARCH_PATH 配置（在开放平台控制台
的「已授权接口」列表中查找，见 README）。未配置时不返回任何数据，
绝不伪造商品信息。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..config import settings
from ..domain.enums import Platform, ShopType
from ..domain.models import Offer
from ..infra.http_client import SafeHttpClient
from ..infra.ratelimit import rate_limiter
from .base import PlatformAdapter


class DouyinAdapter(PlatformAdapter):
    platform = Platform.DOUYIN
    adapter_name = "douyin_open_api"
    display_name = "抖音电商"
    docs_url = "https://open.douyin.com/platform"
    required_env = [
        "DOUYIN_CLIENT_KEY",
        "DOUYIN_CLIENT_SECRET",
        "DOUYIN_ACCESS_TOKEN",
        "DOUYIN_GOODS_SEARCH_PATH",
    ]

    async def _fetch_access_token(self) -> Optional[str]:
        if settings.DOUYIN_ACCESS_TOKEN:
            return settings.DOUYIN_ACCESS_TOKEN
        async with SafeHttpClient() as http:
            data = await http.get_json(
                f"{settings.DOUYIN_API_BASE_URL.rstrip('/')}/oauth/access_token/",
                params={
                    "client_key": settings.DOUYIN_CLIENT_KEY,
                    "client_secret": settings.DOUYIN_CLIENT_SECRET,
                    "grant_type": "client_credential",
                },
            )
        return (data.get("data") or {}).get("access_token")

    async def _search(self, keyword: str, page: int = 1, page_size: int = 20, **kwargs) -> List[Offer]:
        if not rate_limiter.allow("douyin", rate_per_sec=0.5, burst=2):
            raise RuntimeError("抖音接口限流中，请稍后重试")
        token = await self._fetch_access_token()
        if not token:
            raise RuntimeError("无法获取抖音 access_token，请检查 DOUYIN_* 配置")

        url = (
            settings.DOUYIN_API_BASE_URL.rstrip("/")
            + settings.DOUYIN_GOODS_SEARCH_PATH
        )
        async with SafeHttpClient() as http:
            data = await http.get_json(
                url,
                params={
                    "access_token": token,
                    "keyword": keyword,
                    "count": page_size,
                    "cursor": (page - 1) * page_size,
                },
            )
        return self._parse(data)

    def _parse(self, data: dict) -> List[Offer]:
        items = (data.get("data") or {}).get("list") or []
        offers: List[Offer] = []
        for item in items:
            product_id = str(item.get("product_id") or item.get("id") or "")
            if not product_id:
                continue
            price = float(item.get("price", 0) or 0)
            if price > 1000:
                price = price / 100  # 部分接口以分计价
            offer = Offer(
                platform=Platform.DOUYIN,
                platform_product_id=product_id,
                title=item.get("title") or item.get("name") or "",
                url=item.get("url") or f"https://haohuo.jinritemai.com/views/product/item2?id={product_id}",
                list_price=round(price, 2),
                shop_name=item.get("shop_name"),
                shop_type=ShopType.UNKNOWN,
                images=[item["cover"]] if item.get("cover") else [],
                sales_text=item.get("sales"),
                fetched_at=datetime.now(),
                verified_at=datetime.now(),
                credibility=0.45,
                affiliate=True,
            )
            offers.append(offer)
        return offers

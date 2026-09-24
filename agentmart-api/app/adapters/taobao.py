"""淘宝 / 天猫适配器（淘宝开放平台 · 淘宝客）。

API: https://eco.taobao.com/router/rest  (method: taobao.tbk.dg.item.get)
凭据: TAOBAO_APP_KEY / TAOBAO_APP_SECRET / TAOBAO_ACCESS_TOKEN（淘宝客权限）

淘宝与天猫共用同一套开放平台 API，但通过 user_type / shop 字段区分店铺来源，
在 Offer 上以 platform 与 shop_type 区分展示，不把两者数据混为一谈。
"""
from __future__ import annotations

import hashlib
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


class TaobaoBaseAdapter(PlatformAdapter):
    docs_url = "https://open.taobao.com/doc.htm?docId=101635&docType=1"
    required_env = ["TAOBAO_APP_KEY", "TAOBAO_APP_SECRET", "TAOBAO_ACCESS_TOKEN"]

    def _sign(self, params: dict) -> str:
        # MD5 为淘宝开放平台签名协议强制算法，仅用于满足第三方 API 协议。
        sorted_params = sorted(params.items())
        sign_str = settings.TAOBAO_APP_SECRET
        for k, v in sorted_params:
            sign_str += k + str(v)
        sign_str += settings.TAOBAO_APP_SECRET
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    def _build_params(self, method: str, extra: dict) -> dict:
        params = {
            "method": method,
            "app_key": settings.TAOBAO_APP_KEY,
            "session": settings.TAOBAO_ACCESS_TOKEN,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
        }
        params.update(extra)
        params["sign"] = self._sign(params)
        return params

    async def _search(self, keyword: str, page: int = 1, page_size: int = 20, **kwargs) -> List[Offer]:
        if not rate_limiter.allow("taobao", rate_per_sec=0.5, burst=2):
            raise RuntimeError("淘宝接口限流中，请稍后重试")
        extra = {
            "q": keyword,
            "page_no": page,
            "page_size": page_size,
            "sort": kwargs.get("sort_by") or "default",
            "material_id": "2836",
        }
        params = self._build_params("taobao.tbk.dg.item.get", extra)
        async with SafeHttpClient() as http:
            data = await http.post_form(settings.TAOBAO_API_BASE_URL, params)
        return self._parse(data)

    def _shop_type(self, item: dict) -> ShopType:
        # user_type: 0 淘宝 / 1 天猫；shop_type 字段需联盟权限才返回。
        # 仅依据接口明确返回的字段判定店铺类型，不用店名猜测——
        # 店名里的「旗舰店」不等于平台认证的官方旗舰店。
        user_type = item.get("user_type")
        if user_type == 1:
            return ShopType.FLAGSHIP
        if user_type == 0:
            return ShopType.THIRD_PARTY
        return ShopType.UNKNOWN

    def _parse(self, data: dict) -> List[Offer]:
        result = (
            data.get("tbk_dg_item_get_response", {})
            .get("result", {})
            .get("result_list", {})
            .get("map_data", [])
        )
        offers: List[Offer] = []
        for item in result:
            item_id = str(item.get("item_id", ""))
            if not item_id:
                continue
            zk_price = float(item.get("zk_final_price", 0) or 0)
            reserve = float(item.get("reserve_price", zk_price) or zk_price)
            is_tmall = item.get("user_type") == 1
            platform = Platform.TMALL if is_tmall else Platform.TAOBAO
            offer = Offer(
                platform=platform,
                platform_product_id=item_id,
                title=item.get("title", ""),
                url=item.get("item_url") or f"https://item.taobao.com/item.htm?id={item_id}",
                list_price=zk_price,
                shop_name=item.get("shop_title") or item.get("nick"),
                shop_type=self._shop_type(item),
                images=[item.get("pict_url", "")] if item.get("pict_url") else [],
                sales_text=f"月售 {item.get('volume', 0)}" if item.get("volume") else None,
                fetched_at=datetime.now(),
                verified_at=datetime.now(),
                credibility=0.6 if is_tmall else 0.5,
                affiliate=True,
            )
            coupon = item.get("coupon_amount")
            if coupon and float(coupon) > 0:
                offer.discounts.append(Discount(
                    kind=DiscountKind.COUPON,
                    label=f"优惠券 ¥{coupon}",
                    amount=float(coupon),
                    condition="需在商品页领取优惠券",
                    condition_kind=ConditionKind.CONDITIONAL,
                    source_url=offer.url,
                    data_status=DataStatus.REAL,
                ))
            if reserve > zk_price:
                offer.discounts.append(Discount(
                    kind=DiscountKind.ACTIVITY,
                    label="活动价",
                    amount=round(reserve - zk_price, 2),
                    condition="商品页当前活动价",
                    condition_kind=ConditionKind.UNCONDITIONAL,
                    source_url=offer.url,
                    data_status=DataStatus.REAL,
                ))
            offers.append(offer)
        return offers


class TaobaoAdapter(TaobaoBaseAdapter):
    platform = Platform.TAOBAO
    adapter_name = "taobao_tbk_api"
    display_name = "淘宝"


class TmallAdapter(TaobaoBaseAdapter):
    platform = Platform.TMALL
    adapter_name = "tmall_tbk_api"
    display_name = "天猫"

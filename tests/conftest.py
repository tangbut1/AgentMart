"""测试公共 fixture。"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.enums import (
    ConditionKind,
    DataStatus,
    DiscountKind,
    Platform,
    PolicyCategory,
    PolicyScope,
    ShopType,
)
from app.domain.models import Discount, Offer, Policy


def make_offer(
    platform=Platform.JD,
    product_id="1001",
    title="索尼 WH-1000XM5 无线降噪耳机 黑色 国行",
    price="2999.00",
    shipping="0",
    data_status=DataStatus.REAL,
    shop_type=ShopType.SELF_OPERATED,
    discounts=None,
    fetched_at=None,
) -> Offer:
    return Offer(
        platform=platform,
        platform_product_id=product_id,
        title=title,
        url=f"https://item.example.com/{product_id}",
        list_price=Decimal(price),
        shipping_fee=Decimal(shipping),
        shop_name="测试店铺",
        shop_type=shop_type,
        data_status=data_status,
        source="test",
        fetched_at=fetched_at or datetime.utcnow(),
        discounts=discounts or [],
        policies=[
            Policy(
                scope=PolicyScope.PLATFORM_RULE,
                category=PolicyCategory.AFTER_SALES,
                title="七天无理由",
                summary="测试政策",
            )
        ],
    )


@pytest.fixture
def now():
    return datetime(2026, 1, 15, 12, 0, 0)

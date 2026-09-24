"""演示数据提供器。

⚠️ 这里的所有商品、价格、优惠、评测均为**虚构的演示数据**，仅用于
开发联调与界面走查。每条数据的 data_status 都是 DEMO，前端会以
「演示数据」标识展示，且不参与任何真实价格结论与推荐。
只有在请求显式携带 include_demo=true 时才会返回。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Optional

from ..domain.enums import (
    CommercialRelation,
    ConditionKind,
    CurationStatus,
    DataStatus,
    DiscountKind,
    Platform,
    PolicyCategory,
    PolicyScope,
    ReviewPlatform,
    ShopType,
)
from ..domain.models import Discount, Offer, Policy, Review

DEMO_LABEL = "演示数据（虚构，仅用于开发联调，不代表真实在售商品）"

# 演示用：识别关键词中的容量规格，用于生成「不同容量」的第二组演示商品
_STORAGE_RE = re.compile(r"(\d{2,4})\s*(GB|G|TB|T)\b", re.IGNORECASE)


def _next_storage(keyword: str) -> Optional[str]:
    """返回翻倍后的容量规格（如 256G → 512G），没有容量规格时返回 None。"""
    m = _STORAGE_RE.search(keyword)
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2).upper()
    if unit.startswith("T"):
        return None  # TB 规格不再翻倍，避免出现不合理的演示容量
    doubled = value * 2
    if doubled > 2048:
        return None
    return f"{doubled}{unit}"


def _swap_storage(keyword: str, new_storage: str) -> str:
    return _STORAGE_RE.sub(new_storage, keyword, count=1)


def _stable_price(keyword: str, salt: str, base: int) -> float:
    digest = hashlib.sha256(f"{keyword}|{salt}".encode("utf-8")).hexdigest()
    return round(base + (int(digest[:6], 16) % 900) / 10.0, 2)


def demo_offers(keyword: str) -> List[Offer]:
    """按关键词确定性生成 5 个平台的演示 offer。

    关键词含容量规格时，额外生成一组「翻倍容量」的演示商品，
    用于演示同款匹配（容量不同绝不合并）与横向对比视图。
    """
    offers = _demo_offers_for_title(keyword, "在售链接")
    bigger = _next_storage(keyword)
    if bigger:
        variant_title = _swap_storage(keyword, bigger)
        offers += _demo_offers_for_title(variant_title, "在售链接（更大容量）")
    return offers


def _demo_offers_for_title(keyword: str, suffix: str) -> List[Offer]:
    now = datetime.now()
    specs = [
        (Platform.JD, "京东自营旗舰店", ShopType.SELF_OPERATED, 3200),
        (Platform.TMALL, "品牌官方旗舰店", ShopType.OFFICIAL_FLAGSHIP, 3100),
        (Platform.TAOBAO, "淘宝数码专营店", ShopType.THIRD_PARTY, 2950),
        (Platform.PDD, "拼多多品牌好店", ShopType.THIRD_PARTY, 2880),
        (Platform.DOUYIN, "抖音电商直播间", ShopType.UNKNOWN, 3050),
    ]
    offers: List[Offer] = []
    for platform, shop, shop_type, base in specs:
        price = _stable_price(keyword, platform.value, base)
        product_id = hashlib.sha256(f"demo|{keyword}|{platform.value}".encode()).hexdigest()[:10]
        offer = Offer(
            platform=platform,
            platform_product_id=f"demo-{product_id}",
            title=f"{keyword} 【演示】{platform.label}{suffix}",
            url=f"https://example.com/demo/{platform.value}/{product_id}",
            list_price=price,
            shop_name=shop,
            shop_type=shop_type,
            sku_text="演示规格（虚构）",
            shipping_fee=0.0 if platform in (Platform.JD, Platform.TMALL) else 6.0,
            data_status=DataStatus.DEMO,
            source="demo_provider",
            source_url=f"https://example.com/demo/{platform.value}/{product_id}",
            fetched_at=now,
            credibility=0.5,
        )
        offer.discounts = [
            Discount(
                kind=DiscountKind.ACTIVITY,
                label="平台活动直降（演示）",
                amount=round(price * 0.04, 2),
                condition="商品页当前活动价",
                condition_kind=ConditionKind.UNCONDITIONAL,
                data_status=DataStatus.DEMO,
                source_url=offer.url,
            ),
            Discount(
                kind=DiscountKind.COUPON,
                label="满 3000 减 200 优惠券（演示）",
                amount=200,
                condition="需在商品页领取，仅本商品可用",
                condition_kind=ConditionKind.CONDITIONAL,
                stack_group="coupon",
                data_status=DataStatus.DEMO,
                source_url=offer.url,
            ),
            Discount(
                kind=DiscountKind.SUBSIDY,
                label="国家补贴（演示，资格待核实）",
                amount=round(price * 0.10, 2),
                condition="需满足当地国补活动资格，规则以当地商务部门公示为准",
                condition_kind=ConditionKind.UNVERIFIABLE,
                region_limit="部分地区",
                eligibility="个人限领件数、指定品类",
                data_status=DataStatus.DEMO,
                source_url=offer.url,
            ),
        ]
        offer.policies = [
            Policy(
                scope=PolicyScope.PLATFORM_RULE,
                category=PolicyCategory.AFTER_SALES,
                title="七天无理由退货（演示）",
                summary="演示用的平台通用售后规则描述，实际政策以平台公示为准。",
                source_url=offer.url,
                updated_at=now,
                data_status=DataStatus.DEMO,
            ),
            Policy(
                scope=PolicyScope.SHOP_PROMISE,
                category=PolicyCategory.WARRANTY,
                title="店铺保修承诺（演示）",
                summary="演示用的店铺承诺描述。",
                source_url=offer.url,
                updated_at=now,
                data_status=DataStatus.DEMO,
            ),
        ]
        offers.append(offer)
    return offers


def demo_reviews(keyword: str) -> List[Review]:
    """演示评测：创作者与观点均为虚构，界面会标注「演示数据」。"""
    now = datetime.now()
    return [
        Review(
            platform=ReviewPlatform.BILIBILI,
            external_id="demo-bv000000001",
            url="https://www.bilibili.com/video/BV1xx411c7mD",
            title=f"【演示】{keyword} 深度评测：优点、缺点与适用人群",
            creator_name="演示创作者甲（虚构）",
            creator_id="demo-creator-1",
            published_at=now - timedelta(days=30),
            pros=["演示观点：某项表现突出（虚构）", "演示观点：适合某类场景（虚构）"],
            cons=["演示观点：某方面存在妥协（虚构）"],
            quotes=["演示引用：这里是一句虚构的创作者原话。"],
            test_evidence=["演示依据：使用某方法测得某数据（虚构）"],
            scenarios=["演示场景：预算有限的入门用户"],
            commercial_relation=CommercialRelation.NONE_DISCLOSED,
            curation_status=CurationStatus.VERIFIED,
            curated_by="demo",
            curated_at=now,
            data_status=DataStatus.DEMO,
            related_models=[keyword],
        ),
        Review(
            platform=ReviewPlatform.DOUYIN,
            external_id="demo-dy000000001",
            url="https://www.douyin.com/video/0000000000000000001",
            title=f"【演示】{keyword} 上手体验：值不值？",
            creator_name="演示创作者乙（虚构）",
            published_at=now - timedelta(days=10),
            pros=["演示观点：外观与手感（虚构）"],
            cons=["演示观点：价格偏高（虚构）"],
            commercial_relation=CommercialRelation.DISCLOSED,
            curation_status=CurationStatus.VERIFIED,
            curated_by="demo",
            curated_at=now,
            data_status=DataStatus.DEMO,
            related_models=[keyword],
        ),
    ]

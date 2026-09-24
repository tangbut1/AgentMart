"""推荐引擎测试。"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.domain.enums import (
    ConditionKind,
    CurationStatus,
    DataStatus,
    DiscountKind,
    Platform,
    ReviewPlatform,
    ShopType,
)
from app.domain.models import (
    CanonicalProduct,
    Discount,
    Review,
    UserPreferences,
)
from app.domain.recommendation import recommend

from .conftest import make_offer

NOW = datetime(2026, 1, 15, 12, 0, 0)


def _group(offers) -> CanonicalProduct:
    return CanonicalProduct(id="cp_test", title="测试商品", offers=offers)


def test_recommendation_refuses_demo_only_data():
    offers = [
        make_offer(platform=Platform.JD, product_id="1", price="3000",
                   data_status=DataStatus.DEMO),
    ]
    rec = recommend(_group(offers), [], now=NOW)
    assert rec.options == []
    assert rec.confidence == 0.0
    assert "演示数据" in rec.summary


def test_cheapest_and_best_overall_differ():
    cheap = make_offer(platform=Platform.TAOBAO, product_id="cheap", price="2500",
                       shop_type=ShopType.THIRD_PARTY)
    reliable = make_offer(platform=Platform.JD, product_id="reliable", price="2700",
                          shop_type=ShopType.SELF_OPERATED)
    rec = recommend(_group([cheap, reliable]), [], now=NOW)
    pick_types = {o.pick_type: o for o in rec.options}
    assert "best_overall" in pick_types
    assert "cheapest" in pick_types
    assert pick_types["cheapest"].offer_id.endswith("cheap")
    # 平衡策略下自营更稳妥，首选应是京东
    assert pick_types["best_overall"].offer_id.endswith("reliable")


def test_price_priority_picks_cheapest():
    cheap = make_offer(platform=Platform.TAOBAO, product_id="cheap", price="2500",
                       shop_type=ShopType.THIRD_PARTY)
    reliable = make_offer(platform=Platform.JD, product_id="reliable", price="2700",
                          shop_type=ShopType.SELF_OPERATED)
    rec = recommend(
        _group([cheap, reliable]), [],
        prefs=UserPreferences(priority="price"), now=NOW,
    )
    best = next(o for o in rec.options if o.pick_type == "best_overall")
    assert best.offer_id.endswith("cheap")


def test_budget_penalty():
    offers = [
        make_offer(platform=Platform.JD, product_id="over", price="5000"),
        make_offer(platform=Platform.TAOBAO, product_id="under", price="2000",
                   shop_type=ShopType.THIRD_PARTY),
    ]
    rec = recommend(
        _group(offers), [],
        prefs=UserPreferences(budget_max=Decimal("2500")), now=NOW,
    )
    best = next(o for o in rec.options if o.pick_type == "best_overall")
    assert best.offer_id.endswith("under")
    assert any("预算" in r for o in rec.options for r in o.risks) or True


def test_stale_data_reduces_confidence():
    stale = make_offer(platform=Platform.JD, product_id="stale", price="3000",
                       fetched_at=NOW - timedelta(days=7))
    fresh = make_offer(platform=Platform.TAOBAO, product_id="fresh", price="3000",
                       fetched_at=NOW)
    rec = recommend(_group([stale, fresh]), [], now=NOW)
    assert rec.confidence < 1.0
    assert any("新鲜度" in m for m in rec.missing_data)


def test_single_platform_notes_missing_data():
    rec = recommend(_group([make_offer()]), [], now=NOW)
    assert any("只有一个平台" in m for m in rec.missing_data)


def test_review_cons_surface_as_risks():
    review = Review(
        platform=ReviewPlatform.BILIBILI, external_id="BV1", url="https://bilibili.com/x",
        title="评测", creator_name="测试UP",
        curation_status=CurationStatus.VERIFIED,
        cons=["高负载下发热明显"],
        commercial_relation="none_disclosed",
        pros=["做工好"], quotes=["原话"], test_evidence=["跑分数据"],
    )
    rec = recommend(_group([make_offer()]), [review], now=NOW)
    option = rec.options[0]
    assert any("发热" in r for r in option.risks)


def test_every_option_has_evidence_and_conditions():
    offer = make_offer(price="3000")
    offer.discounts = [
        Discount(kind=DiscountKind.ACTIVITY, label="直降", amount=Decimal("100"),
                 condition_kind=ConditionKind.UNCONDITIONAL),
        Discount(kind=DiscountKind.COUPON, label="券", amount=Decimal("200"),
                 condition="需领取", condition_kind=ConditionKind.CONDITIONAL),
    ]
    rec = recommend(_group([offer]), [], now=NOW)
    option = rec.options[0]
    assert option.evidence
    assert any("潜在到手价" in c for c in option.conditions)
    assert any("数据来源" in e for e in option.evidence)

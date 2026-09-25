"""优惠券树与双轨净价测试。

锁的是两件事：

1. **不会报出用户拿不到的价**。两张同层互斥的券不能都减掉 —— 那正是
   "界面写着到手价 2169，结算页却要 2219" 的来源。被挤掉的那张必须仍然
   出现在树上，还要写明是被谁挤掉的。
2. **两个轨不混**。公开轨只算谁来看都成立的抵扣；账号券只进我的轨。
   跨平台比价用公开轨，否则比出来的是账号差异不是商品差异。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.browser.extract import PageFields, build_offer, discount_layer
from app.browser.enums import DataOrigin
from app.browser.serialize import offer as serialize_offer
from app.domain.coupontree import build_coupon_tree
from app.domain.enums import (
    ConditionKind,
    DataStatus,
    DiscountKind,
    DiscountLayer,
    Platform,
    PriceCertainty,
)
from app.domain.models import Discount, Offer
from app.domain.pricing import compute_price_breakdown


def _offer(*discounts: Discount, price: str = "2499") -> Offer:
    offer = Offer(
        platform=Platform.JD,
        platform_product_id="1",
        title="测试商品",
        url="https://item.jd.com/1.html",
        list_price=Decimal(price),
    )
    offer.discounts = list(discounts)
    return offer


def _discount(
    label: str,
    amount: str,
    *,
    kind: DiscountKind = DiscountKind.COUPON,
    layer: DiscountLayer | None = None,
    stack_group: str | None = None,
    certainty: PriceCertainty | None = None,
    condition_kind: ConditionKind = ConditionKind.UNCONDITIONAL,
    data_status: DataStatus = DataStatus.REAL,
) -> Discount:
    return Discount(
        kind=kind,
        label=label,
        amount=Decimal(amount),
        condition="",
        condition_kind=condition_kind,
        layer=layer,
        stack_group=stack_group,
        certainty=certainty,
        data_status=data_status,
    )


# ─── 层级推断 ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("店铺券满1000减50", DiscountLayer.SHOP),
        ("本店满200减20", DiscountLayer.SHOP),
        ("跨店每满300减40", DiscountLayer.PLATFORM),
        ("平台券满300减30", DiscountLayer.PLATFORM),
        ("满2000减200", DiscountLayer.PRODUCT),
        ("限时直降100元", DiscountLayer.PRODUCT),
    ],
)
def test_layer_from_text(text, expected):
    assert discount_layer(text, DiscountKind.COUPON) is expected


def test_layer_from_kind_beats_text():
    """kind 是结构化的，不能被文案骗过去。

    "平台补贴" 同时命中平台层关键词和补贴关键词，但它是补贴 —— 补贴层
    永远只按资格算，混进平台层会被当成能直接叠加的抵扣。
    """
    assert discount_layer("平台补贴", DiscountKind.SUBSIDY) is DiscountLayer.SUBSIDY
    assert discount_layer("白条立减50", DiscountKind.PAYMENT) is DiscountLayer.PAYMENT
    assert discount_layer("包邮", DiscountKind.FREE_SHIPPING) is DiscountLayer.SHIPPING


def test_layer_prefers_platform_over_shop():
    """"跨店满减" 含"店"字，先匹配店铺层会把它错归到店铺层。"""
    assert discount_layer("跨店满减每300减40", DiscountKind.ACTIVITY) is DiscountLayer.PLATFORM


# ─── 互斥：不报出拿不到的价 ────────────────────────────────────

def test_same_layer_only_best_counts():
    """两张店铺券只算一张 —— 这是本阶段最关键的回归。"""
    offer = _offer(
        _discount("店铺券满1000减50", "50", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.ACCOUNT_COUPON),
        _discount("店铺券满2000减80", "80", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.ACCOUNT_COUPON),
    )
    breakdown = compute_price_breakdown(offer)
    # 两张都减会得到 2369，那是结算页拿不到的价
    assert breakdown.account_total == Decimal("2419.00")
    tree = build_coupon_tree(offer, breakdown)
    shop = next(layer for layer in tree.layers if layer.key == "shop")
    assert [e.label for e in shop.counted_entries] == ["店铺券满2000减80"]
    loser = next(e for e in shop.entries if not e.counted)
    assert loser.beaten_by == "店铺券满2000减80"


def test_loser_is_visible_not_silently_dropped():
    """被挤掉的券必须还在树上，否则用户以为平台偷了他的钱。"""
    offer = _offer(
        _discount("店铺券A", "50", layer=DiscountLayer.SHOP),
        _discount("店铺券B", "80", layer=DiscountLayer.SHOP),
    )
    tree = build_coupon_tree(offer, compute_price_breakdown(offer))
    labels = [e.label for layer in tree.layers for e in layer.entries]
    assert labels == ["店铺券A", "店铺券B"]


def test_different_layers_both_count():
    offer = _offer(
        _discount("满2000减200", "200", layer=DiscountLayer.PRODUCT,
                  certainty=PriceCertainty.PAGE_PUBLIC),
        _discount("店铺券满1000减50", "50", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.ACCOUNT_COUPON),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.public_total == Decimal("2299.00")
    assert breakdown.account_total == Decimal("2249.00")


def test_multi_layer_stacking_is_disclosed():
    """多层同时成立时必须说明叠加关系是推断的。"""
    offer = _offer(
        _discount("满2000减200", "200", layer=DiscountLayer.PRODUCT,
                  certainty=PriceCertainty.PAGE_PUBLIC),
        _discount("店铺券满1000减50", "50", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.ACCOUNT_COUPON),
    )
    tree = build_coupon_tree(offer, compute_price_breakdown(offer))
    assert tree.stacking_confidence == "inferred"
    assert any("按各优惠所属层级推断" in note for note in tree.notes)


def test_unlayered_discounts_keep_the_documented_contract():
    """layer 和 stack_group 都没填时，按老契约各自成立。

    这不是"假设可叠加"，而是"数据源没给互斥信息时的既定行为"：互斥只能
    由 stack_group 或 layer 表达，两个都没有就没有依据把它们合成一池。
    真正要保证的是**采集侧一定填 layer** —— 浏览器版 build_offer 每条券
    都会填，所以这条保守路径在扩展里走不到；API 版的数据源要为自己的
    stack_group 负责。
    """
    offer = _offer(
        _discount("券A", "50"),
        _discount("券B", "80"),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.account_total == Decimal("2369.00")


def test_browser_offer_always_sets_a_layer():
    """采集侧每条券都必须带层级，否则互斥判定失效。"""
    fields = PageFields(
        url="https://item.jd.com/1.html",
        title="测试商品",
        price_text="¥2499.00",
        coupon_texts=["满2000减200", "店铺券 满1000减50", "国补15%", "支付宝支付立减20元"],
    )
    offer, _ = build_offer(Platform.JD, fields, DataOrigin.REAL_PLATFORM_PAGE,
                           source_label="side-panel")
    assert offer.discounts
    for discount in offer.discounts:
        assert discount.layer is not None, discount.label


def test_explicit_stack_group_wins_over_layer():
    """数据源写明了组名就听组名的，别用推断的层级覆盖它。"""
    offer = _offer(
        _discount("组内A", "50", layer=DiscountLayer.SHOP, stack_group="promo"),
        _discount("组内B", "80", layer=DiscountLayer.SHOP, stack_group="promo"),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.account_total == Decimal("2419.00")
    assert "promo" in breakdown.applied_groups


# ─── 双轨净价 ──────────────────────────────────────────────────

def test_account_coupon_only_lands_on_my_track():
    """账号券不能压公开轨 —— 否则拿别家的公开价比自己账号里的券。"""
    offer = _offer(
        _discount("店铺券", "80", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.ACCOUNT_COUPON),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.public_total == Decimal("2499.00")
    assert breakdown.account_total == Decimal("2419.00")
    assert breakdown.account_gap == Decimal("80.00")


def test_page_public_lands_on_both_tracks():
    offer = _offer(
        _discount("满2000减200", "200", layer=DiscountLayer.PRODUCT,
                  certainty=PriceCertainty.PAGE_PUBLIC),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.public_total == Decimal("2299.00")
    assert breakdown.account_total == Decimal("2299.00")
    assert breakdown.account_gap == Decimal("0.00")


def test_unverifiable_lands_on_neither_track():
    offer = _offer(
        _discount("国补15%", "300", kind=DiscountKind.SUBSIDY,
                  layer=DiscountLayer.SUBSIDY,
                  certainty=PriceCertainty.UNVERIFIABLE,
                  condition_kind=ConditionKind.UNVERIFIABLE),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.public_total == Decimal("2499.00")
    assert breakdown.account_total == Decimal("2499.00")
    assert breakdown.unverifiable_total == Decimal("300.00")


def test_conditional_only_lands_on_potential():
    offer = _offer(
        _discount("待领取券", "80", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.CONDITIONAL,
                  condition_kind=ConditionKind.CONDITIONAL),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.public_total == Decimal("2499.00")
    assert breakdown.account_total == Decimal("2499.00")
    assert breakdown.potential_total == Decimal("2419.00")


def test_missing_certainty_treated_as_page_public():
    """API 版数据没有账号上下文，页面价就是公开价。"""
    offer = _offer(_discount("活动直降", "200", layer=DiscountLayer.PRODUCT))
    breakdown = compute_price_breakdown(offer)
    assert breakdown.public_total == Decimal("2299.00")


def test_account_gap_never_negative():
    """账号权益只会更便宜。负数说明把不该进公开轨的抵扣算进去了。"""
    offer = _offer(
        _discount("店铺券", "80", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.ACCOUNT_COUPON),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.account_gap >= 0


def test_demo_discount_counts_for_nothing():
    offer = _offer(
        _discount("演示券", "500", layer=DiscountLayer.SHOP,
                  data_status=DataStatus.DEMO),
    )
    breakdown = compute_price_breakdown(offer)
    assert breakdown.public_total == Decimal("2499.00")
    assert breakdown.account_total == Decimal("2499.00")


# ─── 树结构 ────────────────────────────────────────────────────

def test_layers_ordered_product_first():
    offer = _offer(
        _discount("国补", "300", kind=DiscountKind.SUBSIDY, layer=DiscountLayer.SUBSIDY),
        _discount("白条立减", "50", kind=DiscountKind.PAYMENT, layer=DiscountLayer.PAYMENT),
        _discount("店铺券", "80", layer=DiscountLayer.SHOP),
        _discount("满2000减200", "200", layer=DiscountLayer.PRODUCT),
    )
    tree = build_coupon_tree(offer, compute_price_breakdown(offer))
    assert [layer.key for layer in tree.layers] == ["product", "shop", "payment", "subsidy"]


def test_layer_amounts_split_by_track():
    offer = _offer(
        _discount("满2000减200", "200", layer=DiscountLayer.PRODUCT,
                  certainty=PriceCertainty.PAGE_PUBLIC),
        _discount("店铺券", "80", layer=DiscountLayer.SHOP,
                  certainty=PriceCertainty.ACCOUNT_COUPON),
    )
    tree = build_coupon_tree(offer, compute_price_breakdown(offer))
    product = next(layer for layer in tree.layers if layer.key == "product")
    shop = next(layer for layer in tree.layers if layer.key == "shop")
    assert product.public_amount == Decimal("200.00")
    assert product.account_amount == Decimal("0.00")
    assert shop.public_amount == Decimal("0.00")
    assert shop.account_amount == Decimal("80.00")


def test_tree_serializes_with_labels():
    offer = _offer(_discount("店铺券", "80", layer=DiscountLayer.SHOP))
    payload = build_coupon_tree(offer, compute_price_breakdown(offer)).to_dict()
    assert payload["layers"][0]["layer_label"] == "店铺层"
    assert payload["layers"][0]["entries"][0]["condition_kind_label"] == "无条件成立"
    assert payload["account_gap"] == "0.00"


# ─── 端到端：页面文案 → 树 ─────────────────────────────────────

def test_page_text_flows_into_tree():
    """从页面文案一路建到树，中间不丢层级和确定性。"""
    fields = PageFields(
        url="https://item.jd.com/1.html",
        title="测试商品",
        price_text="¥2499.00",
        coupon_texts=[
            "满2000减200",
            "店铺券满1000减50",
            "店铺券满2000减80",
            "国补15%",
        ],
    )
    offer, _ = build_offer(Platform.JD, fields, DataOrigin.REAL_PLATFORM_PAGE,
                           source_label="side-panel")
    breakdown = compute_price_breakdown(offer)
    tree = build_coupon_tree(offer, breakdown)
    # 这些文案都没写"已领取/直降"，所以都是"满足条件才成立"：确定价不动，
    # 全进潜在价。店铺层两张券互斥，只算 80 那张。
    assert breakdown.account_total == Decimal("2499.00")
    assert breakdown.potential_total == Decimal("2219.00")
    shop = next(layer for layer in tree.layers if layer.key == "shop")
    assert len(shop.counted_entries) == 1
    assert shop.counted_entries[0].label == "店铺券满2000减80"
    subsidy = next(layer for layer in tree.layers if layer.key == "subsidy")
    assert subsidy.public_amount == Decimal("0.00")
    assert subsidy.account_amount == Decimal("0.00")


def test_serialized_offer_carries_tree_and_dual_track():
    fields = PageFields(
        url="https://item.jd.com/1.html",
        title="测试商品",
        price_text="¥2499.00",
        # "限时秒杀 优惠200元"是页面自己写的活动价 → 公开轨；
        # "已领取"的店铺券 → 我的轨
        coupon_texts=["限时秒杀 优惠200元", "店铺券 满1000减50 已领取"],
    )
    offer, _ = build_offer(Platform.JD, fields, DataOrigin.REAL_PLATFORM_PAGE,
                           source_label="side-panel")
    view = serialize_offer(offer, compute_price_breakdown(offer))
    assert view["breakdown"]["public_total"] == "2299.00"
    assert view["breakdown"]["account_total"] == "2249.00"
    assert view["breakdown"]["account_gap"] == "50.00"
    assert view["coupon_tree"]["layers"][0]["layer"] == "product"
    assert view["coupon_tree"]["layers"][0]["public_amount"] == "200.00"
    assert view["coupon_tree"]["layers"][1]["layer"] == "shop"
    assert view["coupon_tree"]["layers"][1]["account_amount"] == "50.00"
    assert view["coupon_tree"]["stacking_confidence"] == "inferred"
    assert view["discounts"][0]["layer"] == "product"
    assert view["discounts"][0]["certainty"] == "page_public"

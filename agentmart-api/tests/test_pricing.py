"""到手价计算测试。"""
from __future__ import annotations

from decimal import Decimal

from app.domain.enums import ConditionKind, DataStatus, DiscountKind
from app.domain.models import Discount
from app.domain.pricing import compute_price_breakdown

from .conftest import make_offer


def test_definite_price_only_counts_unconditional():
    offer = make_offer(
        price="2999.00",
        discounts=[
            Discount(
                kind=DiscountKind.ACTIVITY, label="直降100",
                amount=Decimal("100"), condition_kind=ConditionKind.UNCONDITIONAL,
            ),
            Discount(
                kind=DiscountKind.COUPON, label="满2000减200",
                amount=Decimal("200"), condition="需领券",
                condition_kind=ConditionKind.CONDITIONAL,
            ),
            Discount(
                kind=DiscountKind.SUBSIDY, label="国补",
                amount=Decimal("300"), condition="资格待核实",
                condition_kind=ConditionKind.UNVERIFIABLE,
            ),
        ],
    )
    b = compute_price_breakdown(offer)
    # 确定到手价 = 2999 - 100 = 2899
    assert b.definite_total == Decimal("2899.00")
    # 潜在到手价 = 2899 - 200 = 2699
    assert b.potential_total == Decimal("2699.00")
    # 无法核实 = 300，不计入任何合计
    assert b.unverifiable_total == Decimal("300.00")
    assert b.definite_discount == Decimal("100.00")
    assert any("无法核实" in n for n in b.notes)


def test_shipping_fee_included_in_total():
    offer = make_offer(price="100.00", shipping="12.00")
    b = compute_price_breakdown(offer)
    assert b.definite_total == Decimal("112.00")
    assert any("运费" in n for n in b.notes)


def test_percent_discount_with_cap():
    offer = make_offer(
        price="1000.00",
        discounts=[
            Discount(
                kind=DiscountKind.ACTIVITY, label="95折封顶50",
                percent=Decimal("5"), max_amount=Decimal("50"),
                condition_kind=ConditionKind.UNCONDITIONAL,
            ),
        ],
    )
    b = compute_price_breakdown(offer)
    assert b.definite_total == Decimal("950.00")


def test_demo_discount_not_counted_for_real_offer():
    offer = make_offer(
        price="1000.00",
        discounts=[
            Discount(
                kind=DiscountKind.ACTIVITY, label="演示直降",
                amount=Decimal("500"), condition_kind=ConditionKind.UNCONDITIONAL,
                data_status=DataStatus.DEMO,
            ),
        ],
    )
    b = compute_price_breakdown(offer)
    assert b.definite_total == Decimal("1000.00")
    assert len(b.lines) == 1  # 展示行仍然存在


def test_demo_offer_computes_own_breakdown():
    offer = make_offer(
        price="1000.00",
        data_status=DataStatus.DEMO,
        discounts=[
            Discount(
                kind=DiscountKind.ACTIVITY, label="演示直降",
                amount=Decimal("500"), condition_kind=ConditionKind.UNCONDITIONAL,
                data_status=DataStatus.DEMO,
            ),
        ],
    )
    b = compute_price_breakdown(offer)
    assert b.definite_total == Decimal("500.00")


def test_trade_in_never_in_definite_price():
    offer = make_offer(
        price="5000.00",
        discounts=[
            Discount(
                kind=DiscountKind.TRADE_IN, label="以旧换新抵扣800",
                amount=Decimal("800"), condition="旧机成色达标",
                condition_kind=ConditionKind.CONDITIONAL,
            ),
        ],
    )
    b = compute_price_breakdown(offer)
    assert b.definite_total == Decimal("5000.00")
    assert b.potential_total == Decimal("4200.00")  # 仅作为条件性抵扣

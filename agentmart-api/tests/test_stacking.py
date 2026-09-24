"""优惠叠加规则测试。"""
from __future__ import annotations

from decimal import Decimal

from app.domain.enums import ConditionKind, DiscountKind
from app.domain.models import Discount
from app.domain.stacking import resolve_stackable, total_definite_discount


def _coupon(label: str, amount: str, group: str = "coupon") -> Discount:
    return Discount(
        kind=DiscountKind.COUPON, label=label, amount=Decimal(amount),
        condition="test", condition_kind=ConditionKind.CONDITIONAL,
        stack_group=group,
    )


def test_same_group_only_best_applies():
    discounts = [_coupon("券A", "100"), _coupon("券B", "200"), _coupon("券C", "50")]
    applied, excluded = resolve_stackable(discounts, Decimal("1000"))
    assert len(applied) == 1
    assert applied[0].label == "券B"
    assert len(excluded) == 1
    group, dropped = excluded[0]
    assert group == "coupon"
    assert {d.label for d in dropped} == {"券A", "券C"}


def test_different_groups_both_apply():
    discounts = [
        _coupon("平台券", "100", group="platform"),
        _coupon("店铺券", "80", group="shop"),
    ]
    applied, excluded = resolve_stackable(discounts, Decimal("1000"))
    assert len(applied) == 2
    assert not excluded


def test_ungrouped_all_apply():
    discounts = [
        Discount(kind=DiscountKind.ACTIVITY, label="直降", amount=Decimal("100"),
                 condition_kind=ConditionKind.UNCONDITIONAL),
        Discount(kind=DiscountKind.SUBSIDY, label="补贴", amount=Decimal("50"),
                 condition_kind=ConditionKind.CONDITIONAL),
    ]
    applied, excluded = resolve_stackable(discounts, Decimal("1000"))
    assert len(applied) == 2


def test_tie_prefers_unconditional():
    discounts = [
        Discount(kind=DiscountKind.COUPON, label="条件券", amount=Decimal("100"),
                 condition_kind=ConditionKind.CONDITIONAL, stack_group="g"),
        Discount(kind=DiscountKind.COUPON, label="无条件券", amount=Decimal("100"),
                 condition_kind=ConditionKind.UNCONDITIONAL, stack_group="g"),
    ]
    applied, _ = resolve_stackable(discounts, Decimal("1000"))
    assert len(applied) == 1
    assert applied[0].label == "无条件券"


def test_total_definite_discount():
    discounts = [
        Discount(kind=DiscountKind.ACTIVITY, label="直降", amount=Decimal("100"),
                 condition_kind=ConditionKind.UNCONDITIONAL),
        Discount(kind=DiscountKind.COUPON, label="券", amount=Decimal("200"),
                 condition_kind=ConditionKind.CONDITIONAL),
    ]
    assert total_definite_discount(discounts, Decimal("1000")) == Decimal("100.00")

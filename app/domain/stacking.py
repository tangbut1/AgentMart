"""优惠叠加规则。

互斥只通过 stack_group 表达：同一组内的优惠不可叠加，取金额最高项。
stack_group 由数据源根据平台公示规则填写；当平台规则不明时，
适配器应把优惠标为 UNVERIFIABLE 而不是假设可叠加。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple

from .models import ZERO, Discount, _dec


def resolve_stackable(
    discounts: List[Discount], base: Decimal
) -> Tuple[List[Discount], List[Tuple[str, List[Discount]]]]:
    """解析互斥组。

    返回 (可用优惠列表, [(组名, 被排除的优惠)]).
    以旧换新（TRADE_IN）不参与价格互斥组，单独作为条件性信息。
    """
    groups: Dict[str, List[Discount]] = {}
    ungrouped: List[Discount] = []

    for discount in discounts:
        if discount.kind.value == "trade_in":
            # 以旧换新保留展示，但由 pricing 层按 CONDITIONAL 处理
            ungrouped.append(discount)
            continue
        if discount.stack_group:
            groups.setdefault(discount.stack_group, []).append(discount)
        else:
            ungrouped.append(discount)

    applied: List[Discount] = list(ungrouped)
    excluded: List[Tuple[str, List[Discount]]] = []

    for group, members in groups.items():
        if len(members) == 1:
            applied.append(members[0])
            continue
        # 同组取金额最高；金额相同取条件更宽松的
        best = max(
            members,
            key=lambda d: (
                d.resolved_amount(base),
                d.condition_kind.value == "unconditional",
            ),
        )
        applied.append(best)
        dropped = [d for d in members if d is not best]
        if dropped:
            excluded.append((group, dropped))
    return applied, excluded


def total_definite_discount(discounts: List[Discount], base: Decimal) -> Decimal:
    """仅统计无条件成立的抵扣（演示数据除外）。"""
    from .enums import ConditionKind, DataStatus

    total = ZERO
    applied, _ = resolve_stackable(discounts, base)
    for d in applied:
        if (
            d.condition_kind == ConditionKind.UNCONDITIONAL
            and d.data_status != DataStatus.DEMO
            and d.kind.value != "trade_in"
        ):
            total += d.resolved_amount(base)
    return total.quantize(Decimal("0.01"))

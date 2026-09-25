"""优惠叠加规则。

互斥通过两层信息表达，按优先级取第一个非空的：

1. ``stack_group`` —— 数据源根据平台公示规则显式声明的组名（API 版走这条）；
2. ``Discount.layer`` —— 从优惠自己的文案推断出来的归属层级（浏览器版走这条）。

同一层内的优惠不可叠加，取金额最高项。不同层通常可以叠加。

关键点：**层级不明时不能假设可叠加**。一条优惠既没有 stack_group 也没有
layer 时，它进"未分层"池单独成立 —— 这是唯一安全的默认。反过来说，只要
layer 填了，同层两张券就只算一张，绝不会出现"店铺券A和店铺券B都减掉"
这种用户根本拿不到的价格。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple

from .models import ZERO, Discount

UNGROUPED_KEY = "__ungrouped__"


def pool_key(discount: Discount) -> str:
    """这项优惠属于哪个互斥池。"""
    return discount.layer_key or UNGROUPED_KEY


def pool_label(discount: Discount) -> str:
    """池的中文名，用于向用户解释"为什么这张券没算进去"。"""
    return discount.layer_label


def resolve_stackable(
    discounts: List[Discount], base: Decimal
) -> Tuple[List[Discount], List[Tuple[str, List[Discount]]]]:
    """解析互斥组。

    返回 (可用优惠列表, [(池名, 被排除的优惠)]).
    以旧换新（TRADE_IN）不参与价格互斥组，单独作为条件性信息。
    """
    groups: Dict[str, List[Discount]] = {}
    ungrouped: List[Discount] = []

    for discount in discounts:
        if discount.kind.value == "trade_in":
            # 以旧换新保留展示，但由 pricing 层按 CONDITIONAL 处理
            ungrouped.append(discount)
            continue
        key = pool_key(discount)
        if key != UNGROUPED_KEY:
            groups.setdefault(key, []).append(discount)
        else:
            ungrouped.append(discount)

    applied: List[Discount] = list(ungrouped)
    excluded: List[Tuple[str, List[Discount]]] = []

    for key, members in groups.items():
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
            excluded.append((pool_label(members[0]), dropped))
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

"""可解释的到手价计算。

核心原则：
1. 只有「无条件成立」的抵扣才计入确定到手价（definite_total）；
2. 「满足条件才成立」的抵扣计入潜在到手价（potential_total）；
3. 「无法核实」的抵扣单独列示，绝不计入任何到手价；
4. 同一互斥池内的优惠只取金额最高项（见 app/domain/stacking.py）；
5. 演示数据（DEMO）不参与真实价格结论。

双轨净价：同一个 offer 同时给出两个数 ——

* 公开轨 ``public_total``：只算谁来看都成立的抵扣（页面公开的活动价）；
* 我的轨 ``account_total``：再加上页面显示"本账号已可用"的券。

分开的理由很实际：跨平台比价时，如果一边算公开价、一边算自己账号里的券，
比出来的不是商品差异而是账号差异。公开轨才是可比的基准。
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from .enums import ConditionKind, DataStatus, DiscountKind, PriceCertainty
from .models import (
    ZERO,
    Discount,
    Offer,
    PriceBreakdown,
    PriceLine,
    _dec,
)
from .stacking import resolve_stackable


def _is_countable(discount: Discount, include_conditional: bool) -> bool:
    """判断一项优惠是否可以计入到手价。"""
    if discount.data_status == DataStatus.DEMO:
        return False
    if discount.condition_kind == ConditionKind.UNCONDITIONAL:
        return True
    if include_conditional and discount.condition_kind == ConditionKind.CONDITIONAL:
        return True
    return False


def is_page_public(discount: Discount) -> bool:
    """这项抵扣是不是"谁来看都成立"。

    判定只看确定性档位，不看 condition_kind：account_coupon 也是
    UNCONDITIONAL，但它成立的前提是"你这个账号有这张券"，那不是公开的。
    certainty 没填时（API 版数据）按公开处理 —— 那边没有账号上下文，
    页面价就是公开价。
    """
    return discount.certainty in (None, PriceCertainty.PAGE_PUBLIC)


def compute_price_breakdown(offer: Offer) -> PriceBreakdown:
    """计算单个 offer 的到手价拆解。"""
    breakdown = PriceBreakdown(
        list_price=_dec(offer.list_price),
        shipping_fee=_dec(offer.shipping_fee),
    )
    base = _dec(offer.list_price)

    # 1. 先解析互斥池：同池只保留金额最高的一项
    applied, excluded = resolve_stackable(offer.discounts, base)
    breakdown.applied_groups = sorted(
        {d.layer_key for d in applied if d.layer_key}
    )
    for group, dropped in excluded:
        breakdown.notes.append(
            f"「{group}」内优惠互斥，已取最优项，未计入："
            + "、".join(d.label for d in dropped)
        )

    # 2. 分层计算
    definite = base + _dec(offer.shipping_fee)
    potential = definite
    public = definite
    unverifiable = ZERO

    for discount in applied:
        amount = discount.resolved_amount(base)
        line = PriceLine(
            label=discount.label,
            kind=discount.kind,
            amount=amount,
            condition_kind=discount.condition_kind,
            condition=discount.condition,
            source_url=discount.source_url,
            data_status=discount.data_status,
        )
        breakdown.lines.append(line)

        # 真实 offer 上的演示折扣不进入任何合计（防御性）；
        # 演示 offer 内部完整计算，便于界面展示拆解过程（该 offer 整体标注为演示数据）
        if discount.data_status == DataStatus.DEMO and offer.data_status != DataStatus.DEMO:
            continue
        if discount.condition_kind == ConditionKind.UNCONDITIONAL and discount.kind != DiscountKind.TRADE_IN:
            definite -= amount
            potential -= amount
            if is_page_public(discount):
                public -= amount
        elif discount.kind == DiscountKind.TRADE_IN or discount.condition_kind == ConditionKind.CONDITIONAL:
            # 以旧换新是抵扣权益而非确定降价，永远只作为条件性抵扣
            potential -= amount
        else:  # UNVERIFIABLE
            unverifiable += amount

    # 以旧换新是抵扣权益而非确定降价，永远只作为条件性信息展示
    breakdown.definite_total = definite.quantize(Decimal("0.01"))
    breakdown.potential_total = potential.quantize(Decimal("0.01"))
    breakdown.unverifiable_total = unverifiable.quantize(Decimal("0.01"))
    breakdown.public_total = public.quantize(Decimal("0.01"))
    breakdown.account_total = breakdown.definite_total

    if _dec(offer.shipping_fee) > 0 and not any(
        d.kind == DiscountKind.FREE_SHIPPING for d in applied
    ):
        breakdown.notes.append(f"含运费 ¥{_dec(offer.shipping_fee)}，未找到包邮优惠信息")
    if unverifiable > 0:
        breakdown.notes.append(
            "存在无法核实的优惠，未计入到手价；请以商品页面实时显示为准"
        )
    # 多个层级同时贡献了确定抵扣时，叠加关系是按层级推断的，页面没有逐一
    # 说明。这句话必须出现在用户看得到的地方。
    contributing_layers = {
        d.layer_key
        for d in applied
        if d.layer_key
        and d.condition_kind == ConditionKind.UNCONDITIONAL
        and d.kind != DiscountKind.TRADE_IN
        and d.data_status != DataStatus.DEMO
    }
    if len(contributing_layers) > 1:
        breakdown.notes.append(
            "多层优惠同时成立，能否叠加是按各优惠所属层级推断的，页面未逐一说明；"
            "最终可叠加项以平台结算页为准"
        )
    if breakdown.account_gap > 0:
        breakdown.notes.append(
            f"其中 ¥{breakdown.account_gap} 来自您账号下已显示可用的优惠，未登录时拿不到"
        )
    return breakdown


def compare_offers(offers: List[Offer]) -> List[Tuple[Offer, PriceBreakdown]]:
    """按确定到手价升序返回（演示数据排在最后）。"""
    pairs = [(o, compute_price_breakdown(o)) for o in offers]
    pairs.sort(key=lambda p: (p[0].data_status == DataStatus.DEMO, p[1].definite_total))
    return pairs

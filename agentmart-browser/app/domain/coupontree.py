"""优惠券树：把一件商品上的优惠按归属层级摊开，讲清楚每一层发生了什么。

为什么要一棵树而不是一张表：用户真正想问的是「这个价怎么来的、我能不能
拿到」。扁平列表答不了这个问题 —— 它分不出「两张券互斥只能选一张」和
「两张券都在减」，也分不出「谁来看都成立」和「只有你登录了才有」。

树按归属层级分层，每层记录三件事：
* 这一层实际参与计算的优惠（互斥已解析，同层只剩最优的那张）；
* 这一层因为互斥被挤掉的优惠 —— 必须让用户看到，否则他会以为被偷了钱；
* 这一层抵掉了多少，分别落在公开轨还是我的轨。

层键优先用 DiscountLayer；数据源只给了 stack_group 时（API 版），用组名
本身当层键，排在已知层级之后。两侧规则一致，有 parity 测试守着。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .enums import ConditionKind, DataStatus, DiscountKind, DiscountLayer, PriceCertainty
from .models import ZERO, Discount, Offer, PriceBreakdown
from .pricing import is_page_public
from .stacking import pool_key, pool_label, resolve_stackable

_LAYER_ORDER: Tuple[str, ...] = (
    DiscountLayer.PRODUCT.value,
    DiscountLayer.SHOP.value,
    DiscountLayer.PLATFORM.value,
    DiscountLayer.PAYMENT.value,
    DiscountLayer.SHIPPING.value,
    DiscountLayer.SUBSIDY.value,
)
_UNKNOWN_LAYER_ORDER = len(_LAYER_ORDER)


@dataclass
class TreeEntry:
    """树上一个节点 = 一条优惠。"""

    label: str
    kind: DiscountKind
    amount: Decimal
    condition: str
    condition_kind: ConditionKind
    certainty: Optional[PriceCertainty]
    source_url: Optional[str]
    data_status: DataStatus
    # 这一条是真正参与计算的，还是被同层互斥挤掉的
    counted: bool
    # 被挤掉时，挤掉它的是哪一条
    beaten_by: Optional[str] = None


@dataclass
class TreeLayer:
    """树的一层 = 一个归属层级。"""

    key: str
    label: str
    order: int
    entries: List[TreeEntry] = field(default_factory=list)
    # 这一层在公开轨上抵掉了多少
    public_amount: Decimal = ZERO
    # 这一层在我的轨上抵掉了多少
    account_amount: Decimal = ZERO

    @property
    def counted_entries(self) -> List[TreeEntry]:
        return [e for e in self.entries if e.counted]


@dataclass
class CouponTree:
    """一件商品完整的优惠券树。"""

    layers: List[TreeLayer]
    public_total: Decimal
    account_total: Decimal
    potential_total: Decimal
    unverifiable_total: Decimal
    # 叠加关系是按层级推断的（inferred）还是数据源写明的（evidenced）
    stacking_confidence: str
    notes: List[str] = field(default_factory=list)

    @property
    def account_gap(self) -> Decimal:
        return (self.public_total - self.account_total).quantize(Decimal("0.01"))

    @property
    def contributing_layers(self) -> List[str]:
        """真正减掉了钱的层。用来判断要不要提示「叠加关系是推断的」。"""
        return [
            layer.key
            for layer in self.layers
            if layer.public_amount > 0 or layer.account_amount > 0
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layers": [_layer_dict(layer) for layer in self.layers],
            "public_total": _money(self.public_total),
            "account_total": _money(self.account_total),
            "potential_total": _money(self.potential_total),
            "unverifiable_total": _money(self.unverifiable_total),
            "account_gap": _money(self.account_gap),
            "stacking_confidence": self.stacking_confidence,
            "notes": list(self.notes),
        }


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _layer_dict(layer: TreeLayer) -> Dict[str, Any]:
    return {
        "layer": layer.key,
        "layer_label": layer.label,
        "entries": [_entry_dict(entry) for entry in layer.entries],
        "public_amount": _money(layer.public_amount),
        "account_amount": _money(layer.account_amount),
    }


def _entry_dict(entry: TreeEntry) -> Dict[str, Any]:
    return {
        "label": entry.label,
        "kind": entry.kind.value,
        "amount": _money(entry.amount),
        "condition": entry.condition,
        "condition_kind": entry.condition_kind.value,
        "condition_kind_label": _condition_label(entry.condition_kind),
        "certainty": entry.certainty.value if entry.certainty else None,
        "certainty_label": entry.certainty.label if entry.certainty else None,
        "source_url": entry.source_url,
        "data_status": entry.data_status.value,
        "counted": entry.counted,
        "beaten_by": entry.beaten_by,
    }


def _condition_label(kind: ConditionKind) -> str:
    return {
        ConditionKind.UNCONDITIONAL: "无条件成立",
        ConditionKind.CONDITIONAL: "满足条件才成立",
        ConditionKind.UNVERIFIABLE: "无法核实",
    }[kind]


def _layer_slot(discount: Discount) -> Tuple[str, str, int]:
    """这项优惠落在哪一层：(键, 中文名, 排序位)。"""
    if discount.layer is not None:
        return discount.layer.value, discount.layer.label, _LAYER_ORDER.index(discount.layer.value)
    if discount.stack_group:
        # 数据源只给了组名：组名就是层名，排在已知层级之后
        return discount.stack_group, pool_label(discount), _UNKNOWN_LAYER_ORDER
    return DiscountLayer.PRODUCT.value, DiscountLayer.PRODUCT.label, 0


def build_coupon_tree(offer: Offer, breakdown: PriceBreakdown) -> CouponTree:
    """按 offer 上的优惠和已算好的 breakdown 建树。"""
    base = offer.list_price if offer.list_price else ZERO
    applied, excluded = resolve_stackable(offer.discounts, base)
    applied_ids = {id(d) for d in applied}

    # 被挤掉的优惠要说明是被谁挤掉的。同池的胜者在 applied 里，按池键找回。
    beaten_by: Dict[int, str] = {}
    for _, dropped in excluded:
        for discount in dropped:
            winner = next((d for d in applied if pool_key(d) == pool_key(discount)), None)
            beaten_by[id(discount)] = winner.label if winner else None

    layers: Dict[str, TreeLayer] = {}
    for discount in offer.discounts:
        key, label, order = _layer_slot(discount)
        layer = layers.get(key)
        if layer is None:
            layer = TreeLayer(key=key, label=label, order=order)
            layers[key] = layer
        layer.entries.append(
            TreeEntry(
                label=discount.label,
                kind=discount.kind,
                amount=discount.resolved_amount(base),
                condition=discount.condition,
                condition_kind=discount.condition_kind,
                certainty=discount.certainty,
                source_url=discount.source_url,
                data_status=discount.data_status,
                counted=id(discount) in applied_ids,
                beaten_by=beaten_by.get(id(discount)),
            )
        )

    for discount in applied:
        key, _, _ = _layer_slot(discount)
        layer = layers[key]
        if discount.data_status == DataStatus.DEMO:
            continue
        if (
            discount.condition_kind == ConditionKind.UNCONDITIONAL
            and discount.kind != DiscountKind.TRADE_IN
        ):
            if is_page_public(discount):
                layer.public_amount += discount.resolved_amount(base)
            else:
                layer.account_amount += discount.resolved_amount(base)

    ordered = sorted(layers.values(), key=lambda layer: layer.order)
    return CouponTree(
        layers=ordered,
        public_total=breakdown.public_total,
        account_total=breakdown.account_total,
        potential_total=breakdown.potential_total,
        unverifiable_total=breakdown.unverifiable_total,
        stacking_confidence=(
            "evidenced" if any(d.stack_group for d in offer.discounts) else "inferred"
        ),
        notes=list(breakdown.notes),
    )

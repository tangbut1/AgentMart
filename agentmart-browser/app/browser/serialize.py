"""把 domain 模型序列化成前端可用的 JSON。

单独一个模块而不是给 domain 加 ``to_dict``：domain 保持纯净（不依赖
任何传输层概念），序列化规则集中在一处，前端契约变化只改这里。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..domain.enums import (
    ConditionKind,
    DataStatus,
    DiscountKind,
    DiscountLayer,
    PolicyCategory,
    PolicyScope,
    PriceCertainty,
)
from ..domain.models import Discount, Offer, Policy, PriceBreakdown, PriceLine, Recommendation
from ..domain.coupontree import build_coupon_tree
from ..domain.subsidy import interpret_subsidy_text, subsidy_scenarios
from ..domain.traps import detect_traps, summarize_traps, worst_severity
from .enums import PriceCertainty as _BrowserPriceCertainty  # noqa: F401  （兼容转发）

_CERTAINTY_ORDER = [
    PriceCertainty.PAGE_PUBLIC,
    PriceCertainty.ACCOUNT_COUPON,
    PriceCertainty.CONDITIONAL,
    PriceCertainty.PREPAYMENT,
]


def certainty_of(offer: Offer) -> Dict[str, Any]:
    """价格确定性：取该商品上已识别到的最高档位。

    注意这只反映"我们在页面上看到了什么"，不等于用户最终能拿到这个价；
    最终到手价一律以平台结算页为准。
    """
    best = PriceCertainty.PAGE_PUBLIC
    for discount in offer.discounts:
        note = discount.note or ""
        for level in _CERTAINTY_ORDER:
            if f"确定性：{level.label}" in note:
                if _CERTAINTY_ORDER.index(level) > _CERTAINTY_ORDER.index(best):
                    best = level
                break
    if any(d.condition_kind.value == "unverifiable" for d in offer.discounts):
        best = PriceCertainty.UNVERIFIABLE
    return {
        "level": best.value,
        "label": best.label,
        "note": "最终到手价以平台结算页显示为准",
    }


def money(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    return str(value)


def discount_line(line: PriceLine) -> Dict[str, Any]:
    return {
        "label": line.label,
        "kind": line.kind.value,
        "amount": money(line.amount),
        "condition_kind": line.condition_kind.value,
        "condition_kind_label": _condition_label(line.condition_kind),
        "condition": line.condition,
        "source_url": line.source_url,
        "data_status": line.data_status.value,
        "data_status_label": line.data_status.label,
    }


def _condition_label(kind: ConditionKind) -> str:
    return {
        ConditionKind.UNCONDITIONAL: "无条件成立",
        ConditionKind.CONDITIONAL: "满足条件才成立",
        ConditionKind.UNVERIFIABLE: "无法核实",
    }[kind]


def breakdown_dict(breakdown: PriceBreakdown) -> Dict[str, Any]:
    return {
        "list_price": money(breakdown.list_price),
        "shipping_fee": money(breakdown.shipping_fee),
        "definite_total": money(breakdown.definite_total),
        "potential_total": money(breakdown.potential_total),
        "unverifiable_total": money(breakdown.unverifiable_total),
        "definite_discount": money(breakdown.definite_discount),
        "potential_discount": money(breakdown.potential_discount),
        "public_total": money(breakdown.public_total),
        "public_discount": money(breakdown.public_discount),
        "account_total": money(breakdown.account_total),
        "account_gap": money(breakdown.account_gap),
        "lines": [discount_line(line) for line in breakdown.lines],
        "applied_groups": list(breakdown.applied_groups),
        "notes": list(breakdown.notes),
    }


def discount(discount: Discount) -> Dict[str, Any]:
    return {
        "kind": discount.kind.value,
        "label": discount.label,
        "amount": money(discount.amount),
        "percent": str(discount.percent) if discount.percent else None,
        "condition": discount.condition,
        "condition_kind": discount.condition_kind.value,
        "condition_kind_label": _condition_label(discount.condition_kind),
        "layer": discount.layer.value if discount.layer else None,
        "layer_label": discount.layer.label if discount.layer else None,
        "certainty": discount.certainty.value if discount.certainty else None,
        "region_limit": discount.region_limit,
        "eligibility": discount.eligibility,
        "source_url": discount.source_url,
        "verified_at": discount.verified_at.strftime("%Y-%m-%d %H:%M:%S")
        if discount.verified_at
        else None,
        "data_status": discount.data_status.value,
        "note": discount.note,
    }


def policy(policy: Policy) -> Dict[str, Any]:
    return {
        "scope": policy.scope.value,
        "scope_label": _scope_label(policy.scope),
        "category": policy.category.value,
        "category_label": _category_label(policy.category),
        "title": policy.title,
        "summary": policy.summary,
        "data_status": policy.data_status.value,
    }


def _scope_label(scope: PolicyScope) -> str:
    return {
        PolicyScope.PLATFORM_RULE: "平台通用规则",
        PolicyScope.SHOP_PROMISE: "店铺承诺",
        PolicyScope.PRODUCT_PAGE_PROMISE: "商品页承诺",
        PolicyScope.PENDING_VERIFICATION: "尚待核实",
    }[scope]


def _category_label(category: PolicyCategory) -> str:
    return {
        PolicyCategory.AFTER_SALES: "售后/退换",
        PolicyCategory.RETURN_RESTRICTION: "退换限制",
        PolicyCategory.WARRANTY: "保修",
        PolicyCategory.SHIPPING: "发货/物流",
        PolicyCategory.AUTHENTICITY: "正品保障",
        PolicyCategory.INVOICE: "发票",
        PolicyCategory.PRICE_PROTECTION: "价保",
    }[category]


def offer(
    offer: Offer, breakdown: PriceBreakdown, user_region: Optional[str] = None
) -> Dict[str, Any]:
    """一张购买卡片需要的全部字段。

    ``user_region`` 是用户自己填写的收货地，只用于判断补贴文案里写明的
    地区限制和它对不对得上 —— 不替用户认定补贴资格。
    """
    traps = detect_traps(
        [p.title for p in offer.policies],
        [d.label for d in offer.discounts],
        sku_text=offer.sku_text or "",
        title=offer.title,
        source_url=offer.source_url or offer.url,
    )
    subsidy = None
    # 收货地优先用用户自己填的；没填才退到页面"配送至"，并且标明出处 ——
    # 那个地址是登录账号的默认地址，未必是用户真正要送的地方。
    region = (user_region or "").strip() or None
    region_source = "user"
    if not region and (offer.region or "").strip():
        region = offer.region.strip()
        region_source = "page"
    for entry in offer.discounts:
        if entry.kind is not DiscountKind.SUBSIDY:
            continue
        reading = interpret_subsidy_text(entry.label, region)
        if reading is not None:
            subsidy = reading.to_dict()
            subsidy["region_source"] = region_source
            scenarios = subsidy_scenarios(
                Decimal(str(breakdown.definite_total)), reading
            )
            subsidy["scenarios"] = scenarios.to_dict() if scenarios else None
            break
    return {
        "id": offer.id,
        "platform": offer.platform.value,
        "platform_label": offer.platform.label,
        "title": offer.title,
        "url": offer.url,
        "source_url": offer.source_url or offer.url,
        "shop_name": offer.shop_name,
        "shop_type": offer.shop_type.value,
        "shop_type_label": offer.shop_type.label,
        "sku_text": offer.sku_text,
        "sales_text": offer.sales_text,
        "list_price": money(offer.list_price),
        "shipping_fee": money(offer.shipping_fee),
        "discounts": [discount(d) for d in offer.discounts],
        "policies": [policy(p) for p in offer.policies],
        "traps": [t.to_dict() for t in traps],
        "trap_summary": summarize_traps(traps),
        "worst_trap_severity": (
            worst_severity(traps).value if worst_severity(traps) else None
        ),
        "subsidy": subsidy,
        "breakdown": breakdown_dict(breakdown),
        "coupon_tree": build_coupon_tree(offer, breakdown).to_dict(),
        "data_status": offer.data_status.value,
        "data_status_label": offer.data_status.label,
        "source": offer.source,
        "fetched_at": offer.fetched_at.strftime("%Y-%m-%d %H:%M:%S")
        if offer.fetched_at
        else None,
        "verified_at": offer.verified_at.strftime("%Y-%m-%d %H:%M:%S")
        if offer.verified_at
        else None,
        "credibility": offer.credibility,
        "affiliate": offer.affiliate,
        "certainty": certainty_of(offer),
        "is_demo": offer.data_status == DataStatus.DEMO,
        "match_confidence": offer.match_confidence,
        "match_notes": list(offer.match_notes or []),
    }


def recommendation(rec: Recommendation) -> Dict[str, Any]:
    return {
        "canonical_id": rec.canonical_id,
        "summary": rec.summary,
        "confidence": rec.confidence,
        "missing_data": list(rec.missing_data),
        "generated_at": rec.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        if rec.generated_at
        else None,
        "options": [
            {
                "offer_id": o.offer_id,
                "platform": o.platform.value,
                "platform_label": o.platform.label,
                "pick_type": o.pick_type,
                "headline": o.headline,
                "definite_total": money(o.definite_total),
                "potential_total": money(o.potential_total),
                "score": o.score,
                "evidence": list(o.evidence),
                "conditions": list(o.conditions),
                "risks": list(o.risks),
            }
            for o in rec.options
        ],
    }


def evidence(offer: Offer) -> List[Dict[str, Any]]:
    """证据条目（来源 URL / 标题 / 抓取时间）。"""
    return [
        {
            "source_url": offer.source_url or offer.url,
            "title": offer.title,
            "fetched_at": offer.fetched_at.strftime("%Y-%m-%d %H:%M:%S")
            if offer.fetched_at
            else None,
            "source": offer.source,
            "credibility": offer.credibility,
        }
    ]

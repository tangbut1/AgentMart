"""把 domain 模型序列化成前端可用的 JSON。

单独一个模块而不是给 domain 加 ``to_dict``：domain 保持纯净（不依赖
任何传输层概念），序列化规则集中在一处，前端契约变化只改这里。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from ..domain.enums import ConditionKind, DataStatus, PolicyCategory, PolicyScope
from ..domain.models import Discount, Offer, Policy, PriceBreakdown, PriceLine, Recommendation
from .enums import PriceCertainty

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
        PolicyCategory.WARRANTY: "保修",
        PolicyCategory.SHIPPING: "发货/物流",
        PolicyCategory.AUTHENTICITY: "正品保障",
        PolicyCategory.INVOICE: "发票",
        PolicyCategory.PRICE_PROTECTION: "价保",
    }[category]


def offer(offer: Offer, breakdown: PriceBreakdown) -> Dict[str, Any]:
    """一张购买卡片需要的全部字段。"""
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
        "breakdown": breakdown_dict(breakdown),
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

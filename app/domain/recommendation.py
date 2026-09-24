"""可解释的推荐引擎。

设计原则：
- 纯规则、可复现：每个分数都能拆成价格/服务/数据新鲜度三个因子；
- 只在数据足够时给出判断，数据不足时明确说明缺什么；
- 每个推荐都附带证据、适用条件与风险；
- 演示数据（DEMO）永远不参与推荐。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from .enums import (
    CommercialRelation,
    ConditionKind,
    CurationStatus,
    DataStatus,
    DiscountKind,
    Platform,
    ShopType,
)
from .models import (
    CanonicalProduct,
    Offer,
    PriceBreakdown,
    Recommendation,
    RecommendationOption,
    Review,
    UserPreferences,
)
from .pricing import compute_price_breakdown

STALE_AFTER = timedelta(hours=24)

SHOP_SERVICE_SCORE: Dict[ShopType, float] = {
    ShopType.SELF_OPERATED: 1.0,
    ShopType.OFFICIAL_FLAGSHIP: 0.9,
    ShopType.FLAGSHIP: 0.75,
    ShopType.AUTHORIZED: 0.7,
    ShopType.THIRD_PARTY: 0.45,
    ShopType.UNKNOWN: 0.4,
}

PRIORITY_WEIGHTS: Dict[str, Dict[str, float]] = {
    "price": {"price": 0.70, "service": 0.20, "freshness": 0.10},
    "service": {"price": 0.35, "service": 0.50, "freshness": 0.15},
    "balanced": {"price": 0.50, "service": 0.35, "freshness": 0.15},
}

PLATFORM_AFTER_SALES_NOTE = {
    Platform.JD: "京东对自营商品提供平台级售后介入，退换货流程相对标准化",
    Platform.TAOBAO: "淘宝售后依赖店铺承诺与平台规则，下单前需确认店铺服务",
    Platform.TMALL: "天猫店铺受平台售后规则约束，官方旗舰店通常由品牌方履约",
    Platform.PDD: "拼多多部分商品支持平台介入售后，具体政策以商品页面为准",
    Platform.DOUYIN: "抖音电商售后以小店/直播间承诺为主，建议保留直播录屏等凭证",
}

_POLICY_CATEGORIES_STRONG = {"after_sales", "warranty", "authenticity"}


def _is_fresh(offer: Offer, now: datetime) -> bool:
    if offer.data_status != DataStatus.REAL:
        return False
    fetched = offer.fetched_at or offer.verified_at
    if fetched is None:
        return False
    return now - fetched <= STALE_AFTER


# 价格分按相对价差折算：与最低确定到手价相差 25% 以内线性衰减，
# 超出则记 0 分。这样「价差小」时售后与可靠性更能影响决策，
# 「价差大」时价格主导 —— 与用户直觉一致且可解释。
PRICE_GAP_THRESHOLD = Decimal("0.25")


def _price_scores(breakdowns: Dict[str, PriceBreakdown]) -> Dict[str, float]:
    """按确定到手价归一化到 0-1（越便宜越高分）。"""
    totals = {oid: b.definite_total for oid, b in breakdowns.items()}
    if not totals:
        return {}
    lo = min(totals.values())
    hi = max(totals.values())
    if hi == lo:
        return {oid: 1.0 for oid in totals}
    scores = {}
    for oid, total in totals.items():
        gap = (total - lo) / lo if lo > 0 else Decimal(1)
        scores[oid] = float(max(Decimal(0), Decimal(1) - gap / PRICE_GAP_THRESHOLD))
    return scores


def _service_score(offer: Offer) -> float:
    score = SHOP_SERVICE_SCORE.get(offer.shop_type, 0.4)
    strong = {
        p.category.value for p in offer.policies
        if p.data_status != DataStatus.DEMO
    } & _POLICY_CATEGORIES_STRONG
    if strong:
        score = min(1.0, score + 0.08 * len(strong))
    return score


def _freshness_score(offer: Offer, now: datetime) -> float:
    if offer.data_status == DataStatus.REAL:
        return 1.0 if _is_fresh(offer, now) else 0.5
    if offer.data_status == DataStatus.UNVERIFIED:
        return 0.3
    return 0.0


def _verified_reviews(reviews: List[Review]) -> List[Review]:
    return [
        r for r in reviews
        if r.curation_status == CurationStatus.VERIFIED
        and r.data_status != DataStatus.DEMO
    ]


def _model_risks(reviews: List[Review]) -> List[str]:
    """从已核实的评测中提炼模型级风险提示（用于各选项的风险说明）。"""
    risks: List[str] = []
    verified = _verified_reviews(reviews)
    if not verified:
        return risks
    cons = [c for r in verified for c in r.cons if c]
    if cons:
        risks.append("已核实评测中提到该型号的不足：" + "；".join(cons[:3]))
    undisclosed = [
        r for r in verified
        if r.commercial_relation in (CommercialRelation.UNDISCLOSED, CommercialRelation.UNKNOWN)
    ]
    if undisclosed:
        risks.append(
            f"{len(undisclosed)} 条参考评测未标注商业合作关系，观点可能存在倾向性"
        )
    return risks


def _build_option(
    offer: Offer,
    breakdown: PriceBreakdown,
    pick_type: str,
    score: float,
    now: datetime,
    reviews: List[Review],
) -> RecommendationOption:
    evidence: List[str] = []
    conditions: List[str] = []
    risks: List[str] = []

    evidence.append(
        f"确定到手价 ¥{breakdown.definite_total}"
        f"（标价 ¥{breakdown.list_price}"
        + (f" + 运费 ¥{breakdown.shipping_fee}" if breakdown.shipping_fee else "")
        + "，已计入无条件优惠）"
    )
    if offer.shop_type != ShopType.UNKNOWN and offer.shop_name:
        evidence.append(f"店铺：{offer.shop_name}（{offer.shop_type.label}）")
    else:
        risks.append("店铺类型未能核实，售后保障程度不确定")
    evidence.append(f"数据来源：{offer.source or '未知'}，采集于 {_fmt_time(offer.fetched_at)}")
    if offer.affiliate:
        risks.append("该链接为联盟/返佣链接，平台可能获得佣金")

    conditional = [
        d for d in offer.discounts
        if d.condition_kind == ConditionKind.CONDITIONAL
        and d.data_status != DataStatus.DEMO
        and d.kind != DiscountKind.TRADE_IN
    ]
    if conditional:
        conditions.append(
            f"潜在到手价 ¥{breakdown.potential_total}，需满足："
            + "；".join(f"{d.label}（{d.condition}）" for d in conditional)
        )
    unverifiable = [
        d for d in offer.discounts
        if d.condition_kind == ConditionKind.UNVERIFIABLE
    ]
    if unverifiable:
        risks.append(
            "以下优惠规则无法核实，未计入到手价："
            + "、".join(d.label for d in unverifiable)
        )
    if not _is_fresh(offer, now):
        risks.append("价格数据不是最新采集，下单前请以商品页面实时价格为准")
    if offer.shop_type in (ShopType.THIRD_PARTY, ShopType.UNKNOWN):
        risks.append("第三方店铺货源与售后依赖店铺自身承诺，建议优先平台官方渠道")
    risks.extend(_model_risks(reviews))
    note = PLATFORM_AFTER_SALES_NOTE.get(offer.platform)
    if note:
        evidence.append(note)

    return RecommendationOption(
        offer_id=offer.id,
        platform=offer.platform,
        pick_type=pick_type,
        headline=f"{offer.platform.label} · {offer.shop_name or '店铺待核实'} · 到手价 ¥{breakdown.definite_total}",
        definite_total=breakdown.definite_total,
        potential_total=breakdown.potential_total,
        score=round(score, 3),
        evidence=evidence,
        conditions=conditions,
        risks=risks,
    )


def _fmt_time(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "时间未知"


def recommend(
    canonical: CanonicalProduct,
    reviews: List[Review],
    prefs: Optional[UserPreferences] = None,
    now: Optional[datetime] = None,
) -> Recommendation:
    now = now or datetime.now()
    prefs = prefs or UserPreferences()

    real_offers = [o for o in canonical.offers if o.data_status != DataStatus.DEMO]
    result = Recommendation(canonical_id=canonical.id, generated_at=now)

    if not real_offers:
        result.summary = (
            "当前没有可核验的真实购买数据（仅有演示数据或尚未接入平台），"
            "无法给出购买建议。请接入平台数据后重试。"
        )
        result.confidence = 0.0
        result.missing_data.append("没有任何已接入平台返回真实数据")
        return result

    breakdowns = {o.id: compute_price_breakdown(o) for o in real_offers}
    price_scores = _price_scores(breakdowns)
    weights = PRIORITY_WEIGHTS.get(prefs.priority, PRIORITY_WEIGHTS["balanced"])

    scored: List[Tuple[Offer, float]] = []
    for offer in real_offers:
        p_score = price_scores.get(offer.id, 0.0)
        s_score = _service_score(offer)
        f_score = _freshness_score(offer, now)
        total = (
            weights["price"] * p_score
            + weights["service"] * s_score
            + weights["freshness"] * f_score
        )
        if prefs.budget_max is not None:
            if breakdowns[offer.id].definite_total > prefs.budget_max:
                total *= 0.3
        scored.append((offer, total))

    scored.sort(key=lambda t: t[1], reverse=True)
    best_offer, best_score = scored[0]

    # 首选
    result.options.append(_build_option(
        best_offer, breakdowns[best_offer.id], "best_overall", best_score, now, reviews
    ))

    # 更省钱：确定到手价最低（若与首选不同）
    cheapest = min(real_offers, key=lambda o: breakdowns[o.id].definite_total)
    if cheapest.id != best_offer.id:
        result.options.append(_build_option(
            cheapest, breakdowns[cheapest.id], "cheapest", best_score * 0.95, now, reviews
        ))

    # 更稳妥：服务分最高
    safest = max(real_offers, key=lambda o: (_service_score(o), -breakdowns[o.id].definite_total))
    if safest.id not in {best_offer.id, cheapest.id}:
        result.options.append(_build_option(
            safest, breakdowns[safest.id], "safest", best_score * 0.9, now, reviews
        ))

    # 汇总与置信度
    verified_reviews = _verified_reviews(reviews)
    real_ratio = len(real_offers) / max(1, len(canonical.offers))
    fresh_ratio = sum(1 for o in real_offers if _is_fresh(o, now)) / len(real_offers)
    confidence = round(
        0.55 * real_ratio + 0.30 * fresh_ratio + 0.15 * min(1.0, len(verified_reviews) / 2),
        3,
    )
    result.confidence = confidence

    if len(real_offers) == 1:
        result.missing_data.append("只有一个平台返回真实数据，无法横向比较")
    if not verified_reviews:
        result.missing_data.append("暂无经人工核实的评测观点可供参考")
    if fresh_ratio < 1.0:
        result.missing_data.append("部分价格数据采集时间较久，新鲜度不足")
    if canonical.offers and any(o.data_status == DataStatus.DEMO for o in canonical.offers):
        result.missing_data.append("该结果包含演示数据，已从推荐中排除")

    diff = breakdowns[cheapest.id].definite_total - breakdowns[best_offer.id].definite_total
    if diff > 0 and cheapest.id != best_offer.id:
        result.summary = (
            f"综合价格、售后与数据可信度，首选 {best_offer.platform.label}"
            f"（{best_offer.shop_name or '店铺待核实'}），确定到手价 "
            f"¥{breakdowns[best_offer.id].definite_total}；"
            f"若只想最低价，{cheapest.platform.label}可再省 ¥{diff}，"
            f"但需接受其售后与货源条件（见风险说明）。"
        )
    else:
        result.summary = (
            f"综合价格、售后与数据可信度，首选 {best_offer.platform.label}"
            f"（{best_offer.shop_name or '店铺待核实'}），确定到手价 "
            f"¥{breakdowns[best_offer.id].definite_total}，且它同时是当前价格最低的可核验选项。"
        )
    return result

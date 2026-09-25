"""可解释的推荐引擎。

设计原则：
- 纯规则、可复现：每个分数都能拆成价格/服务/数据新鲜度三个因子；
- 只在数据足够时给出判断，数据不足时明确说明缺什么；
- 每个推荐都附带证据、适用条件与风险；
- 演示数据（DEMO）永远不参与推荐。

跨平台比价只比公开轨（谁来看都成立的抵扣），账号券带来的差额单独
披露、不并进排名分 —— 理由见 app/domain/decision.py 的模块说明。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from .decision import (
    PRIORITY_LABELS,
    PRIORITY_WEIGHTS,
    PLATFORM_AFTER_SALES_NOTE,
    build_matrix,
    cheapest_on_public_track,
    freshness_score,
    is_fresh,
    price_scores,
    service_score,
)
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
    sku_sync: str = "unknown",
) -> RecommendationOption:
    evidence: List[str] = []
    conditions: List[str] = []
    risks: List[str] = []

    # 两个轨都写进证据：公开轨是跨平台可比的数，我的轨是这个人实际会付的数。
    # 只写一个都会误导 —— 只写我的轨，用户没法验证这个价是不是谁都能拿到；
    # 只写公开轨，用户会以为自己要付的比实际多。
    evidence.append(
        f"公开轨到手价 ¥{breakdown.public_total}"
        f"（标价 ¥{breakdown.list_price}"
        + (f" + 运费 ¥{breakdown.shipping_fee}" if breakdown.shipping_fee else "")
        + "，只计谁来看都成立的抵扣）"
    )
    gap = breakdown.account_gap
    if gap > 0:
        evidence.append(
            f"我的轨到手价 ¥{breakdown.account_total}，比公开轨低 ¥{gap}"
            " —— 来自你账号下已显示可用的券，换个账号拿不到"
        )
    else:
        evidence.append(
            f"我的轨到手价 ¥{breakdown.account_total}，与公开轨相同"
            "（页面上没有你这个账号专属的可用抵扣）"
        )
    if offer.shop_type != ShopType.UNKNOWN and offer.shop_name:
        evidence.append(f"店铺：{offer.shop_name}（{offer.shop_type.label}）")
    else:
        risks.append("店铺类型未能核实，售后保障程度不确定")
    evidence.append(f"数据来源：{offer.source or '未知'}，采集于 {_fmt_time(offer.fetched_at)}")
    if offer.affiliate:
        risks.append("该链接为联盟/返佣链接，平台可能获得佣金")
    if sku_sync == "variant":
        spec = offer.sku_spec.describe() if offer.sku_spec else ""
        risks.append(
            "该报价与组内基准不是同一个规格"
            + (f"（{spec}）" if spec else "")
            + "，价格差里含规格差异，不参与赢家评选"
        )
    elif sku_sync == "unknown":
        risks.append("未读到该报价的规格信息，无法确认是不是同一个 SKU")

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
    if not is_fresh(offer, now):
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
    # 排名分与决策矩阵同一套口径：公开轨 + 服务 + 新鲜度。
    # 规格不一致的报价照常展示，但不参与赢家评选 —— 以矩阵算出的
    # blocked 为准，不另读 offer.sku_sync，避免两处口径不一致。
    result.matrix = build_matrix(real_offers, breakdowns, prefs.priority, now)
    blocked_ids = {row["offer_id"] for row in result.matrix["rows"] if row["blocked"]}
    sku_sync_by_id = {row["offer_id"]: row["sku_sync"] for row in result.matrix["rows"]}
    p_scores = price_scores(breakdowns)
    weights = PRIORITY_WEIGHTS.get(prefs.priority, PRIORITY_WEIGHTS["balanced"])

    eligible = [o for o in real_offers if o.id not in blocked_ids] or real_offers

    scored: List[Tuple[Offer, float]] = []
    for offer in eligible:
        total = (
            weights["price"] * p_scores.get(offer.id, 0.0)
            + weights["service"] * service_score(offer)
            + weights["freshness"] * freshness_score(offer, now)
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

    # 更省钱：公开轨最低（若与首选不同）
    cheapest = cheapest_on_public_track(eligible, breakdowns)
    if cheapest is not None and cheapest.id != best_offer.id:
        result.options.append(_build_option(
            cheapest, breakdowns[cheapest.id], "cheapest", best_score * 0.95, now, reviews,
            sku_sync_by_id[cheapest.id],
        ))

    # 更稳妥：服务分最高
    safest = max(eligible, key=lambda o: (service_score(o), -breakdowns[o.id].definite_total))
    if safest.id not in {best_offer.id, cheapest.id if cheapest else ""}:
        result.options.append(_build_option(
            safest, breakdowns[safest.id], "safest_service", best_score * 0.9, now, reviews,
            sku_sync_by_id[safest.id],
        ))

    # 汇总与置信度
    verified_reviews = _verified_reviews(reviews)
    real_ratio = len(real_offers) / max(1, len(canonical.offers))
    fresh_ratio = sum(1 for o in real_offers if is_fresh(o, now)) / len(real_offers)
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
    if blocked_ids:
        result.missing_data.append("组内存在规格不一致的报价，未纳入赢家评选")
    if any(row["sku_sync"] == "unknown" for row in result.matrix["rows"]):
        result.missing_data.append("部分报价未读到规格，无法确认是否同一个 SKU")

    # 汇总里同时给两个轨的数：用户实际会付的是我的轨，
    # 跨平台可比的公开轨也写明，避免拿账号券当平台优势。
    best_breakdown = breakdowns[best_offer.id]
    priority_note = PRIORITY_LABELS.get(prefs.priority, prefs.priority)
    if cheapest is not None and cheapest.id != best_offer.id:
        diff = breakdowns[cheapest.id].public_total - best_breakdown.public_total
        result.summary = (
            f"按「{priority_note}」加权公开轨价格、店铺售后与数据新鲜度，首选 "
            f"{best_offer.platform.label}（{best_offer.shop_name or '店铺待核实'}），"
            f"公开轨到手 ¥{best_breakdown.public_total}"
            + (f"，用上你账号里的券后实付 ¥{best_breakdown.account_total}"
               if best_breakdown.account_gap > 0 else "")
            + f"；若只想最低价，{cheapest.platform.label}公开轨可再省 ¥{diff}，"
            "但需接受其售后与货源条件（见风险说明）。"
        )
    else:
        result.summary = (
            f"按「{priority_note}」加权公开轨价格、店铺售后与数据新鲜度，首选 "
            f"{best_offer.platform.label}（{best_offer.shop_name or '店铺待核实'}），"
            f"公开轨到手 ¥{best_breakdown.public_total}"
            + (f"，用上你账号里的券后实付 ¥{best_breakdown.account_total}"
               if best_breakdown.account_gap > 0 else "")
            + "，且它同时是公开轨最低的可核验选项。"
        )
    return result

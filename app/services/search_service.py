"""编排层：适配器采集 → 匹配分组 → 价格拆解 → 评测关联 → 推荐。"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime
from typing import List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters import registry
from ..adapters.base import AdapterResult
from ..adapters.demo import demo_offers, demo_reviews
from ..domain.enums import DataStatus, Platform
from ..domain.matching import group_offers
from ..domain.models import (
    CanonicalProduct,
    Offer,
    Recommendation,
    Review,
    UserPreferences,
)
from ..domain.pricing import compute_price_breakdown
from ..domain.recommendation import recommend
from ..infra.cache import cache
from ..reviews import curation as curation_service
from ..reviews.criteria import evaluate_review
from ..schemas import (
    CanonicalProductOut,
    CompareResponse,
    DiscountOut,
    OfferOut,
    PlatformSearchResult,
    PlatformStatus,
    PriceBreakdownOut,
    PriceLineOut,
    PolicyOut,
    RecommendationOptionOut,
    RecommendationOut,
    ReviewAssessmentOut,
    ReviewOut,
    SearchResponse,
)

ADAPTER_TIMEOUT_SECONDS = 20.0


# ─── domain → API 映射 ─────────────────────────────────────────

def map_breakdown(breakdown) -> PriceBreakdownOut:
    return PriceBreakdownOut(
        list_price=breakdown.list_price,
        shipping_fee=breakdown.shipping_fee,
        lines=[
            PriceLineOut(
                label=line.label,
                kind=line.kind,
                amount=line.amount,
                condition_kind=line.condition_kind,
                condition=line.condition,
                source_url=line.source_url,
                data_status=line.data_status,
            )
            for line in breakdown.lines
        ],
        definite_total=breakdown.definite_total,
        potential_total=breakdown.potential_total,
        unverifiable_total=breakdown.unverifiable_total,
        applied_groups=breakdown.applied_groups,
        notes=breakdown.notes,
    )


def map_offer(offer: Offer) -> OfferOut:
    return OfferOut(
        id=offer.id,
        platform=offer.platform,
        platform_product_id=offer.platform_product_id,
        title=offer.title,
        url=offer.url,
        list_price=offer.list_price,
        shop_name=offer.shop_name,
        shop_type=offer.shop_type,
        shop_url=offer.shop_url,
        brand=offer.brand,
        sku_text=offer.sku_text,
        images=offer.images,
        sales_text=offer.sales_text,
        shipping_fee=offer.shipping_fee,
        region=offer.region,
        affiliate=offer.affiliate,
        data_status=offer.data_status,
        source=offer.source,
        source_url=offer.source_url,
        fetched_at=offer.fetched_at,
        verified_at=offer.verified_at,
        credibility=offer.credibility,
        match_confidence=offer.match_confidence,
        match_notes=offer.match_notes,
        discounts=[
            DiscountOut(
                kind=d.kind,
                label=d.label,
                amount=d.resolved_amount(offer.list_price),
                condition=d.condition,
                condition_kind=d.condition_kind,
                stack_group=d.stack_group,
                region_limit=d.region_limit,
                eligibility=d.eligibility,
                source_url=d.source_url,
                data_status=d.data_status,
            )
            for d in offer.discounts
        ],
        policies=[
            PolicyOut(
                scope=p.scope,
                category=p.category,
                title=p.title,
                summary=p.summary,
                source_url=p.source_url,
                updated_at=p.updated_at,
                region=p.region,
                data_status=p.data_status,
            )
            for p in offer.policies
        ],
        breakdown=map_breakdown(compute_price_breakdown(offer)),
    )


def map_group(group: CanonicalProduct) -> CanonicalProductOut:
    return CanonicalProductOut(
        id=group.id,
        title=group.title,
        brand=group.brand,
        model=group.model,
        category=group.category,
        specs=group.specs,
        confidence=group.confidence,
        warnings=group.warnings,
        offers=[map_offer(o) for o in group.offers],
        best_definite_price=group.best_definite_price,
    )


def map_review(review: Review, query_model: Optional[str] = None) -> ReviewOut:
    assessment = evaluate_review(review, query_model)
    return ReviewOut(
        id=review.id,
        platform=review.platform,
        url=review.url,
        title=review.title,
        creator_name=review.creator_name,
        creator_id=review.creator_id,
        creator_url=review.creator_url,
        cover_url=review.cover_url,
        published_at=review.published_at,
        duration_seconds=review.duration_seconds,
        view_count=review.view_count,
        like_count=review.like_count,
        model_tested=review.model_tested,
        pros=review.pros,
        cons=review.cons,
        quotes=review.quotes,
        test_evidence=review.test_evidence,
        scenarios=review.scenarios,
        commercial_relation=review.commercial_relation,
        curation_status=review.curation_status,
        curated_by=review.curated_by,
        curated_at=review.curated_at,
        curator_notes=review.curator_notes,
        ai_summary=review.ai_summary,
        ai_generated_at=review.ai_generated_at,
        data_status=review.data_status,
        fetched_at=review.fetched_at,
        related_models=review.related_models,
        relevance_note=review.relevance_note,
        assessment=ReviewAssessmentOut(
            checks=[
                {"dimension": c.dimension, "met": c.met, "note": c.note}
                for c in assessment.checks
            ],
            score=assessment.score,
            recommend_reference=assessment.recommend_reference,
        ),
    )


def map_recommendation(rec: Recommendation) -> RecommendationOut:
    return RecommendationOut(
        canonical_id=rec.canonical_id,
        options=[
            RecommendationOptionOut(
                offer_id=o.offer_id,
                platform=o.platform,
                pick_type=o.pick_type,
                headline=o.headline,
                definite_total=o.definite_total,
                potential_total=o.potential_total,
                score=o.score,
                evidence=o.evidence,
                conditions=o.conditions,
                risks=o.risks,
            )
            for o in rec.options
        ],
        summary=rec.summary,
        confidence=rec.confidence,
        missing_data=rec.missing_data,
        generated_at=rec.generated_at,
    )


# ─── 查询处理 ──────────────────────────────────────────────────

def _looks_like_url(text: str) -> bool:
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def _extract_keyword_from_url(url: str) -> Optional[str]:
    """从商品链接中提取可用于搜索的关键词（不抓取页面）。"""
    parsed = urlparse(unquote(url))
    candidates: List[str] = []
    for segment in parsed.path.split("/"):
        segment = segment.strip()
        if not segment or segment.isdigit():
            continue
        segment = re.sub(r"\.(html?|php|aspx?)$", "", segment)
        if re.search(r"[\u4e00-\u9fffA-Za-z]", segment) and len(segment) >= 2:
            candidates.append(segment)
    query = parsed.query
    if query:
        candidates.append(query)
    text = " ".join(candidates).strip()
    return text[:80] if text else None


def _group_id_from_signature(signature) -> str:
    digest = hashlib.sha256(signature.key().encode("utf-8")).hexdigest()[:12]
    return f"cp_{digest}"


def _canonical_title(offers: List[Offer]) -> str:
    """从组内 offer 标题提炼商品组标题（去掉演示标记与平台后缀）。"""
    from collections import Counter

    cleaned = []
    for offer in offers:
        title = offer.title
        if offer.data_status == DataStatus.DEMO:
            title = re.sub(r"【演示】", "", title)
            title = re.sub(r"(京东|淘宝|天猫|拼多多|抖音电商)?在售链接", "", title)
        title = title.strip()
        if title:
            cleaned.append(title)
    if not cleaned:
        return "未命名商品"
    counts = Counter(cleaned)
    best = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))
    return best[0]


# ─── 主流程 ────────────────────────────────────────────────────

async def _query_adapters(
    keyword: str, platforms: Optional[Sequence[Platform]] = None
) -> List[AdapterResult]:
    adapters = registry.all_adapters()
    if platforms:
        adapters = [a for a in adapters if a.platform in set(platforms)]

    async def _run(adapter) -> AdapterResult:
        try:
            return await asyncio.wait_for(
                adapter.search(keyword), timeout=ADAPTER_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            from ..adapters.base import AdapterResult as _AR
            from ..domain.enums import ConnectionStatus

            return _AR(
                platform=adapter.platform,
                status=ConnectionStatus.ERROR,
                error="timeout",
                message=f"{adapter.display_name} 数据请求超时（{ADAPTER_TIMEOUT_SECONDS:.0f}s）",
            )
        except Exception as exc:  # 单个适配器崩溃不影响其他平台
            logger.exception(f"[search] adapter {adapter.adapter_name} failed")
            from ..adapters.base import AdapterResult as _AR
            from ..domain.enums import ConnectionStatus

            return _AR(
                platform=adapter.platform,
                status=ConnectionStatus.ERROR,
                error=str(exc),
                message=f"{adapter.display_name} 数据请求失败：{exc}",
            )

    return await asyncio.gather(*[_run(a) for a in adapters])


async def search_products(
    keyword: str,
    include_demo: bool = False,
    platforms: Optional[Sequence[Platform]] = None,
    session: Optional[AsyncSession] = None,
) -> SearchResponse:
    keyword = keyword.strip()
    cache_key = f"search:{keyword}:{include_demo}:{','.join(p.value for p in platforms) if platforms else 'all'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    response = SearchResponse(keyword=keyword, demo_included=include_demo)
    is_link = _looks_like_url(keyword)
    response.is_link_query = is_link
    search_keyword = keyword

    if is_link:
        extracted = _extract_keyword_from_url(keyword)
        response.link_notice = (
            "AgentMart 不抓取商品页面（遵守平台反爬规则）。"
            "商品链接的真实数据需要通过对应平台的开放接口获取，"
            "请在 .env 配置平台凭据（见 README）。"
        )
        if extracted:
            search_keyword = extracted
            response.link_notice += f"已从链接中提取关键词「{extracted}」进行搜索。"
        else:
            search_keyword = keyword
            response.link_notice += "未能从该链接提取有效关键词，请改用关键词搜索。"

    results = await _query_adapters(search_keyword, platforms)
    all_offers: List[Offer] = []
    for result in results:
        response.platform_results.append(PlatformSearchResult(
            platform=result.platform,
            status=result.status,
            message=result.message,
            offer_count=len(result.offers),
            elapsed_ms=result.elapsed_ms,
        ))
        all_offers.extend(result.offers)

    has_real = any(o.data_status == DataStatus.REAL for o in all_offers)
    response.has_real_data = has_real

    if include_demo:
        all_offers.extend(demo_offers(search_keyword))
        response.demo_notice = (
            "当前包含演示数据（虚构，仅用于开发联调）。演示数据不参与真实价格结论与推荐，"
            "界面中以「演示数据」标识。"
        )

    match_groups = group_offers(all_offers)
    groups: List[CanonicalProduct] = []
    for mg in match_groups:
        title = _canonical_title(mg.offers)
        group = CanonicalProduct(
            id=_group_id_from_signature(mg.signature),
            title=title,
            brand=mg.signature.brand,
            model="-".join(sorted(mg.signature.model_tokens)) or None,
            specs={
                "storage": mg.signature.storage,
                "color": mg.signature.color,
                "version": mg.signature.version,
                "condition": mg.signature.condition,
                "bundle": mg.signature.bundle,
            },
            offers=mg.offers,
            confidence=mg.confidence,
            warnings=list(mg.warnings),
        )
        groups.append(group)

    response.groups = [map_group(g) for g in groups]
    response.generated_at = datetime.now()
    cache.set(cache_key, response)
    return response


async def get_product_detail(
    keyword: str,
    group_id: str,
    include_demo: bool = False,
    preferences: Optional[UserPreferences] = None,
    session: Optional[AsyncSession] = None,
) -> Tuple[Optional[CanonicalProductOut], Optional[RecommendationOut], List[ReviewOut], bool]:
    search = await search_products(
        keyword, include_demo=include_demo, session=session
    )
    group_out = next((g for g in search.groups if g.id == group_id), None)
    if group_out is None:
        return None, None, [], search.demo_included

    # 找到对应的 domain group 以计算推荐
    reviews_out: List[ReviewOut] = []
    recommendation_out: Optional[RecommendationOut] = None
    if session is not None:
        try:
            reviews = await curation_service.find_reviews_for_model(
                session, group_out.title, include_demo=include_demo
            )
            reviews_out = [map_review(r, group_out.title) for r in reviews]
        except Exception:
            logger.exception("[detail] review association failed")

    # 用 domain 层重算推荐（保证与价格引擎一致）
    domain_group = await _rebuild_domain_group(search, group_id)
    if domain_group is not None:
        rec = recommend(domain_group, [
            _review_from_out(r) for r in reviews_out
        ], preferences)
        recommendation_out = map_recommendation(rec)

    return group_out, recommendation_out, reviews_out, search.demo_included


async def _rebuild_domain_group(search: SearchResponse, group_id: str):
    """从搜索结果反构 domain CanonicalProduct（用于推荐计算）。"""
    from ..domain.enums import DataStatus as _DS
    from ..domain.models import CanonicalProduct, Offer, Discount, Policy

    group_out = next((g for g in search.groups if g.id == group_id), None)
    if group_out is None:
        return None
    offers: List[Offer] = []
    for o in group_out.offers:
        offer = Offer(
            platform=o.platform,
            platform_product_id=o.platform_product_id,
            title=o.title,
            url=o.url,
            list_price=o.list_price,
            shop_name=o.shop_name,
            shop_type=o.shop_type,
            brand=o.brand,
            sku_text=o.sku_text,
            images=list(o.images),
            sales_text=o.sales_text,
            shipping_fee=o.shipping_fee,
            region=o.region,
            data_status=o.data_status,
            source=o.source,
            source_url=o.source_url,
            fetched_at=o.fetched_at,
            verified_at=o.verified_at,
            credibility=o.credibility,
            affiliate=o.affiliate,
            match_confidence=o.match_confidence,
            match_notes=list(o.match_notes),
        )
        offer.discounts = [
            Discount(
                kind=d.kind,
                label=d.label,
                amount=d.amount,
                condition=d.condition,
                condition_kind=d.condition_kind,
                stack_group=d.stack_group,
                source_url=d.source_url,
                data_status=d.data_status,
            )
            for d in o.discounts
        ]
        offer.policies = [
            Policy(
                scope=p.scope,
                category=p.category,
                title=p.title,
                summary=p.summary,
                source_url=p.source_url,
                updated_at=p.updated_at,
                region=p.region,
                data_status=p.data_status,
            )
            for p in o.policies
        ]
        offers.append(offer)
    return CanonicalProduct(
        id=group_out.id,
        title=group_out.title,
        brand=group_out.brand,
        model=group_out.model,
        category=group_out.category,
        specs=group_out.specs,
        offers=offers,
        confidence=group_out.confidence,
        warnings=group_out.warnings,
    )


def _review_from_out(review: ReviewOut) -> Review:
    from ..domain.models import Review as _Review

    return _Review(
        platform=review.platform,
        external_id=review.id.split(":", 1)[-1],
        url=review.url,
        title=review.title,
        creator_name=review.creator_name,
        creator_id=review.creator_id,
        creator_url=review.creator_url,
        published_at=review.published_at,
        pros=review.pros,
        cons=review.cons,
        quotes=review.quotes,
        test_evidence=review.test_evidence,
        scenarios=review.scenarios,
        commercial_relation=review.commercial_relation,
        curation_status=review.curation_status,
        model_tested=review.model_tested,
        data_status=review.data_status,
        related_models=review.related_models,
    )


async def compare_products(
    keyword: str,
    group_ids: List[str],
    include_demo: bool = False,
    preferences: Optional[UserPreferences] = None,
    session: Optional[AsyncSession] = None,
) -> CompareResponse:
    search = await search_products(
        keyword, include_demo=include_demo, session=session
    )
    response = CompareResponse(has_real_data=search.has_real_data)
    for group_id in group_ids:
        group_out = next((g for g in search.groups if g.id == group_id), None)
        if group_out is None:
            continue
        domain_group = await _rebuild_domain_group(search, group_id)
        if domain_group is None:
            continue
        reviews: List[Review] = []
        if session is not None:
            try:
                reviews = await curation_service.find_reviews_for_model(
                    session, group_out.title, include_demo=include_demo
                )
            except Exception:
                logger.exception("[compare] review association failed")
        rec = recommend(domain_group, reviews, preferences)
        response.groups.append(group_out)
        response.reviews[group_id] = [map_review(r, group_out.title) for r in reviews]
        response.recommendations[group_id] = map_recommendation(rec)
    return response


def platform_status_list() -> List[PlatformStatus]:
    return [
        PlatformStatus(
            platform=info.platform,
            adapter=info.adapter,
            status=info.status,
            message=info.message,
            docs_url=info.docs_url,
            required_env=info.required_env,
        )
        for info in registry.platform_statuses()
    ]

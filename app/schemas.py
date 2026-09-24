"""API 层 Pydantic 模型（与 domain 层一一对应，附溯源字段）。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .domain.enums import (
    CommercialRelation,
    ConditionKind,
    ConnectionStatus,
    CurationStatus,
    DataStatus,
    DiscountKind,
    Platform,
    PolicyCategory,
    PolicyScope,
    ReviewPlatform,
    ShopType,
)


# ─── 通用 ──────────────────────────────────────────────────────

class APIResponse(BaseModel):
    success: bool = True
    data: Optional[dict | list | None] = None
    message: Optional[str] = None


# ─── 平台状态 ──────────────────────────────────────────────────

class PlatformStatus(BaseModel):
    platform: Platform
    adapter: str
    status: ConnectionStatus
    message: str
    docs_url: str = ""
    required_env: List[str] = []


# ─── 优惠与价格 ────────────────────────────────────────────────

class DiscountOut(BaseModel):
    kind: DiscountKind
    label: str
    amount: Decimal
    condition: str = ""
    condition_kind: ConditionKind
    stack_group: Optional[str] = None
    region_limit: Optional[str] = None
    eligibility: Optional[str] = None
    source_url: Optional[str] = None
    data_status: DataStatus


class PriceLineOut(BaseModel):
    label: str
    kind: DiscountKind
    amount: Decimal
    condition_kind: ConditionKind
    condition: str = ""
    source_url: Optional[str] = None
    data_status: DataStatus


class PriceBreakdownOut(BaseModel):
    list_price: Decimal
    shipping_fee: Decimal
    lines: List[PriceLineOut] = []
    definite_total: Decimal
    potential_total: Decimal
    unverifiable_total: Decimal
    applied_groups: List[str] = []
    notes: List[str] = []


# ─── 政策 ──────────────────────────────────────────────────────

class PolicyOut(BaseModel):
    scope: PolicyScope
    category: PolicyCategory
    title: str
    summary: str
    source_url: Optional[str] = None
    updated_at: Optional[datetime] = None
    region: Optional[str] = None
    data_status: DataStatus


# ─── Offer ─────────────────────────────────────────────────────

class OfferOut(BaseModel):
    id: str
    platform: Platform
    platform_product_id: str
    title: str
    url: str
    list_price: Decimal
    shop_name: Optional[str] = None
    shop_type: ShopType
    shop_url: Optional[str] = None
    brand: Optional[str] = None
    sku_text: Optional[str] = None
    images: List[str] = []
    sales_text: Optional[str] = None
    shipping_fee: Decimal = Decimal("0")
    region: Optional[str] = None
    affiliate: bool = False
    data_status: DataStatus
    source: str = ""
    source_url: Optional[str] = None
    fetched_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    credibility: float = 0.5
    match_confidence: Optional[float] = None
    match_notes: List[str] = []
    discounts: List[DiscountOut] = []
    policies: List[PolicyOut] = []
    breakdown: Optional[PriceBreakdownOut] = None


# ─── 商品组 ────────────────────────────────────────────────────

class CanonicalProductOut(BaseModel):
    id: str
    title: str
    brand: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    specs: dict = {}
    confidence: float = 1.0
    warnings: List[str] = []
    offers: List[OfferOut] = []
    best_definite_price: Optional[Decimal] = None


# ─── 搜索 ──────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    include_demo: bool = False
    platforms: Optional[List[Platform]] = None


class PlatformSearchResult(BaseModel):
    platform: Platform
    status: ConnectionStatus
    message: str
    offer_count: int = 0
    elapsed_ms: int = 0


class SearchResponse(BaseModel):
    keyword: str
    is_link_query: bool = False
    link_notice: Optional[str] = None
    groups: List[CanonicalProductOut] = []
    platform_results: List[PlatformSearchResult] = []
    has_real_data: bool = False
    demo_included: bool = False
    demo_notice: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.now)


# ─── 评测 ──────────────────────────────────────────────────────

class CriteriaCheckOut(BaseModel):
    dimension: str
    met: bool
    note: str


class ReviewAssessmentOut(BaseModel):
    checks: List[CriteriaCheckOut] = []
    score: float
    recommend_reference: bool


class ReviewOut(BaseModel):
    # model_tested 等字段名与 pydantic 保留前缀冲突，显式关闭保护
    model_config = ConfigDict(protected_namespaces=())

    id: str
    platform: ReviewPlatform
    url: str
    title: str
    creator_name: str
    creator_id: Optional[str] = None
    creator_url: Optional[str] = None
    cover_url: Optional[str] = None
    published_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    model_tested: Optional[str] = None
    pros: List[str] = []
    cons: List[str] = []
    quotes: List[str] = []
    test_evidence: List[str] = []
    scenarios: List[str] = []
    commercial_relation: CommercialRelation
    curation_status: CurationStatus
    curated_by: Optional[str] = None
    curated_at: Optional[datetime] = None
    curator_notes: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_generated_at: Optional[datetime] = None
    data_status: DataStatus
    fetched_at: Optional[datetime] = None
    related_models: List[str] = []
    relevance_note: Optional[str] = None
    assessment: Optional[ReviewAssessmentOut] = None


class ReviewSubmitRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    """提交评测链接 + 人工整理内容。"""

    url: str = Field(..., min_length=5, max_length=500)
    title: Optional[str] = None
    creator_name: Optional[str] = None
    model_tested: Optional[str] = None
    pros: List[str] = []
    cons: List[str] = []
    quotes: List[str] = []
    test_evidence: List[str] = []
    scenarios: List[str] = []
    commercial_relation: CommercialRelation = CommercialRelation.UNKNOWN
    curator_notes: Optional[str] = None
    related_models: List[str] = []
    submitter: str = "anonymous"


class ReviewCurateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: CurationStatus
    curator: str = "admin"
    model_tested: Optional[str] = None
    pros: Optional[List[str]] = None
    cons: Optional[List[str]] = None
    quotes: Optional[List[str]] = None
    test_evidence: Optional[List[str]] = None
    scenarios: Optional[List[str]] = None
    commercial_relation: Optional[CommercialRelation] = None
    curator_notes: Optional[str] = None
    related_models: Optional[List[str]] = None
    relevance_note: Optional[str] = None


class ReviewResolveRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=500)


class ReviewResolveResponse(BaseModel):
    ok: bool
    review: Optional[ReviewOut] = None
    error: Optional[str] = None
    notice: Optional[str] = None


# ─── 推荐 ──────────────────────────────────────────────────────

class RecommendationPreferences(BaseModel):
    budget_max: Optional[Decimal] = None
    priority: str = "balanced"  # price | service | balanced
    scenario: Optional[str] = None
    region: Optional[str] = None


class RecommendationOptionOut(BaseModel):
    offer_id: str
    platform: Platform
    pick_type: str
    headline: str
    definite_total: Decimal
    potential_total: Decimal
    score: float
    evidence: List[str] = []
    conditions: List[str] = []
    risks: List[str] = []


class RecommendationOut(BaseModel):
    canonical_id: str
    options: List[RecommendationOptionOut] = []
    summary: str = ""
    confidence: float = 0.0
    missing_data: List[str] = []
    generated_at: Optional[datetime] = None


# ─── 商品详情 / 对比 ───────────────────────────────────────────

class ProductDetailResponse(BaseModel):
    group: Optional[CanonicalProductOut] = None
    reviews: List[ReviewOut] = []
    recommendation: Optional[RecommendationOut] = None
    demo_included: bool = False


class CompareRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    group_ids: List[str] = Field(..., min_length=1, max_length=5)
    include_demo: bool = False
    preferences: Optional[RecommendationPreferences] = None


class CompareResponse(BaseModel):
    groups: List[CanonicalProductOut] = []
    reviews: Dict[str, List[ReviewOut]] = {}
    recommendations: Dict[str, RecommendationOut] = {}
    has_real_data: bool = False


# ─── 数据来源 ──────────────────────────────────────────────────

class DataSourceInfo(BaseModel):
    name: str
    kind: str  # platform_api | review_metadata | curated | demo
    status: str
    description: str
    last_updated: Optional[datetime] = None
    url: Optional[str] = None

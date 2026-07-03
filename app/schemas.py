from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


# ─── Enums ───────────────────────────────────────────────────
class Platform(str, Enum):
    JD = "jd"
    TAOBAO = "taobao"
    TMALL = "tmall"


class VideoPlatform(str, Enum):
    BILIBILI = "bilibili"
    DOUYIN = "douyin"


class ThinkMode(str, Enum):
    FAST = "fast"
    DEEP = "deep"


# ─── Product Schemas ─────────────────────────────────────────
class ProductSpec(BaseModel):
    """Normalized product specs (flexible KV)"""
    key: str
    value: str


class Product(BaseModel):
    platform: Platform
    product_id: str
    title: str
    price: float
    original_price: Optional[float] = None
    discount_rate: Optional[float] = None
    store_name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    specs: Optional[Dict[str, Any]] = None
    sales: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    delivery: Optional[str] = None
    url: str
    images: Optional[List[str]] = []
    fetched_at: Optional[datetime] = None
    tags: Optional[List[str]] = []


class ProductSearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=100)
    platforms: Optional[List[Platform]] = [Platform.JD, Platform.TAOBAO, Platform.TMALL]
    category: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    sort_by: Optional[str] = "default"  # default | price_asc | price_desc | sales | rating
    page: int = 1
    page_size: int = 20


class ProductCompareRequest(BaseModel):
    product_ids: List[str] = Field(..., min_items=2, max_items=6)
    platform: Optional[Platform] = None


class ProductAggregateResult(BaseModel):
    keyword: str
    total: int
    products: List[Product]
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    avg_price: Optional[float] = None
    platform_distribution: Optional[Dict[str, int]] = None
    cheapest: Optional[Product] = None
    highest_rated: Optional[Product] = None


class PriceHistory(BaseModel):
    product_id: str
    platform: Platform
    prices: List[Dict[str, Any]]  # [{date, price}]


# ─── Creator / Video Review Schemas ──────────────────────────
class CreatorProfile(BaseModel):
    creator_id: str
    creator_name: str
    platform: VideoPlatform
    uid: Optional[str] = None
    avatar: Optional[str] = None
    domain: List[str] = []  # e.g. ["GPU", "CPU", "Laptop"]
    style_tags: List[str] = []  # e.g. ["benchmark", "thermals", "gaming"]
    credibility_score: float = Field(default=0.8, ge=0.0, le=1.0)
    follower_count: Optional[int] = None
    video_count: Optional[int] = None
    homepage_url: Optional[str] = None


class VideoReview(BaseModel):
    video_id: str
    platform: VideoPlatform
    title: str
    creator_name: str
    creator_id: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[int] = None  # seconds
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    coin_count: Optional[int] = None  # bilibili specific
    published_at: Optional[datetime] = None
    url: str
    tags: Optional[List[str]] = []
    description: Optional[str] = None
    # Structured review content (extracted from transcript)
    verdict: Optional[str] = None
    pros: Optional[List[str]] = []
    cons: Optional[List[str]] = []
    scenarios: Optional[List[str]] = []  # suitable use cases
    test_environment: Optional[str] = None
    evidence: Optional[List[str]] = []  # key data points
    related_products: Optional[List[str]] = []


class ReviewSearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=100)
    platforms: Optional[List[VideoPlatform]] = [VideoPlatform.BILIBILI, VideoPlatform.DOUYIN]
    domain: Optional[str] = None
    creator_whitelist_only: bool = True
    max_results: int = Field(default=10, le=50)


class ReviewAggregateResult(BaseModel):
    keyword: str
    total: int
    videos: List[VideoReview]
    creators: List[CreatorProfile]
    domain_summary: Optional[str] = None
    key_findings: Optional[List[str]] = []


# ─── Agent Schemas ────────────────────────────────────────────
class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    think_mode: ThinkMode = ThinkMode.FAST
    history: Optional[List[Dict[str, str]]] = []


class ToolCall(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    result_summary: Optional[str] = None
    duration_ms: Optional[int] = None


class AgentChatResponse(BaseModel):
    session_id: str
    message: str
    think_mode: ThinkMode
    products: Optional[List[Product]] = []
    reviews: Optional[List[VideoReview]] = []
    aggregate: Optional[ProductAggregateResult] = None
    tool_calls: Optional[List[ToolCall]] = []
    reasoning_steps: Optional[List[str]] = []
    response_time_ms: Optional[int] = None


# ─── Common ───────────────────────────────────────────────────
class APIResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    message: Optional[str] = None
    error: Optional[str] = None

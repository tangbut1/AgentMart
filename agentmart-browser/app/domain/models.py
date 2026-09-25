"""Unified product/price domain model (framework-independent dataclasses).

These types are the contract between adapters (ingestion), the pricing
engine, and the API layer. Money is always Decimal to avoid float drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .enums import (
    CommercialRelation,
    ConditionKind,
    CurationStatus,
    DataStatus,
    DiscountKind,
    DiscountLayer,
    Platform,
    PolicyCategory,
    PolicyScope,
    PriceCertainty,
    ReviewPlatform,
    ShopType,
)

ZERO = Decimal("0")


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


# ─── Discounts & price breakdown ──────────────────────────────

@dataclass
class Discount:
    """一项优惠/补贴。amount 为正数，表示可抵扣的金额。"""

    kind: DiscountKind
    label: str
    amount: Decimal = ZERO
    condition: str = ""
    condition_kind: ConditionKind = ConditionKind.UNCONDITIONAL
    # 同一 stack_group 内的优惠互斥，只取金额最高的一项（由数据源声明的规则决定）
    stack_group: Optional[str] = None
    # 归属层级。数据源没填时互斥判定退回 stack_group，两者都空则视为可叠加
    # （扩展侧 build_offer 一定会填，见 app/browser/extract.py）
    layer: Optional[DiscountLayer] = None
    # 页面文案对应的确定性档位。双轨净价靠它区分「公开轨」和「我的轨」，
    # 不再从 note 字符串里反解
    certainty: Optional[PriceCertainty] = None
    # 百分比折扣（与 amount 二选一）；percent 为 0-100 的数值
    percent: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    # 适用地区 / 资格 / 活动时间
    region_limit: Optional[str] = None
    eligibility: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    # 溯源
    source_url: Optional[str] = None
    verified_at: Optional[datetime] = None
    data_status: DataStatus = DataStatus.REAL
    note: Optional[str] = None

    @property
    def layer_key(self) -> str:
        """互斥判定用的池键。显式声明的 stack_group 优先于推断出的层级。"""
        if self.stack_group:
            return self.stack_group
        if self.layer is not None:
            return self.layer.value
        return ""

    @property
    def layer_label(self) -> str:
        if self.stack_group:
            return self.stack_group
        if self.layer is not None:
            return self.layer.label
        return "未分层"

    def resolved_amount(self, base: Decimal) -> Decimal:
        """按基础价计算实际抵扣额（处理百分比与封顶）。"""
        if self.percent is not None:
            value = base * _dec(self.percent) / Decimal(100)
            if self.max_amount is not None:
                value = min(value, _dec(self.max_amount))
            return value.quantize(Decimal("0.01"))
        return _dec(self.amount)


@dataclass
class PriceLine:
    """到手价拆解中的一行。"""

    label: str
    kind: DiscountKind
    amount: Decimal            # 正数=抵扣，负数=加价（如运费）
    condition_kind: ConditionKind
    condition: str = ""
    source_url: Optional[str] = None
    data_status: DataStatus = DataStatus.REAL


@dataclass
class PriceBreakdown:
    """可解释的到手价拆解。

    双轨净价（同一件商品、两个都站得住的数）：

    - ``public_total``   公开轨：只算「谁来看都成立」的抵扣。不登录、没有
                         任何账号权益也能拿到这个价。跨平台比价用这一轨，
                         否则拿别家的公开价比自己账号里的券，比出来的是
                         两个不同的东西。
    - ``account_total``  我的轨：再加上「页面显示本账号已可用」的抵扣。
                         只有在用户自己的浏览器里读页面才拿得到这个数。
    - ``potential_total`` 再计入「满足条件才成立」的抵扣 —— 需要用户自行
                         确认资格。
    - ``unverifiable_total`` 无法核实的抵扣，仅供参考，绝不计入上面任何一个。

    ``definite_total`` 保留为 ``account_total`` 的别名：老界面和老测试读的
    都是它，语义也没变（"用户现在就能拿到的价格"）。
    """

    list_price: Decimal
    shipping_fee: Decimal
    lines: List[PriceLine] = field(default_factory=list)
    definite_total: Decimal = ZERO
    potential_total: Decimal = ZERO
    unverifiable_total: Decimal = ZERO
    applied_groups: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    public_total: Decimal = ZERO
    account_total: Decimal = ZERO

    @property
    def definite_discount(self) -> Decimal:
        return (self.list_price + self.shipping_fee - self.definite_total).quantize(Decimal("0.01"))

    @property
    def potential_discount(self) -> Decimal:
        return (self.list_price + self.shipping_fee - self.potential_total).quantize(Decimal("0.01"))

    @property
    def public_discount(self) -> Decimal:
        return (self.list_price + self.shipping_fee - self.public_total).quantize(Decimal("0.01"))

    @property
    def account_gap(self) -> Decimal:
        """我的轨比公开轨便宜了多少 —— 也就是账号权益带来的那部分。

        这个数必须 ≥ 0：账号权益只会更便宜，不会更贵。真算出负数说明哪里
        把不该进公开轨的抵扣算进去了，调用方应当把它当错误而不是展示出来。
        """
        return (self.public_total - self.account_total).quantize(Decimal("0.01"))


# ─── Offer (a concrete listing on one platform) ───────────────

@dataclass
class Policy:
    scope: PolicyScope
    category: PolicyCategory
    title: str
    summary: str
    source_url: Optional[str] = None
    updated_at: Optional[datetime] = None
    region: Optional[str] = None
    data_status: DataStatus = DataStatus.REAL


@dataclass
class Offer:
    """某平台上的一个具体商品链接（SKU 级）。"""

    platform: Platform
    platform_product_id: str
    title: str
    url: str
    list_price: Decimal
    shop_name: Optional[str] = None
    shop_type: ShopType = ShopType.UNKNOWN
    shop_url: Optional[str] = None
    brand: Optional[str] = None
    sku_text: Optional[str] = None          # 原始规格描述（容量/颜色/配置）
    images: List[str] = field(default_factory=list)
    sales_text: Optional[str] = None
    shipping_fee: Decimal = ZERO
    region: Optional[str] = None
    discounts: List[Discount] = field(default_factory=list)
    policies: List[Policy] = field(default_factory=list)
    # 溯源与可信度
    data_status: DataStatus = DataStatus.REAL
    source: str = ""                         # 数据来源标识（如 jd_union_api）
    source_url: Optional[str] = None
    fetched_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    credibility: float = 0.5                 # 0-1 店铺/商品可靠程度
    # 匹配信息（由匹配层填充）
    match_confidence: Optional[float] = None
    match_notes: List[str] = field(default_factory=list)
    # SKU 规格同步：这一行的价格对应哪个规格，与组内基准是不是同一个 SKU。
    # sku_sync 取值 matched / variant / unknown，由 app/domain/matching.py 填。
    sku_spec: Optional[Any] = None
    sku_sync: str = "unknown"
    affiliate: bool = False                  # 是否联盟/返佣链接

    @property
    def id(self) -> str:
        return f"{self.platform.value}:{self.platform_product_id}"


# ─── Canonical product (cross-platform match group) ───────────

@dataclass
class CanonicalProduct:
    """跨平台匹配后的“同一款商品”组。"""

    id: str
    title: str
    brand: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    specs: dict = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    offers: List[Offer] = field(default_factory=list)
    confidence: float = 1.0
    warnings: List[str] = field(default_factory=list)
    # 组内规格是否统一：matched / mixed / unknown（由 matching 层填）。
    # mixed 时各行价格对应不同规格，横向对比不能直接比大小。
    sku_status: str = "unknown"

    @property
    def best_definite_price(self) -> Optional[Decimal]:
        # list_price 为 0 表示「没读到价格」，不是「免费」—— build_offer 抽不到
        # 价格时给的就是 0。这种条目一旦进 min()，界面会写出「最低确定价 0.00」，
        # 那是凭空造出来的数，必须先剔掉。与前端 grouping.ts 的 hasPrice 同规则。
        totals = [
            compute_price_breakdown(o).definite_total
            for o in self.offers
            if o.data_status != DataStatus.DEMO and o.list_price > 0
        ]
        return min(totals) if totals else None

    @property
    def best_public_price(self) -> Optional[Decimal]:
        """公开轨上的最低到手价。

        跨平台比价应该看这一轨：definite_total 里含"我账号里的券"，
        两个平台同样的商品，因为账号不同就能比出高下，那不是商品差异。
        过滤条件和 best_definite_price 完全一致（见那边的注释）。
        """
        totals = [
            compute_price_breakdown(o).public_total
            for o in self.offers
            if o.data_status != DataStatus.DEMO and o.list_price > 0
        ]
        return min(totals) if totals else None


# ─── Reviews ──────────────────────────────────────────────────

@dataclass
class Review:
    """一条经整理的评测。quotes 必须是创作者原话摘录。"""

    platform: ReviewPlatform
    external_id: str
    url: str
    title: str
    creator_name: str
    published_at: Optional[datetime] = None
    creator_id: Optional[str] = None
    creator_url: Optional[str] = None
    cover_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    # 整理内容（人工）
    model_tested: Optional[str] = None      # 评测涉及的具体型号
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    quotes: List[str] = field(default_factory=list)   # 原话引用
    test_evidence: List[str] = field(default_factory=list)  # 测试方法/数据点
    scenarios: List[str] = field(default_factory=list)      # 适用人群/场景
    commercial_relation: CommercialRelation = CommercialRelation.UNKNOWN
    curation_status: CurationStatus = CurationStatus.PENDING
    curated_by: Optional[str] = None
    curated_at: Optional[datetime] = None
    curator_notes: Optional[str] = None
    # 可选 AI 归纳（与人工整理分开存储、分开展示）
    ai_summary: Optional[str] = None
    ai_generated_at: Optional[datetime] = None
    # 溯源
    data_status: DataStatus = DataStatus.REAL
    fetched_at: Optional[datetime] = None
    related_models: List[str] = field(default_factory=list)
    relevance_note: Optional[str] = None

    @property
    def id(self) -> str:
        return f"{self.platform.value}:{self.external_id}"


# ─── Recommendation ───────────────────────────────────────────

@dataclass
class UserPreferences:
    budget_max: Optional[Decimal] = None
    priority: str = "balanced"     # price | service | balanced
    scenario: Optional[str] = None  # 使用场景自由文本
    region: Optional[str] = None


@dataclass
class RecommendationOption:
    offer_id: str
    platform: Platform
    pick_type: str                 # best_overall | cheapest | safest
    headline: str
    definite_total: Decimal
    potential_total: Decimal
    score: float
    evidence: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)


@dataclass
class Recommendation:
    canonical_id: str
    options: List[RecommendationOption] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    missing_data: List[str] = field(default_factory=list)
    generated_at: Optional[datetime] = None
    # 决策矩阵（见 app/domain/decision.py）。序列化后的 dict，
    # 前端按 rows/cells 直接渲染，不在前端重算任何分数。
    matrix: Dict[str, Any] = field(default_factory=dict)


# 延迟导入避免循环依赖
from .pricing import compute_price_breakdown  # noqa: E402

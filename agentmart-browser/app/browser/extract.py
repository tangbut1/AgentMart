"""把浏览器页面抽取结果转换为 domain 模型，并判定价格确定性。

核心规则（对应需求第九、三节）：
1. 页面公开标价只是标价，不是到手价；
2. 用户账号可见的券，只有页面本身显示它**适用于这个商品**时才记为
   ``ACCOUNT_COUPON``（可计入确定到手价）；
3. 只看到"有这张券"但看不清适用范围/叠加关系 → ``CONDITIONAL``，
   需要用户确认，并下调确定性；
4. 无法核实资格（国补、地区、以旧换新残值）→ ``UNVERIFIABLE``，
   只列示，不计入任何到手价；
5. 页面只给优惠后总价、无法分辨各项优惠时，不编造拆分明细。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from ..domain.enums import (
    ConditionKind,
    DataStatus,
    DiscountKind,
    Platform,
    PolicyCategory,
    PolicyScope,
    ShopType,
)
from ..domain.models import Discount, Offer, Policy
from .enums import DataOrigin, PriceCertainty

# ─── 金额解析 ────────────────────────────────────────────────────

_MONEY_RE = re.compile(r"([0-9][0-9，,]*(?:\.[0-9]{1,2})?)")
_CURRENCY_RE = re.compile(r"[¥￥$]")


def parse_money(text: Optional[str]) -> Optional[Decimal]:
    """从文本中解析金额。无法确定返回 None（不猜）。"""
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    # 去掉千分位
    cleaned = raw.replace(",", "").replace("，", "")
    # 取第一个带货币符号的数值；没有货币符号时取第一个数值
    match = re.search(r"[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)", cleaned)
    if not match:
        match = re.search(r"([0-9]+(?:\.[0-9]{1,2})?)", cleaned)
    if not match:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if value <= 0 or value > Decimal("100000000"):
        return None
    return value.quantize(Decimal("0.01"))


def looks_like_money(text: Optional[str]) -> bool:
    return parse_money(text) is not None


# ─── 优惠解释 ────────────────────────────────────────────────────

# 明确表示"已领取/已可用"的措辞 —— 必须优先于动作词判断，
# 因为"已领取"里含"领取"，不能当成"还需要去领"。
_CLAIMED_HINTS = ("已领取", "已领", "已获得", "已入手", "已享", "券后", "优惠后")
# 表示"已可用"的措辞
_AVAILABLE_HINTS = ("可用", "立减")
# 表示"需要操作/不确定"的措辞
_ACTION_HINTS = ("去领取", "立即领取", "点击领取", "待领取", "需领取", "去使用", "立即抢", "抢券")
# 表示"不确定/不可用"的措辞
_UNAVAILABLE_HINTS = ("已抢光", "已过期", "不可用", "已失效", "暂不可用")
# 补贴类关键词
_SUBSIDY_HINTS = ("国补", "国家补贴", "政府补贴", "以旧换新", "换新补贴", "平台补贴", "百亿补贴")
# 支付类关键词
_PAYMENT_HINTS = ("支付立减", "银行卡", "花呗", "白条", "微信支付", "支付宝", "分期免息")
# 门槛
_THRESHOLD_RE = re.compile(r"满\s*([0-9]+(?:\.[0-9]+)?)\s*(?:元)?\s*减\s*([0-9]+(?:\.[0-9]+)?)")
_OFF_RE = re.compile(r"(?:减|优惠|立减|券)\s*([0-9]+(?:\.[0-9]{1,2})?)\s*元")
_DISCOUNT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*折")


@dataclass
class CouponReading:
    """页面上一条优惠文案的解释结果。"""

    raw_text: str
    kind: DiscountKind
    amount: Optional[Decimal]
    percent: Optional[Decimal]
    threshold: Optional[Decimal]
    certainty: PriceCertainty
    reason: str


def interpret_coupon_text(text: str) -> Optional[CouponReading]:
    """解释一条优惠文案。看不懂就返回 None（不猜）。"""
    raw = (text or "").strip()
    if len(raw) < 3:
        return None

    lowered = raw
    threshold = None
    amount: Optional[Decimal] = None
    percent: Optional[Decimal] = None

    m = _THRESHOLD_RE.search(lowered)
    if m:
        threshold = Decimal(m.group(1))
        amount = Decimal(m.group(2))
    else:
        m = _OFF_RE.search(lowered)
        if m:
            amount = Decimal(m.group(1))
        else:
            m = _DISCOUNT_RE.search(lowered)
            if m:
                percent = Decimal(m.group(1))

    if amount is None and percent is None:
        # 补贴类文案常常只写比例或只写"有补贴"，没有可量化金额。
        # 仍然要把它列出来（用户需要知道有这回事），但明确标为无法核实。
        if any(h in lowered for h in _SUBSIDY_HINTS):
            return CouponReading(
                raw_text=raw, kind=DiscountKind.SUBSIDY, amount=None, percent=None,
                threshold=None, certainty=PriceCertainty.UNVERIFIABLE,
                reason="页面提到补贴但未给出可核实金额，资格需本人核实",
            )
        return None  # 文案里没有可量化金额，不当成优惠

    if any(h in lowered for h in _SUBSIDY_HINTS):
        kind = DiscountKind.SUBSIDY
    elif any(h in lowered for h in _PAYMENT_HINTS):
        kind = DiscountKind.PAYMENT
    else:
        kind = DiscountKind.COUPON

    if any(h in lowered for h in _UNAVAILABLE_HINTS):
        return CouponReading(
            raw_text=raw, kind=kind, amount=amount, percent=percent,
            threshold=threshold, certainty=PriceCertainty.UNVERIFIABLE,
            reason="页面显示该优惠当前不可用",
        )

    if any(h in lowered for h in _SUBSIDY_HINTS):
        # 补贴资格（地区/品类/售价门槛/是否已领取）几乎无法从页面确认
        return CouponReading(
            raw_text=raw, kind=kind, amount=amount, percent=percent,
            threshold=threshold, certainty=PriceCertainty.UNVERIFIABLE,
            reason="补贴资格需本人核实（地区/品类/售价门槛/是否已领取）",
        )

    if any(h in lowered for h in _CLAIMED_HINTS) or (
        any(h in lowered for h in _AVAILABLE_HINTS)
        and not any(h in lowered for h in _ACTION_HINTS)
    ):
        return CouponReading(
            raw_text=raw, kind=kind, amount=amount, percent=percent,
            threshold=threshold, certainty=PriceCertainty.ACCOUNT_COUPON,
            reason="页面显示该优惠已可用于当前商品",
        )

    return CouponReading(
        raw_text=raw, kind=kind, amount=amount, percent=percent,
        threshold=threshold, certainty=PriceCertainty.CONDITIONAL,
        reason="页面显示可领/需满足条件，适用范围与叠加关系待确认",
    )


# ─── 店铺类型 ────────────────────────────────────────────────────

def classify_shop(shop_name: Optional[str], self_operated_hint: bool) -> Tuple[ShopType, str]:
    """店铺类型只在页面明示时标注，否则 UNKNOWN。"""
    name = (shop_name or "").strip()
    if self_operated_hint or "自营" in name:
        return ShopType.SELF_OPERATED, "页面标注自营"
    if "官方旗舰店" in name or "官方旗舰" in name:
        return ShopType.OFFICIAL_FLAGSHIP, "店铺名含官方旗舰店"
    if "旗舰店" in name or "旗舰" in name:
        return ShopType.FLAGSHIP, "店铺名含旗舰店"
    if "专营店" in name or "授权" in name:
        return ShopType.AUTHORIZED, "店铺名含专营/授权"
    if name:
        return ShopType.THIRD_PARTY, "按普通店铺处理"
    return ShopType.UNKNOWN, "页面未显示店铺名称"


# ─── 政策 ────────────────────────────────────────────────────────

_POLICY_PATTERNS: List[Tuple[re.Pattern, PolicyCategory, PolicyScope]] = [
    (re.compile(r"7天|七天|无理由"), PolicyCategory.AFTER_SALES, PolicyScope.PRODUCT_PAGE_PROMISE),
    (re.compile(r"退换|退货|换货"), PolicyCategory.AFTER_SALES, PolicyScope.PRODUCT_PAGE_PROMISE),
    (re.compile(r"保修|质保|全国联保"), PolicyCategory.WARRANTY, PolicyScope.PRODUCT_PAGE_PROMISE),
    (re.compile(r"包邮|免运费|运费险"), PolicyCategory.SHIPPING, PolicyScope.PRODUCT_PAGE_PROMISE),
    (re.compile(r"正品|假一赔|官方质检"), PolicyCategory.AUTHENTICITY, PolicyScope.PRODUCT_PAGE_PROMISE),
    (re.compile(r"发票|开票"), PolicyCategory.INVOICE, PolicyScope.PRODUCT_PAGE_PROMISE),
    (re.compile(r"价保|价格保护"), PolicyCategory.PRICE_PROTECTION, PolicyScope.PRODUCT_PAGE_PROMISE),
]


def extract_policies(texts: List[str]) -> List[Policy]:
    seen = set()
    policies: List[Policy] = []
    for text in texts:
        for pattern, category, scope in _POLICY_PATTERNS:
            if pattern.search(text) and (category, text) not in seen:
                seen.add((category, text))
                policies.append(
                    Policy(
                        scope=scope,
                        category=category,
                        title=text[:40],
                        summary=text[:200],
                        data_status=DataStatus.REAL,
                    )
                )
                break
    return policies


# ─── Offer 构造 ──────────────────────────────────────────────────

@dataclass
class PageFields:
    """JS 抽取返回的原始字段。"""

    url: str
    title: Optional[str] = None
    price_text: Optional[str] = None
    # 价格来源：dom=页面文本字段；vision=截图识别（确定性更低，需标注）
    price_source: str = "dom"
    shop_name: Optional[str] = None
    self_operated_hint: bool = False
    sku_text: Optional[str] = None
    coupon_texts: List[str] = field(default_factory=list)
    policy_texts: List[str] = field(default_factory=list)
    sales_text: Optional[str] = None
    evidence: Dict[str, str] = field(default_factory=dict)
    fetched_at: Optional[datetime] = None

    @classmethod
    def from_js(cls, data: dict) -> "PageFields":
        return cls(
            url=str(data.get("url") or ""),
            title=data.get("title"),
            price_text=data.get("priceText"),
            price_source=str(data.get("priceSource") or "dom"),
            shop_name=data.get("shopName"),
            self_operated_hint=bool(data.get("selfOperatedHint")),
            sku_text=data.get("skuText"),
            coupon_texts=list(data.get("couponTexts") or []),
            policy_texts=list(data.get("policyTexts") or []),
            sales_text=data.get("salesText"),
            evidence=dict(data.get("evidence") or {}),
        )


def certainty_to_condition(certainty: PriceCertainty) -> ConditionKind:
    return {
        PriceCertainty.ACCOUNT_COUPON: ConditionKind.UNCONDITIONAL,
        PriceCertainty.CONDITIONAL: ConditionKind.CONDITIONAL,
        PriceCertainty.PREPAYMENT: ConditionKind.CONDITIONAL,
        PriceCertainty.PAGE_PUBLIC: ConditionKind.UNCONDITIONAL,
        PriceCertainty.UNVERIFIABLE: ConditionKind.UNVERIFIABLE,
    }[certainty]


# 优惠条件等级 → 价格确定性档位标签。写进 Discount.note，
# 供前端展示"这条优惠属于哪一档确定性"。
_CONDITION_TO_CERTAINTY_LABEL = {
    ConditionKind.UNCONDITIONAL: "账号可见可用券",
    ConditionKind.CONDITIONAL: "满足条件的预计价",
    ConditionKind.UNVERIFIABLE: "无法核实",
}


def certainty_label(condition: ConditionKind) -> str:
    return _CONDITION_TO_CERTAINTY_LABEL[condition]


def build_offer(
    platform: Platform,
    fields: PageFields,
    origin: DataOrigin,
    *,
    source_label: str,
    affiliate: bool = False,
) -> Tuple[Optional[Offer], List[str]]:
    """把页面字段转成 domain Offer。

    返回 (offer, problems)。problems 记录无法核实/缺失的字段，
    由调用方展示，不静默丢弃。
    """
    problems: List[str] = []
    list_price = parse_money(fields.price_text)
    if list_price is None:
        problems.append("未能从页面确定价格（无价格证据）")

    shop_type, shop_reason = classify_shop(fields.shop_name, fields.self_operated_hint)
    if shop_type is ShopType.UNKNOWN:
        problems.append("未能确认店铺类型")

    discounts: List[Discount] = []
    for text in fields.coupon_texts:
        reading = interpret_coupon_text(text)
        if reading is None:
            continue
        condition = certainty_to_condition(reading.certainty)
        reason = reading.reason
        # 门槛检查：已领取但商品价格没到门槛，本单就用不上，
        # 必须从"确定可用"下调为"满足条件才成立"。
        if (
            reading.threshold is not None
            and list_price is not None
            and list_price < reading.threshold
        ):
            condition = ConditionKind.CONDITIONAL
            reason = (
                f"该优惠需满 {reading.threshold} 元，本商品页面价 {list_price} 元未达门槛，"
                "本单不适用"
            )
        discounts.append(
            Discount(
                kind=reading.kind,
                label=f"{reading.raw_text[:40]}",
                amount=reading.amount or Decimal("0"),
                percent=reading.percent,
                condition=reason,
                condition_kind=condition,
                region_limit=None,
                eligibility=None,
                source_url=fields.url,
                data_status=DataStatus.REAL,
                note=f"确定性：{certainty_label(condition)}；原文：{reading.raw_text}",
            )
        )
        if reading.threshold is not None:
            discounts[-1].condition = (
                f"{reason}；门槛：满 {reading.threshold} 元"
            )

    policies = extract_policies(fields.policy_texts)

    product_id = _product_id_from_url(fields.url) or fields.url[-32:]
    # 价格来自截图识别、没有页面文本字段交叉核对时，数据状态降级为
    # 「待核实」：它仍然会被展示，但绝不被当成已核验的价格。
    data_status = DataStatus.REAL
    if fields.price_source == "vision":
        data_status = DataStatus.UNVERIFIED
        problems.append(
            f"价格 {list_price} 来自截图识别，未经页面文本字段交叉核对，"
            "已标记为待核实，请以平台结算页为准"
        )
    offer = Offer(
        platform=platform,
        platform_product_id=product_id,
        title=fields.title or fields.url,
        url=fields.url,
        list_price=list_price or Decimal("0"),
        shop_name=fields.shop_name,
        shop_type=shop_type,
        sku_text=fields.sku_text,
        sales_text=fields.sales_text,
        discounts=discounts,
        policies=policies,
        data_status=data_status,
        source=f"browser:{source_label}",
        source_url=fields.url,
        fetched_at=fields.fetched_at or datetime.now(),
        verified_at=None,
        credibility=_credibility(origin, shop_type, bool(fields.evidence)) - (
            0.1 if fields.price_source == "vision" else 0.0
        ),
        affiliate=affiliate,
    )
    if list_price is None:
        problems.append("该链接已记录，但价格缺失，不参与价格比较")
    return offer, problems


def _credibility(origin: DataOrigin, shop_type: ShopType, has_evidence: bool) -> float:
    score = 0.4
    if origin is DataOrigin.REAL_PLATFORM_PAGE:
        score += 0.25
    elif origin is DataOrigin.USER_PROVIDED:
        score += 0.15
    elif origin is DataOrigin.TEST_FIXTURE:
        score += 0.1
    if shop_type is not ShopType.UNKNOWN:
        score += 0.15
    if has_evidence:
        score += 0.1
    return min(1.0, round(score, 2))


def _product_id_from_url(url: str) -> Optional[str]:
    m = re.search(r"[?&]id=(\d{5,})", url)
    if m:
        return m.group(1)
    m = re.search(r"/item[/.]?(\d{5,})", url)
    if m:
        return m.group(1)
    m = re.search(r"(\d{10,})", url)
    if m:
        return m.group(1)
    return None


# ─── 金额一致性校验 ──────────────────────────────────────────────

def amounts_agree(
    dom_amount: Optional[Decimal],
    vision_amount: Optional[Decimal],
    tolerance: Decimal = Decimal("0.01"),
) -> Tuple[bool, str]:
    """视觉识别金额必须与 DOM 证据一致，否则拦截。

    返回 (是否一致, 说明)。任何一边缺失都视为不一致——不允许用视觉
    金额单独作为价格证据。
    """
    if dom_amount is None and vision_amount is None:
        return False, "DOM 与视觉都没有金额"
    if dom_amount is None:
        return False, "只有视觉金额、没有 DOM 证据，已拦截"
    if vision_amount is None:
        return True, "仅使用 DOM 证据金额"
    if abs(dom_amount - vision_amount) <= tolerance:
        return True, f"DOM 与视觉一致（{dom_amount}）"
    return False, (
        f"视觉金额 {vision_amount} 与页面证据 {dom_amount} 不一致，已拦截视觉结果"
    )

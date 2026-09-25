"""决策矩阵：把「买哪个平台」拆成用户能自己核对的几个维度。

为什么不直接给一个总分就完事：总分是个黑箱，用户没法验证，
也没法按自己的偏好重新权衡。矩阵把每个维度单独列出来 ——
公开轨到手价、我的轨到手价、店铺与售后、价格确定性、数据新鲜度、
规格是否一致 —— 每格都给值和一句解释，用户能自己改权重做决定。

两条硬规则：

1. **跨平台比价只比公开轨。** 我的轨里含「我这个账号已可用」的券，
   换个账号就没了。拿它给平台排名，排出来的是账号运气不是商品差异。
   账号券带来的差额单独一列明示，不并进排名分。

2. **规格不一致的报价不能当赢家。** 同款但不同尺码/容量，价格差里
   含规格差异。这种报价照常参与展示，但分数打折并写明原因 ——
   否则用户按矩阵下单会买到另一个规格。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .enums import DataStatus, DiscountKind, Platform, ShopType
from .models import Offer, PriceBreakdown
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

PRIORITY_LABELS: Dict[str, str] = {
    "price": "更看重价格",
    "service": "更看重售后",
    "balanced": "价格与售后平衡",
}

PLATFORM_AFTER_SALES_NOTE = {
    Platform.JD: "京东对自营商品提供平台级售后介入，退换货流程相对标准化",
    Platform.TAOBAO: "淘宝售后依赖店铺承诺与平台规则，下单前需确认店铺服务",
    Platform.TMALL: "天猫店铺受平台售后规则约束，官方旗舰店通常由品牌方履约",
    Platform.PDD: "拼多多部分商品支持平台介入售后，具体政策以商品页面为准",
    Platform.DOUYIN: "抖音电商售后以小店/直播间承诺为主，建议保留直播录屏等凭证",
}

_POLICY_CATEGORIES_STRONG = {"after_sales", "warranty", "authenticity"}

# 价格分按相对价差折算：与公开轨最低价相差 25% 以内线性衰减，超出记 0 分。
PRICE_GAP_THRESHOLD = Decimal("0.25")

# 规格不一致时的分数折损。0.5 足以让任何规格不符的报价排在规格相符的
# 报价之后（相符的报价价格分至少 0、服务分至少 0.4，加权后不会低于 0.4）。
SKU_VARIANT_PENALTY = 0.5

SKU_SYNC_LABELS: Dict[str, str] = {
    "matched": "规格一致",
    "variant": "规格不同",
    "unknown": "未读到规格",
}

TONE_OK = "ok"
TONE_WARN = "warn"
TONE_DANGER = "danger"
TONE_MUTED = "muted"


def is_fresh(offer: Offer, now: datetime) -> bool:
    if offer.data_status != DataStatus.REAL:
        return False
    fetched = offer.fetched_at or offer.verified_at
    if fetched is None:
        return False
    return now - fetched <= STALE_AFTER


def price_scores(breakdowns: Dict[str, PriceBreakdown]) -> Dict[str, float]:
    """按**公开轨**到手价归一化到 0-1（越便宜越高分）。

    刻意不用我的轨：那一轨含账号券，跨平台比它会比出账号差异。
    """
    totals = {oid: b.public_total for oid, b in breakdowns.items()}
    if not totals:
        return {}
    lo = min(totals.values())
    hi = max(totals.values())
    if hi == lo:
        return {oid: 1.0 for oid in totals}
    scores: Dict[str, float] = {}
    for oid, total in totals.items():
        gap = (total - lo) / lo if lo > 0 else Decimal(1)
        scores[oid] = float(max(Decimal(0), Decimal(1) - gap / PRICE_GAP_THRESHOLD))
    return scores


def service_score(offer: Offer) -> float:
    score = SHOP_SERVICE_SCORE.get(offer.shop_type, 0.4)
    strong = {
        p.category.value for p in offer.policies
        if p.data_status != DataStatus.DEMO
    } & _POLICY_CATEGORIES_STRONG
    if strong:
        score = min(1.0, score + 0.08 * len(strong))
    return score


def freshness_score(offer: Offer, now: datetime) -> float:
    if offer.data_status == DataStatus.REAL:
        return 1.0 if is_fresh(offer, now) else 0.5
    if offer.data_status == DataStatus.UNVERIFIED:
        return 0.3
    return 0.0


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _public_cell(breakdown: PriceBreakdown) -> Dict[str, str]:
    note = "只算谁来看都成立的抵扣；跨平台比价看这一列"
    if breakdown.shipping_fee:
        note += f"（含运费 {_money(breakdown.shipping_fee)} 元）"
    return {
        "key": "public_total",
        "label": "公开轨到手",
        "value": _money(breakdown.public_total),
        "note": note,
        "tone": TONE_MUTED,
    }


def _account_cell(breakdown: PriceBreakdown) -> Dict[str, str]:
    gap = breakdown.account_gap
    if gap > 0:
        note = (
            f"比公开轨低 {_money(gap)} 元，来自你账号下已显示可用的券；"
            "换个账号或未登录时拿不到"
        )
        tone = TONE_WARN
    else:
        note = "与公开轨相同：页面上没有你这个账号专属的可用抵扣"
        tone = TONE_MUTED
    return {
        "key": "account_total",
        "label": "我的轨到手",
        "value": _money(breakdown.account_total),
        "note": note,
        "tone": tone,
    }


def _service_cell(offer: Offer) -> Dict[str, str]:
    if offer.shop_type == ShopType.UNKNOWN or not offer.shop_name:
        note = "店铺类型未能核实，售后保障程度不确定"
        tone = TONE_WARN
    else:
        note = f"{offer.shop_name}（{offer.shop_type.label}）"
        tone = TONE_OK if offer.shop_type in (
            ShopType.SELF_OPERATED, ShopType.OFFICIAL_FLAGSHIP
        ) else TONE_WARN
    platform_note = PLATFORM_AFTER_SALES_NOTE.get(offer.platform)
    if platform_note:
        note = f"{note}；{platform_note}"
    return {
        "key": "service",
        "label": "店铺与售后",
        "value": offer.shop_type.label,
        "note": note,
        "tone": tone,
    }


def _freshness_cell(offer: Offer, now: datetime) -> Dict[str, str]:
    fetched = offer.fetched_at or offer.verified_at
    if offer.data_status != DataStatus.REAL:
        return {
            "key": "freshness",
            "label": "数据新鲜度",
            "value": offer.data_status.label,
            "note": "不是真实采集数据，仅供参考",
            "tone": TONE_DANGER,
        }
    if fetched is None:
        return {
            "key": "freshness",
            "label": "数据新鲜度",
            "value": "时间未知",
            "note": "没记录采集时间，无法判断是否过期",
            "tone": TONE_WARN,
        }
    if is_fresh(offer, now):
        return {
            "key": "freshness",
            "label": "数据新鲜度",
            "value": fetched.strftime("%m-%d %H:%M"),
            "note": "24 小时内采集，价格参考价值较高",
            "tone": TONE_OK,
        }
    return {
        "key": "freshness",
        "label": "数据新鲜度",
        "value": fetched.strftime("%m-%d %H:%M"),
        "note": "采集时间较早，下单前请以商品页面实时价格为准",
        "tone": TONE_WARN,
    }


def _sku_anchor(offers: List[Offer]) -> Optional[Any]:
    """组内基准规格：第一个读到了规格的报价。

    和 app/domain/matching.py 的 _fill_sku_sync 取同一个基准
    （组内第一个非空规格），这样矩阵和对比表对「谁是基准」的说法一致。
    """
    from .sku import parse_sku  # 延迟导入避免循环依赖

    for offer in offers:
        spec = offer.sku_spec or parse_sku(offer.sku_text)
        if not spec.is_empty:
            return spec
    return None


def _sku_cell(offer: Offer, anchor: Optional[Any]) -> Tuple[Dict[str, str], str]:
    """规格同步格，以及这一格对应的同步状态。

    自己解析 sku_text、自己和基准比，不依赖调用方先跑过 group_offers：
    矩阵要能对任意一组 Offer 独立成立，否则少接一步就全变成「未读到规格」。
    """
    from .sku import parse_sku, sku_relation  # 延迟导入避免循环依赖

    spec = offer.sku_spec or parse_sku(offer.sku_text)
    if anchor is None or spec.is_empty:
        sync = "unknown"
    else:
        sync = sku_relation(anchor, spec)
    described = spec.describe()

    if sync == "matched":
        value = described or "规格一致"
        note = "与组内基准同一个 SKU，价格可直接比"
        tone = TONE_OK
    elif sync == "variant":
        value = described or "规格不同"
        note = "与组内基准不是同一个 SKU，价格差里含规格差异，不能直接比大小"
        tone = TONE_DANGER
    else:
        value = "未读到规格"
        note = "页面上没读到规格信息，无法确认是不是同一个 SKU"
        tone = TONE_WARN
    cell = {
        "key": "sku_sync",
        "label": "规格同步",
        "value": value,
        "note": note,
        "tone": tone,
    }
    return cell, sync


def _score_cell(score: float, blocked: bool) -> Dict[str, str]:
    if blocked:
        return {
            "key": "score",
            "label": "综合分",
            "value": f"{score:.2f}",
            "note": "已按规格不一致折损，不参与赢家评选",
            "tone": TONE_DANGER,
        }
    return {
        "key": "score",
        "label": "综合分",
        "value": f"{score:.2f}",
        "note": "按当前权重加权：公开轨价格 + 店铺售后 + 数据新鲜度",
        "tone": TONE_MUTED,
    }


def build_matrix(
    offers: List[Offer],
    breakdowns: Dict[str, PriceBreakdown],
    priority: str,
    now: datetime,
) -> Dict[str, Any]:
    """生成决策矩阵。演示数据不进入矩阵。"""
    weights = PRIORITY_WEIGHTS.get(priority, PRIORITY_WEIGHTS["balanced"])
    real = [o for o in offers if o.data_status != DataStatus.DEMO]
    p_scores = price_scores(breakdowns)
    anchor = _sku_anchor(real)

    rows: List[Dict[str, Any]] = []
    for offer in real:
        b = breakdowns[offer.id]
        base = (
            weights["price"] * p_scores.get(offer.id, 0.0)
            + weights["service"] * service_score(offer)
            + weights["freshness"] * freshness_score(offer, now)
        )
        sku_cell, sku_sync = _sku_cell(offer, anchor)
        blocked = sku_cell["tone"] == TONE_DANGER
        score = base * SKU_VARIANT_PENALTY if blocked else base
        rows.append({
            "offer_id": offer.id,
            "platform": offer.platform.value,
            "platform_label": offer.platform.label,
            "shop_name": offer.shop_name,
            "shop_type_label": offer.shop_type.label,
            "url": offer.url,
            "sku_sync": sku_sync,
            "sku_sync_label": SKU_SYNC_LABELS.get(sku_sync, sku_sync),
            "blocked": blocked,
            "score": round(score, 3),
            "cells": [
                _public_cell(b),
                _account_cell(b),
                _service_cell(offer),
                _freshness_cell(offer, now),
                sku_cell,
                _score_cell(score, blocked),
            ],
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    notes: List[str] = [
        "跨平台比价只看「公开轨到手」——那一轨只算谁来看都成立的抵扣；"
        "「我的轨到手」含你账号下已显示可用的券，换个账号就没了，不并进综合分。",
    ]
    if any(row["blocked"] for row in rows):
        notes.append(
            "有报价与组内基准规格不一致，其价格差里含规格差异，已折损分数并标注，"
            "不参与赢家评选。"
        )
    if any(row["sku_sync"] == "unknown" for row in rows):
        notes.append(
            "有报价没读到规格信息，无法确认是不是同一个 SKU，请以两边商品页为准。"
        )

    return {
        "rows": rows,
        "weights": dict(weights),
        "priority": priority,
        "priority_label": PRIORITY_LABELS.get(priority, priority),
        "notes": notes,
    }


def cheapest_on_public_track(
    offers: List[Offer], breakdowns: Dict[str, PriceBreakdown]
) -> Optional[Offer]:
    """公开轨上最便宜的真实报价。比价用这个，不用我的轨。"""
    candidates = [
        o for o in offers
        if o.data_status != DataStatus.DEMO and o.list_price > 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda o: breakdowns[o.id].public_total)

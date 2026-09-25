"""规格匹配测试：核心是「不错配」。"""
from __future__ import annotations

from app.domain.enums import Platform
from app.domain.matching import (
    extract_signature,
    group_offers,
    hard_conflict,
    match_score,
)
from app.domain.models import CanonicalProduct, Offer


def _offer(title: str, pid: str = "1") -> Offer:
    return Offer(
        platform=Platform.JD, platform_product_id=pid, title=title,
        url=f"https://item.example.com/{pid}", list_price=100,
    )


def test_extract_storage_and_model():
    sig = extract_signature("Apple iPhone 15 Pro 256GB 黑色钛金属 国行")
    assert sig.storage == "256GB"
    assert "IPHONE15" in sig.model_tokens or any("15" in t for t in sig.model_tokens)
    assert sig.version == "cn"
    assert sig.brand == "Apple"


def test_extract_ram_plus_storage_takes_largest():
    sig = extract_signature("某手机 16GB+512GB 全网通")
    assert sig.storage == "512GB"


def test_extract_condition_and_bundle():
    sig = extract_signature("索尼 WH-1000XM5 耳机 二手 95新 套装")
    assert sig.condition == "used"
    assert sig.bundle is True


def test_hard_conflict_storage():
    a = extract_signature("iPhone 15 128GB")
    b = extract_signature("iPhone 15 256GB")
    assert hard_conflict(a, b) is not None
    assert match_score(a, b)[0] == 0.0


def test_hard_conflict_version():
    a = extract_signature("iPhone 15 国行")
    b = extract_signature("iPhone 15 美版")
    assert hard_conflict(a, b) is not None


def test_hard_conflict_condition():
    a = extract_signature("iPhone 15 全新")
    b = extract_signature("iPhone 15 二手")
    assert hard_conflict(a, b) is not None


def test_no_conflict_same_model():
    a = extract_signature("索尼 WH-1000XM5 黑色 国行")
    b = extract_signature("Sony WH-1000XM5 头戴式降噪耳机 官方旗舰店")
    assert hard_conflict(a, b) is None
    score, reasons = match_score(a, b)
    assert score >= 0.45
    assert any("型号" in r for r in reasons)


def test_color_difference_is_soft():
    a = extract_signature("iPhone 15 黑色 128GB")
    b = extract_signature("iPhone 15 白色 128GB")
    score, reasons = match_score(a, b)
    assert score > 0
    assert any("颜色" in r for r in reasons)


def test_group_offers_separates_storage():
    offers = [
        _offer("Apple iPhone 15 128GB 黑色", "a"),
        _offer("Apple iPhone 15 256GB 黑色", "b"),
        _offer("Apple iPhone 15 128GB 白色", "c"),
    ]
    groups = group_offers(offers)
    # 128GB 的两个合组，256GB 单独一组
    assert len(groups) == 2
    sizes = sorted(len(g.offers) for g in groups)
    assert sizes == [1, 2]


def test_group_offers_warns_on_color_mix():
    offers = [
        _offer("索尼 WH-1000XM5 黑色", "a"),
        _offer("索尼 WH-1000XM5 白色", "b"),
    ]
    groups = group_offers(offers)
    assert len(groups) == 1
    assert any("颜色" in w for w in groups[0].warnings)


def test_different_brands_never_merge():
    offers = [
        _offer("索尼 WH-1000XM5 耳机", "a"),
        _offer("Bose QC45 耳机", "b"),
    ]
    groups = group_offers(offers)
    assert len(groups) == 2


def test_best_definite_price_ignores_missing_price():
    """没读到价格的条目 list_price 是 0，不是「免费」。

    它一旦参与 min()，界面会写出「最低确定价 0.00」—— 那是凭空造出来的数。
    """
    cluster = CanonicalProduct(
        id="g1",
        title="Apple iPhone 15 Pro",
        offers=[
            _offer("Apple iPhone 15 Pro 256GB", "a"),
            _offer("Apple iPhone 15 Pro 256GB", "b"),
        ],
    )
    cluster.offers[0].list_price = 2499
    cluster.offers[1].list_price = 0  # 没抽到价格
    assert cluster.best_definite_price == cluster.offers[0].list_price


def test_best_definite_price_is_none_when_all_missing():
    cluster = CanonicalProduct(
        id="g2",
        title="Apple iPhone 15 Pro",
        offers=[_offer("Apple iPhone 15 Pro 256GB", "a")],
    )
    cluster.offers[0].list_price = 0
    assert cluster.best_definite_price is None

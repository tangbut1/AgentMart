"""SKU 级规格同步测试：价格必须对应同一个 SKU，否则不能比。

核心场景：很多平台把颜色/尺码只放在规格选择器里，标题里不写。
「冲锋衣 TAWJ91719」在两个平台标题一样，但一个选的是黑色 L、
一个是蓝色 M —— 旧逻辑只解析标题，两边签名都没有尺码，
于是合成一组、并排比价，把 200 元的差价算成了平台差异。
"""
from __future__ import annotations

from app.domain.enums import Platform
from app.domain.matching import extract_signature, group_offers
from app.domain.models import Offer
from app.domain.sku import parse_sku, sku_relation


def _offer(title: str, sku: str, pid: str, price: int) -> Offer:
    return Offer(
        platform=Platform.JD,
        platform_product_id=pid,
        title=title,
        url=f"https://item.example.com/{pid}",
        list_price=price,
        sku_text=sku,
    )


def test_sku_only_size_difference_is_not_the_same_sku():
    """标题相同、尺码只在规格里：不能当成同一个 SKU 比价。"""
    a = _offer("冲锋衣 TAWJ91719 三合一", "黑色 L", "a", 1299)
    b = _offer("冲锋衣 TAWJ91719 三合一", "蓝色 M", "b", 1099)

    groups = group_offers([a, b])
    # 尺码不同是硬冲突：必须分成两组，而不是合成一个 200 元价差的对比表
    assert len(groups) == 2, "尺码只在规格里时也必须是硬冲突"


def test_same_sku_after_normalization_stays_together():
    """同一 SKU 的不同写法（L码 / L、曜石黑 / 黑）必须归到一组。"""
    a = _offer("冲锋衣 TAWJ91719 三合一", "曜石黑 L码", "a", 1299)
    b = _offer("冲锋衣 TAWJ91719 三合一", "黑色 L", "b", 1299)

    groups = group_offers([a, b])
    assert len(groups) == 1, "归一后同一个 SKU，不该被拆开"
    assert groups[0].offers[0].sku_sync == "matched"


def test_storage_only_in_sku_is_a_hard_conflict():
    a = _offer("某品牌 手机 Pro", "256GB 黑色", "a", 3999)
    b = _offer("某品牌 手机 Pro", "512GB 黑色", "b", 4599)

    groups = group_offers([a, b])
    assert len(groups) == 2, "容量不同是硬冲突，标题没写也一样"


def test_missing_sku_is_unknown_not_matched():
    """读不到规格时说「未读到」，不能假装一致。"""
    a = _offer("冲锋衣 TAWJ91719 三合一", "黑色 L", "a", 1299)
    b = _offer("冲锋衣 TAWJ91719 三合一", "", "b", 1299)

    groups = group_offers([a, b])
    assert len(groups) == 1, "读不到规格不构成冲突，仍然同款"
    statuses = {o.platform_product_id: o.sku_sync for o in groups[0].offers}
    assert statuses["a"] == "matched"
    assert statuses["b"] == "unknown"


def test_parse_sku_normalizes_color_and_size():
    spec = parse_sku("曜石黑 L码 2024款")
    assert spec.color == "黑"
    assert spec.size == "L"

    spec2 = parse_sku("月光白 42码")
    assert spec2.color == "白"
    assert spec2.size == "42"


def test_parse_sku_reads_storage_version_condition():
    spec = parse_sku("深空灰 256GB 国行 全新")
    assert spec.color == "灰"
    assert spec.storage == "256GB"
    assert spec.version == "cn"
    assert spec.condition == "new"


def test_sku_relation_reports_the_difference():
    a = parse_sku("黑色 L")
    b = parse_sku("蓝色 M")
    assert sku_relation(a, b) == "variant"

    same = parse_sku("黑色 L")
    assert sku_relation(a, same) == "matched"

    empty = parse_sku("")
    assert sku_relation(a, empty) == "unknown"
    assert sku_relation(empty, a) == "unknown"


def test_signature_merges_sku_size():
    """规格里的尺码要进签名，成为硬冲突判定依据。"""
    sig = extract_signature("冲锋衣 TAWJ91719", sku_text="黑色 L")
    assert sig.sizes == {"L"}
    sig2 = extract_signature("冲锋衣 TAWJ91719", sku_text="蓝色 M")
    assert sig2.sizes == {"M"}

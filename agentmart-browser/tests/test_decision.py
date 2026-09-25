"""决策矩阵测试：比价要站在同一个口径上，标签要前后端一致。

两个前提来自阶段二的结论：
1. 跨平台比价只能比公开轨 —— 我的账号券换个账号就没了，
   拿它给平台排名次，排出来的是「我这个账号的运气」而不是商品差异；
2. 前后端对同一个 pick_type 必须用同一个词，否则界面会把英文原值
   直接怼给用户看。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.domain.enums import (
    ConditionKind,
    DataStatus,
    DiscountKind,
    DiscountLayer,
    Platform,
    PriceCertainty,
    ShopType,
)
from app.domain.models import CanonicalProduct, Discount
from app.domain.recommendation import recommend

from .conftest import make_offer

NOW = datetime(2026, 1, 15, 12, 0, 0)


def _group(offers) -> CanonicalProduct:
    return CanonicalProduct(id="cp_test", title="测试商品", offers=offers)


def _account_coupon(amount: str) -> Discount:
    return Discount(
        kind=DiscountKind.COUPON,
        label=f"店铺券 已领取 可用 {amount}",
        amount=Decimal(amount),
        condition_kind=ConditionKind.UNCONDITIONAL,
        certainty=PriceCertainty.ACCOUNT_COUPON,
        layer=DiscountLayer.SHOP,
    )


def test_safest_pick_type_matches_frontend_label():
    """后端发的 pick_type 必须是前端认识的那个词。

    前端 BrowserRecommendation 只认 best_overall / cheapest /
    safest_service；后端以前发 "safest"，标签映射落空，
    界面上直接显示英文 "safest"。

    三个报价才能走到 safest 分支：最便宜的是第三方店、服务最好的是自营、
    且自营不是最便宜 —— 否则 safest 会和另外两个选项重复而被跳过。
    """
    cheapest = make_offer(platform=Platform.TAOBAO, product_id="cheap", price="2500",
                          shop_type=ShopType.THIRD_PARTY)
    safest = make_offer(platform=Platform.JD, product_id="safest", price="3000",
                        shop_type=ShopType.SELF_OPERATED)
    middle = make_offer(platform=Platform.PDD, product_id="middle", price="2800",
                        shop_type=ShopType.THIRD_PARTY)
    rec = recommend(_group([cheapest, safest, middle]), [], now=NOW)
    pick_types = {o.pick_type for o in rec.options}
    assert "safest_service" in pick_types, f"safest 分支没触发：{pick_types}"
    assert pick_types <= {"best_overall", "cheapest", "safest_service"}, (
        f"前端不认识的 pick_type：{pick_types}"
    )


def test_price_ranking_uses_public_track_not_account_coupons():
    """账号券不能改变跨平台的便宜排名。

    A 平台公开价 1299，但我有 120 的券（我的轨 1179）；
    B 平台公开价 1199，没券。按「谁来看都成立的价」排，B 更便宜。
    以前用我的轨排，A 会赢 —— 那是我的券在赢，不是平台在赢。
    """
    from app.domain.decision import cheapest_on_public_track
    from app.domain.pricing import compute_price_breakdown

    a = make_offer(platform=Platform.JD, product_id="a", price="1299",
                   shop_type=ShopType.THIRD_PARTY, discounts=[_account_coupon("120")])
    b = make_offer(platform=Platform.PDD, product_id="b", price="1199",
                   shop_type=ShopType.THIRD_PARTY)
    breakdowns = {o.id: compute_price_breakdown(o) for o in (a, b)}
    assert breakdowns[a.id].account_total == Decimal("1179.00")
    assert cheapest_on_public_track([a, b], breakdowns).id == b.id


def test_account_gap_is_disclosed_not_hidden():
    """我的轨便宜了多少要明说，不能只拿来偷偷改排名。"""
    a = make_offer(platform=Platform.JD, product_id="a", price="1299",
                   shop_type=ShopType.THIRD_PARTY, discounts=[_account_coupon("120")])
    b = make_offer(platform=Platform.PDD, product_id="b", price="1199",
                   shop_type=ShopType.THIRD_PARTY)
    rec = recommend(_group([a, b]), [], now=NOW)
    option_a = next(o for o in rec.options if o.offer_id == a.id)
    text = " ".join(option_a.evidence + option_a.conditions)
    assert "120" in text, "账号券带来的差价必须写在证据里"
    assert "公开轨" in text and "我的轨" in text, "两个轨都要写，只写一个会误导"
    assert "换个账号" in text, "要说明这个便宜是有条件的"


def test_matrix_has_one_row_per_real_offer_with_both_tracks():
    """矩阵每个真实报价一行，且公开轨/我的轨都要有。"""
    a = make_offer(platform=Platform.JD, product_id="a", price="1299",
                   shop_type=ShopType.SELF_OPERATED)
    b = make_offer(platform=Platform.PDD, product_id="b", price="1199",
                   shop_type=ShopType.THIRD_PARTY)
    demo = make_offer(platform=Platform.DOUYIN, product_id="demo", price="999",
                      data_status=DataStatus.DEMO)
    rec = recommend(_group([a, b, demo]), [], now=NOW)

    rows = {row["offer_id"]: row for row in rec.matrix["rows"]}
    assert set(rows) == {a.id, b.id}, "演示数据不能进矩阵"

    keys = {"public_total", "account_total", "service", "freshness", "sku_sync", "score"}
    for row in rows.values():
        cell_keys = {cell["key"] for cell in row["cells"]}
        assert keys <= cell_keys, f"缺列：{keys - cell_keys}"
        assert isinstance(row["score"], float)
        assert row["rank"] >= 1


def test_matrix_weights_follow_user_priority():
    """用户选了「更看重价格」时，权重里价格项必须最大。"""
    a = make_offer(platform=Platform.JD, product_id="a", price="1299",
                   shop_type=ShopType.SELF_OPERATED)
    b = make_offer(platform=Platform.PDD, product_id="b", price="1199",
                   shop_type=ShopType.THIRD_PARTY)
    from app.domain.models import UserPreferences

    rec = recommend(_group([a, b]), [], now=NOW,
                    prefs=UserPreferences(priority="price"))
    weights = rec.matrix["weights"]
    assert weights["price"] == max(weights.values()), weights


def test_sku_variant_offer_cannot_win_the_matrix():
    """规格不一致的报价不能当赢家。

    A 是同款同规格 1299；B 是同款但另一个尺码 1099。
    B 更便宜但规格不同，矩阵里它不能排第一 —— 否则用户按矩阵下单
    会买到另一个规格。
    """
    a = make_offer(platform=Platform.JD, product_id="a", price="1299",
                   shop_type=ShopType.SELF_OPERATED, title="冲锋衣 TAWJ91719 三合一")
    b = make_offer(platform=Platform.PDD, product_id="b", price="1099",
                   shop_type=ShopType.SELF_OPERATED, title="冲锋衣 TAWJ91719 三合一")
    a.sku_text, b.sku_text = "黑色 L", "蓝色 M"

    # 尺码不同本就不能合组；这里强制同组，考察矩阵自身的防护
    group = CanonicalProduct(id="cp_test", title="冲锋衣 TAWJ91719 三合一",
                             offers=[a, b], confidence=1.0)
    rec = recommend(group, [], now=NOW)
    rows = {row["offer_id"]: row for row in rec.matrix["rows"]}
    assert rows[b.id]["blocked"] is True, "规格不符的报价要被标出来"
    assert rows[a.id]["blocked"] is False
    winner = max(rec.matrix["rows"], key=lambda r: r["score"])
    assert winner["offer_id"] == a.id, (
        "规格不一致的报价不该是矩阵赢家"
    )
    # 首选也不能是规格不符的那个
    best = next(o for o in rec.options if o.pick_type == "best_overall")
    assert best.offer_id == a.id

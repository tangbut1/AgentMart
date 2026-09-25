"""商品链接/分享口令解析。

这一层全部是确定性字符串处理：认得出平台就认，认不出就如实返回问题。
它不能猜 —— 猜错平台会把用户带到别的网站，那比"解析失败"严重得多。
"""
from __future__ import annotations

import pytest

from app.browser.itemlinks import (
    LinkParse,
    group_links_by_platform,
    normalize_url,
    parse_user_input,
    platform_for_url,
    summarize,
)
from app.domain.enums import Platform


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://item.jd.com/100012043978.html", Platform.JD),
        ("https://item.m.jd.com/product/100012043978.html", Platform.JD),
        ("https://3.cn/1-AbCdEf", Platform.JD),
        ("https://item.taobao.com/item.htm?id=123", Platform.TAOBAO),
        ("https://m.tb.cn/h.abc123", Platform.TAOBAO),
        ("https://e.tb.cn/abc123", Platform.TAOBAO),
        ("https://detail.tmall.com/item.htm?id=123", Platform.TMALL),
        ("https://mobile.yangkeduo.com/goods.html?goods_id=1", Platform.PDD),
        ("https://www.pinduoduo.com/goods.html", Platform.PDD),
        ("https://haohuo.jinritemai.com/views/product/item?id=1", Platform.DOUYIN),
        ("https://www.douyin.com/product/123", Platform.DOUYIN),
        ("https://www.example.com/item/1", None),
        ("not a url at all", None),
        ("", None),
    ],
)
def test_platform_for_url(url, expected):
    assert platform_for_url(url) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        # 跟踪参数去掉，商品标识参数留下
        (
            "https://item.jd.com/100012043978.html?utm_source=qq&spm=a1z",
            "https://item.jd.com/100012043978.html",
        ),
        (
            "https://detail.tmall.com/item.htm?id=123&scene=taobao_shop",
            "https://detail.tmall.com/item.htm?id=123",
        ),
        # 认不出的参数保守保留：删错了页面就打不开
        (
            "https://item.taobao.com/item.htm?id=1&skuId=2",
            "https://item.taobao.com/item.htm?id=1&skuId=2",
        ),
        # fragment 一律去掉
        ("https://item.jd.com/1.html#anchor", "https://item.jd.com/1.html"),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


def test_single_bare_link():
    (parsed,) = parse_user_input("https://item.jd.com/100012043978.html")
    assert parsed.ok
    assert parsed.platform is Platform.JD
    assert parsed.url == "https://item.jd.com/100012043978.html"
    assert parsed.problem is None


def test_taobao_share_token_with_link():
    """一整段淘口令：口令码 + 描述 + m.tb.cn 短链。"""
    raw = (
        "¥aB3xK9z¥ 【索尼 WH-1000XM5】头戴式降噪耳机 黑色 "
        "https://m.tb.cn/h.abc123 点击链接直接打开"
    )
    (parsed,) = parse_user_input(raw)
    assert parsed.ok
    assert parsed.platform is Platform.TAOBAO
    assert parsed.url == "https://m.tb.cn/h.abc123"


def test_multiple_links_grouped_by_platform():
    raw = (
        "京东 https://item.jd.com/1.html\n"
        "淘宝 https://item.taobao.com/item.htm?id=2\n"
        "天猫 https://detail.tmall.com/item.htm?id=3\n"
        "拼多多 https://mobile.yangkeduo.com/goods.html?goods_id=4\n"
    )
    grouped = group_links_by_platform(parse_user_input(raw))
    assert set(grouped) == {Platform.JD, Platform.TAOBAO, Platform.TMALL, Platform.PDD}
    assert grouped[Platform.JD] == ["https://item.jd.com/1.html"]


def test_duplicate_links_are_deduplicated():
    raw = (
        "https://item.jd.com/1.html?utm_source=a "
        "https://item.jd.com/1.html?utm_source=b"
    )
    (parsed,) = parse_user_input(raw)
    assert parsed.url == "https://item.jd.com/1.html"
    assert len(parse_user_input(raw)) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://www.jd.com",
        "https://www.taobao.com",
        "https://detail.tmall.com",
        "https://login.taobao.com/member/login.jhtml",
        "https://cart.taobao.com/cart.htm",
        "https://trade.taobao.com/trade/itemlist/list_bought_items.htm",
    ],
)
def test_non_item_pages_are_flagged(url):
    """首页/登录页/购物车收进来也抽不到商品，要当场说清楚。"""
    (parsed,) = parse_user_input(url)
    assert not parsed.ok
    assert parsed.problem and "不是商品详情页" in parsed.problem


def test_unknown_platform_is_flagged_not_guessed():
    (parsed,) = parse_user_input("https://www.example.com/item/1")
    assert not parsed.ok
    assert parsed.problem and "认不出" in parsed.problem


def test_token_only_input_explains_what_is_missing():
    """只有口令码、没有链接：说明缺什么，而不是当垃圾丢掉。"""
    (parsed,) = parse_user_input("¥aB3xK9z¥ 索尼耳机")
    assert not parsed.ok
    assert parsed.token_only
    assert parsed.problem and "复制链接" in parsed.problem


def test_text_without_any_link():
    (parsed,) = parse_user_input("我想买一个耳机")
    assert not parsed.ok
    assert parsed.problem and "没有" in parsed.problem


def test_empty_input():
    assert parse_user_input("") == []
    assert parse_user_input("   ") == []


def test_summarize_reports_counts_and_problems():
    raw = "https://item.jd.com/1.html https://www.jd.com"
    data = summarize(parse_user_input(raw))
    assert data["total"] == 2
    assert data["usable"] == 1
    assert data["by_platform"] == {"jd": 1}
    assert len(data["problems"]) == 1
    assert data["links"] == [{"url": "https://item.jd.com/1.html", "platform": "jd"}]


def test_summarize_of_empty():
    assert summarize([]) == {
        "total": 0,
        "usable": 0,
        "by_platform": {},
        "problems": [],
        "links": [],
    }


def test_link_parse_ok_requires_all_three():
    """ok 的定义：有 url、有平台、没有问题。缺一不可。"""
    assert LinkParse(raw="x").ok is False
    assert LinkParse(raw="x", url="https://item.jd.com/1.html").ok is False
    assert (
        LinkParse(raw="x", url="https://item.jd.com/1.html", platform=Platform.JD).ok
        is True
    )
    assert (
        LinkParse(
            raw="x",
            url="https://item.jd.com/1.html",
            platform=Platform.JD,
            problem="坏了",
        ).ok
        is False
    )

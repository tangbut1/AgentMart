"""需求解析：预算区间与结构化填表。

用户实测踩到的坑（原样复现）：「预算100到250之间的西装」被解析成
关键词 ``到250之间 西装``、预算 ``max=100`` —— 于是浏览器拿着一个错得
离谱的关键词去搜，用户看到的就是"没有按照我的需要进行搜索评判"。

根因有两条，都在这里钉住：
1. ``_BUDGET_RANGE_RE`` 原来强制要求第二个数字后面写"元/块"，
   而口语里"100到250之间"根本不写第二个"元"，整段就掉到
   ``_BUDGET_PREFIX_RE`` 只认出 100；
2. "之间"不在填充词表里，识别失败后它又残留在搜索词中。

后半部分覆盖结构化填表：表单里填的数字就是最终数字，
不允许被"解析"改掉，也不允许悄悄拼凑。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.browser.agent import build_requirement, parse_requirement


# ---- 预算区间：各种口语写法都必须认对 ----

@pytest.mark.parametrize(
    "text,expected",
    [
        # 用户原话：不带第二个"元"，靠"之间"收尾
        ("预算100到250之间的西装", ("西装", Decimal(100), Decimal(250))),
        ("预算100-250之间的西装", ("西装", Decimal(100), Decimal(250))),
        ("预算在100到250之间的西装", ("西装", Decimal(100), Decimal(250))),
        ("预算 100 ~ 250 之间的西装", ("西装", Decimal(100), Decimal(250))),
        # 带了单位的原有写法不能被改坏
        ("100到250元的西装", ("西装", Decimal(100), Decimal(250))),
        ("100 到 250 元 西装", ("西装", Decimal(100), Decimal(250))),
        ("预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣",
         ("冲锋衣", Decimal(500), Decimal(800))),
        # 话没写完、停在数字上，带了"预算"也该认
        ("预算100到250", (None, Decimal(100), Decimal(250))),
        ("预算100到250，想要降噪耳机", ("降噪耳机", Decimal(100), Decimal(250))),
        # 只有上限 / 约数的原有写法
        ("预算 2500 的降噪耳机", ("降噪耳机", None, Decimal(2500))),
        ("预算800以内的洗衣机", ("洗衣机", None, Decimal(800))),
    ],
)
def test_budget_range_is_parsed(text, expected):
    keyword, low, high = expected
    r = parse_requirement(text)
    assert (r.budget_min, r.budget_max) == (low, high)
    if keyword is not None:
        assert r.keyword == keyword


def test_user_reported_sentence_now_parses_correctly():
    """用户原话的完整断言：搜索词干净，区间完整，不再是 max=100。"""
    r = parse_requirement("预算100到250之间的西装")
    assert r.keyword == "西装"
    assert r.budget_min == Decimal(100)
    assert r.budget_max == Decimal(250)
    # "到250之间"这类残渣不能再出现在搜索词里
    assert "到" not in r.keyword
    assert "250" not in r.keyword
    assert "之间" not in r.keyword


@pytest.mark.parametrize(
    "text",
    [
        "买10到20件T恤",          # 数量，不是价格
        "10年以内的笔记本电脑",    # 时长
        "iPhone 15-16 手机",     # 型号
        "出差15-20天的行李箱",    # 时长
        "WH-1000XM5",
    ],
)
def test_quantities_and_models_are_not_budgets(text):
    """没带"预算"字样时，不能把数量/型号/时长当成价格区间。"""
    r = parse_requirement(text)
    assert r.budget_min is None
    assert r.budget_max is None


def test_approximate_budget_is_flagged():
    r = parse_requirement("想买一部手机，预算 3000 元左右，重视续航和信号")
    assert r.budget_max == Decimal(3000)
    assert r.budget_approximate is True


# ---- 结构化填表：表单优先于自然语言 ----

def test_form_fields_alone_build_a_requirement():
    """纯填表、不写一句话，也要能构造出完整需求。"""
    r = build_requirement(
        "",
        {"keyword": "西装", "category": "服装", "budget_min": 100, "budget_max": 250},
    )
    assert r.keyword == "西装"
    assert r.category == "服装"
    assert r.budget_min == Decimal(100)
    assert r.budget_max == Decimal(250)
    # 界面回显用的一句话要能读
    assert "西装" in r.text
    assert "100" in r.text and "250" in r.text


def test_form_overrides_parsed_values():
    """表单填了就听表单的：即使原话被解析成别的数字。"""
    r = build_requirement(
        "预算100到250之间的西装", {"keyword": "西装", "budget_min": 300, "budget_max": 900}
    )
    assert (r.budget_min, r.budget_max) == (Decimal(300), Decimal(900))
    assert r.keyword == "西装"


def test_untouched_budget_keeps_parsed_value():
    """没碰预算就保留从原话里解析出来的，不强行清空。"""
    r = build_requirement("预算100到250之间的西装", {"keyword": "西装"})
    assert (r.budget_min, r.budget_max) == (Decimal(100), Decimal(250))


def test_form_only_max_means_not_exceeding():
    r = build_requirement("", {"keyword": "降噪耳机", "budget_max": 2500})
    assert r.budget_min is None
    assert r.budget_max == Decimal(2500)
    assert "不超过" in r.text


def test_brands_scenarios_region_come_from_form():
    r = build_requirement(
        "",
        {
            "keyword": "手机",
            "budget_max": 3000,
            "budget_approximate": True,
            "brands": "华为，小米",
            "region": "广东省深圳市",
            "scenarios": ["通勤", "续航"],
        },
    )
    assert r.brands == ["华为", "小米"]
    assert r.region == "广东省深圳市"
    assert r.scenarios == ["通勤", "续航"]
    assert r.budget_approximate is True


def test_form_suppresses_category_followup():
    """已经在表单里说清楚品类/商品时，不该再弹"未能确定品类"。"""
    r = build_requirement("", {"keyword": "西装"})
    assert r.unclear == []
    # 但什么都没填的时候，老路径的追问要保留
    assert parse_requirement("随便看看").unclear


def test_budget_min_above_max_is_rejected():
    """下限比上限大要当场报错，不静默取一个"差不多"的值。"""
    with pytest.raises(ValueError, match="下限"):
        build_requirement("", {"keyword": "西装", "budget_min": 250, "budget_max": 100})


def test_non_numeric_budget_is_rejected():
    with pytest.raises(ValueError, match="数字"):
        build_requirement("", {"keyword": "西装", "budget_max": "两百多"})


def test_negative_budget_is_rejected():
    with pytest.raises(ValueError, match="负数"):
        build_requirement("", {"keyword": "西装", "budget_max": -100})


def test_absurd_budget_is_rejected():
    with pytest.raises(ValueError, match="不合理"):
        build_requirement("", {"keyword": "西装", "budget_max": 10**12})


def test_natural_language_only_path_is_unchanged():
    """没传 fields 时行为必须和以前完全一致。"""
    text = "预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣"
    assert build_requirement(text).to_dict() == parse_requirement(text).to_dict()


# ---- 抖音登录入口：首页触发下载，不能拿它当登录窗口地址 ----

def test_douyin_login_entry_avoids_download_triggering_homepage():
    """实测 haohuo.jinritemai.com 一打开就触发文件下载，goto 抛
    ``Page.goto: Download is starting``，登录窗口会停在空白页，
    用户看到的就是「抖音登录无法实现」。抖音主站能正常打开，
    登录入口要用它。"""
    from app.browser.recipes import get_recipe
    from app.domain.enums import Platform

    recipe = get_recipe(Platform.DOUYIN)
    assert recipe.login_entry() == "https://www.douyin.com"
    assert recipe.login_entry() != recipe.home_url


def test_other_platforms_login_entry_defaults_to_home():
    from app.browser.recipes import get_recipe
    from app.domain.enums import Platform

    for platform in (Platform.JD, Platform.TAOBAO, Platform.PDD):
        recipe = get_recipe(platform)
        assert recipe.login_entry() == recipe.home_url

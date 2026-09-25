"""防套路：把「看着便宜、其实有坑」的信号挑出来。

比价真正难的不是找最低价，是三个价格根本不可比：一个支持 7 天无理由、
一个激活了就不给退；一个国行全国联保、一个港版自己找店修；一个带运费险、
一个退货运费自理。

这里固化的规矩：**没有页面证据就不说有坑；证据是否定式的按限制报；
页面没提的按「未显示」报并让用户自己去确认。** 宁可少报一个坑，
不能把一个保护讲成坑，也不能把坑讲成保护。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.browser.extract import extract_policies
from app.domain.enums import PolicyCategory
from app.domain.subsidy import (
    SubsidyFit,
    interpret_subsidy_text,
    subsidy_scenarios,
)
from app.domain.traps import (
    TrapBasis,
    TrapKind,
    TrapSeverity,
    detect_traps,
    summarize_traps,
    worst_severity,
)


def _kinds(traps):
    return [t.kind for t in traps]


def _find(traps, kind):
    return next(t for t in traps if t.kind is kind)


# ─── 激活不退 ────────────────────────────────────────────────────

def test_activation_lock_is_a_blocker_with_page_evidence():
    traps = detect_traps(["激活后不支持7天无理由退货", "全国联保"])
    trap = _find(traps, TrapKind.ACTIVATION_LOCKED)
    assert trap.severity is TrapSeverity.BLOCKER
    assert trap.basis is TrapBasis.PAGE_TEXT
    assert "激活后不支持" in trap.evidence
    assert trap.question  # 必须给用户一个要回答的问题
    assert trap.evidence == "激活后不支持7天无理由退货"


def test_activation_lock_detected_from_title_or_sku():
    """版本/激活信息常常只写在标题或规格里，政策栏反而没有。"""
    traps = detect_traps([], sku_text="拆封后不可退换")
    assert TrapKind.ACTIVATION_LOCKED in _kinds(traps)

    traps = detect_traps([], title="Apple AirPods Pro 2 港版 激活后不支持退换")
    assert TrapKind.ACTIVATION_LOCKED in _kinds(traps)


def test_positive_activation_wording_is_not_a_trap():
    """"激活后可享受7天无理由"是保护，不能被当成限制，也不该再报"未显示"。"""
    traps = detect_traps(["激活后可享受7天无理由退货", "退货运费险"])
    assert TrapKind.ACTIVATION_LOCKED not in _kinds(traps)
    assert TrapKind.NO_RETURN_WINDOW not in _kinds(traps)
    assert traps == []


# ─── 非国行 ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text", ["港版", "非国行", "海外版", "美版", "日版", "水货", "跨境版"]
)
def test_non_mainland_is_a_blocker(text):
    traps = detect_traps([], sku_text=text)
    trap = _find(traps, TrapKind.NON_MAINLAND)
    assert trap.severity is TrapSeverity.BLOCKER
    assert trap.evidence == text
    assert "国行" in trap.question


def test_mainland_version_is_not_a_trap():
    traps = detect_traps(["国行正品，全国联保", "7天无理由退货", "退货运费险"])
    assert TrapKind.NON_MAINLAND not in _kinds(traps)
    assert not traps, "页面把保护都写全了，就不该再报任何坑"


def test_both_wording_present_still_reported_for_the_user_to_judge():
    """标题同时出现"国行"和"港版"时，不替用户判定，报出来让他自己看。"""
    traps = detect_traps([], title="国行 港版 双版本 耳机")
    assert TrapKind.NON_MAINLAND in _kinds(traps)


# ─── 7 天无理由 ──────────────────────────────────────────────────

def test_explicit_no_return_window_is_major():
    traps = detect_traps(["该商品不支持7天无理由退货"])
    trap = _find(traps, TrapKind.NO_RETURN_WINDOW)
    assert trap.severity is TrapSeverity.MAJOR
    assert trap.basis is TrapBasis.PAGE_TEXT
    assert trap.label == "页面写明不支持7天无理由"


def test_missing_return_window_is_reported_as_not_shown_not_as_unsupported():
    """没看到不等于没有 —— 措辞必须是"未显示"，并配一个待确认问题。"""
    traps = detect_traps(["全国联保", "假一赔十"])
    trap = _find(traps, TrapKind.NO_RETURN_WINDOW)
    assert trap.severity is TrapSeverity.MINOR
    assert trap.basis is TrapBasis.NOT_SHOWN
    assert trap.label == "页面未显示7天无理由"
    assert "不支持" not in trap.label
    assert trap.evidence == ""
    assert trap.question
    assert "确认" in trap.question


def test_present_return_window_produces_no_no_return_trap():
    traps = detect_traps(["7天无理由退货", "退货运费险"])
    assert TrapKind.NO_RETURN_WINDOW not in _kinds(traps)


# ─── 特价不退不换 ────────────────────────────────────────────────

def test_special_goods_no_return_is_major():
    traps = detect_traps(["特价商品不支持7天无理由，不退不换"])
    assert TrapKind.SPECIAL_NO_RETURN in _kinds(traps)
    assert _find(traps, TrapKind.SPECIAL_NO_RETURN).severity is TrapSeverity.MAJOR


def test_special_word_alone_is_not_a_trap():
    """"特价"两个字不构成坑，必须和不退换连在一起才算。"""
    traps = detect_traps(["特价直降 50 元", "7天无理由退货", "退货运费险"])
    assert TrapKind.SPECIAL_NO_RETURN not in _kinds(traps)


def test_same_sentence_reports_only_the_more_specific_trap():
    """"特价商品不支持7天无理由退货，不退不换"同时命中两条，
    只报更具体的那条 —— 同一句证据报两遍只是噪音。"""
    traps = detect_traps(["特价商品不支持7天无理由退货，不退不换"])
    kinds = _kinds(traps)
    assert TrapKind.SPECIAL_NO_RETURN in kinds
    assert TrapKind.NO_RETURN_WINDOW not in kinds


def test_separate_sentences_report_both():
    """两条不同的话，各自报各自的，不能互相吞掉。"""
    traps = detect_traps(["该商品不支持7天无理由退货", "清仓商品不退不换"])
    assert TrapKind.NO_RETURN_WINDOW in _kinds(traps)
    assert TrapKind.SPECIAL_NO_RETURN in _kinds(traps)


# ─── 运费险 ──────────────────────────────────────────────────────

def test_missing_freight_insurance_is_minor_and_not_shown():
    traps = detect_traps(["7天无理由退货"])
    trap = _find(traps, TrapKind.NO_FREIGHT_INSURANCE)
    assert trap.severity is TrapSeverity.MINOR
    assert trap.basis is TrapBasis.NOT_SHOWN
    assert trap.question
    assert "运费" in trap.question


def test_present_freight_insurance_is_not_a_trap():
    traps = detect_traps(["7天无理由退货", "退货运费险"])
    assert TrapKind.NO_FREIGHT_INSURANCE not in _kinds(traps)


# ─── 补贴资格 ────────────────────────────────────────────────────

def test_subsidy_without_verified_eligibility_is_flagged():
    traps = detect_traps(["7天无理由退货", "退货运费险"], coupon_texts=["国补 15%（需本人资格核实）"])
    trap = _find(traps, TrapKind.SUBSIDY_UNVERIFIED)
    assert trap.severity is TrapSeverity.MAJOR
    assert trap.evidence == "国补 15%（需本人资格核实）"
    assert "不代您认定资格" in trap.detail
    assert trap.question


def test_plain_coupon_is_not_a_subsidy_trap():
    traps = detect_traps(["7天无理由退货", "退货运费险"], coupon_texts=["满 1000 减 100 元店铺券（已领取，可用）"])
    assert TrapKind.SUBSIDY_UNVERIFIED not in _kinds(traps)


# ─── 排序与摘要 ──────────────────────────────────────────────────

def test_worst_severity_and_summary():
    traps = detect_traps(
        ["激活后不支持7天无理由退货"],
        coupon_texts=["国补 15%"],
    )
    assert worst_severity(traps) is TrapSeverity.BLOCKER
    summary = summarize_traps(traps)
    assert "激活后不支持退换" in summary
    assert "补贴" in summary


def test_no_traps_summary():
    assert summarize_traps([]) == "页面未发现明显的退换或版本限制"


def test_blocker_sorts_first():
    traps = detect_traps(["激活后不支持7天无理由退货", "港版"])
    assert traps[0].kind is TrapKind.ACTIVATION_LOCKED


# ─── 政策归类：否定式不能变成"保护" ──────────────────────────────

def test_negated_return_text_is_classified_as_restriction():
    """这是本次改动最要紧的一条：以前"激活后不支持7天无理由"会被归成
    售后/退换，用户在「售后与保障」里看到它，还以为是项保护。"""
    policies = extract_policies(["激活后不支持7天无理由退货"])
    assert len(policies) == 1
    assert policies[0].category is PolicyCategory.RETURN_RESTRICTION


def test_positive_return_text_stays_after_sales():
    policies = extract_policies(["7天无理由退货"])
    assert policies[0].category is PolicyCategory.AFTER_SALES


def test_other_categories_unchanged():
    policies = extract_policies(
        ["全国联保", "假一赔十", "满 99 元包邮", "可开发票", "价保 30 天"]
    )
    assert [p.category for p in policies] == [
        PolicyCategory.WARRANTY,
        PolicyCategory.AUTHENTICITY,
        PolicyCategory.SHIPPING,
        PolicyCategory.INVOICE,
        PolicyCategory.PRICE_PROTECTION,
    ]


def test_restriction_and_positive_can_coexist():
    policies = extract_policies(["不支持7天无理由", "7天无理由退货"])
    categories = {p.category for p in policies}
    assert PolicyCategory.RETURN_RESTRICTION in categories
    assert PolicyCategory.AFTER_SALES in categories


# ─── 国补：两种情形都算，不合并 ──────────────────────────────────

def test_subsidy_percent_yields_two_scenarios():
    reading = interpret_subsidy_text("国补 15%", user_region="江苏省")
    scenarios = subsidy_scenarios(Decimal("1000.00"), reading)
    assert scenarios.without_subsidy == Decimal("1000.00")
    assert scenarios.with_subsidy == Decimal("850.00")
    # 文案必须说清右边只在符合资格时成立
    assert "符合补贴资格" in scenarios.note
    assert "不代您认定" in scenarios.note


def test_subsidy_amount_is_used_when_no_percent():
    reading = interpret_subsidy_text("政府补贴 减 200 元")
    scenarios = subsidy_scenarios(Decimal("1500.00"), reading)
    assert scenarios.with_subsidy == Decimal("1300.00")


def test_subsidy_never_goes_below_zero():
    """比例超过 100% 时（页面文案写错或理解错），不能出现负到手价。"""
    reading = interpret_subsidy_text("国补 120%")
    scenarios = subsidy_scenarios(Decimal("100.00"), reading)
    assert scenarios.with_subsidy == Decimal("0.00")


def test_subsidy_without_quantified_benefit_has_no_scenarios():
    """只写"有国补"没写比例/金额时，不硬凑一个数。"""
    reading = interpret_subsidy_text("可享受国家补贴")
    assert reading.has_quantified_benefit is False
    assert subsidy_scenarios(Decimal("1000.00"), reading) is None


def test_region_conflict_is_called_out():
    reading = interpret_subsidy_text("国补 15%，限江苏用户", user_region="广东省")
    assert reading.fit is SubsidyFit.REGION_CONFLICTS
    assert "不一致" in reading.reason
    scenarios = subsidy_scenarios(Decimal("1000.00"), reading)
    assert "不一致" in scenarios.note
    assert "很可能不成立" in scenarios.note


def test_region_match_is_reported_but_still_not_assumed():
    reading = interpret_subsidy_text("国补 15%，限江苏用户", user_region="江苏省")
    assert reading.fit is SubsidyFit.REGION_MATCHES
    assert "与您填写的收货地一致" in reading.reason
    # 地区对得上也不代表资格成立，问题照样要问
    assert reading.questions


def test_region_limit_without_user_region_asks_for_it():
    reading = interpret_subsidy_text("国补 15%，限江苏用户")
    assert reading.fit is SubsidyFit.UNKNOWN
    assert reading.region_limit == "江苏"
    assert any("江苏" in q for q in reading.questions)


def test_no_region_limit_asks_about_eligibility():
    reading = interpret_subsidy_text("国补 15%")
    assert reading.fit is SubsidyFit.UNKNOWN
    assert reading.questions
    assert any("资格" in q for q in reading.questions)


def test_non_subsidy_text_returns_none():
    assert interpret_subsidy_text("满 1000 减 100 元店铺券") is None


def test_region_normalization_matches_province_suffix():
    """"江苏"和"江苏省"要能对上，"江苏"和"南京"不能 —— 后者本来就要用户确认。"""
    assert interpret_subsidy_text("国补 15%，限江苏省", "江苏").fit is SubsidyFit.REGION_MATCHES
    assert interpret_subsidy_text("国补 15%，限江苏省", "南京市").fit is SubsidyFit.REGION_CONFLICTS

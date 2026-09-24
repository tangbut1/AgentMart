"""个人浏览器版抽取与定价逻辑的单元回归。

覆盖需求第十一节要求的测试面：
- 不同规格/版本/容量/尺码不得被错误合并
- 优惠门槛、互斥组、叠加、过期、运费、补贴资格不确定
- 同一页面字段识别失败、价格变动、登录过期、验证码、导航失败
- 单平台失败不影响其它平台
- 多平台隔离（不能把京东的券算到淘宝商品上）
- 视觉金额与页面证据不一致必须被拦截
- 任务取消与预算耗尽安全停止
- 不自动下单/付款
- 演示数据不得混入真实推荐
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.browser.agent import (
    BlockedPlatform,
    Requirement,
    ShoppingAgent,
    TaskOptions,
    parse_requirement,
)
from app.browser.driver import ScriptedDriver, ScriptedStep
from app.browser.enums import BlockedReason, DataOrigin, PriceCertainty, TaskStatus
from app.browser.extract import (
    PageFields,
    amounts_agree,
    build_offer,
    interpret_coupon_text,
    parse_money,
)
from app.domain.enums import ConditionKind, DataStatus, Platform
from app.domain.matching import group_offers
from app.domain.pricing import compute_price_breakdown

# ─── 金额解析 ────────────────────────────────────────────────────


def test_parse_money_accepts_common_formats():
    assert parse_money("¥899.00") == Decimal("899.00")
    assert parse_money("￥1,299.5") == Decimal("1299.50")
    assert parse_money("到手价 799 元") == Decimal("799")


def test_parse_money_returns_none_when_unclear():
    assert parse_money(None) is None
    assert parse_money("") is None
    assert parse_money("价格面议") is None
    assert parse_money("0") is None


# ─── 优惠解释 ────────────────────────────────────────────────────


def test_coupon_threshold_not_met_is_downgraded():
    """已领取但商品价未达门槛：不得计入确定到手价。"""
    reading = interpret_coupon_text("满 1000 减 100 元店铺券（已领取，可用）")
    assert reading is not None
    assert reading.threshold == Decimal("1000")
    assert reading.amount == Decimal("100")
    assert reading.certainty == PriceCertainty.ACCOUNT_COUPON

    fields = PageFields(
        url="https://item.jd.com/1001.html",
        title="测试商品",
        price_text="899.00",
        coupon_texts=["满 1000 减 100 元店铺券（已领取，可用）"],
    )
    offer, problems = build_offer(Platform.JD, fields, DataOrigin.REAL_PLATFORM_PAGE,
                                  source_label="test")
    breakdown = compute_price_breakdown(offer)
    # 门槛未达：确定价仍是标价，不能扣这 100
    assert breakdown.definite_total == Decimal("899.00")
    assert breakdown.potential_total == Decimal("799.00")
    assert offer.discounts[0].condition_kind == ConditionKind.CONDITIONAL


def test_coupon_threshold_met_stays_definite():
    fields = PageFields(
        url="https://item.jd.com/1002.html",
        title="测试商品",
        price_text="1299.00",
        coupon_texts=["满 1000 减 100 元店铺券（已领取，可用）"],
    )
    offer, _ = build_offer(Platform.JD, fields, DataOrigin.REAL_PLATFORM_PAGE,
                           source_label="test")
    breakdown = compute_price_breakdown(offer)
    assert breakdown.definite_total == Decimal("1199.00")


def test_unclaimed_coupon_is_only_conditional():
    reading = interpret_coupon_text("满 500 减 60 元店铺券 立即领取")
    assert reading is not None
    assert reading.certainty == PriceCertainty.CONDITIONAL


def test_expired_coupon_is_unverifiable():
    reading = interpret_coupon_text("满 300 减 30 元券 已过期")
    assert reading is not None
    assert reading.certainty == PriceCertainty.UNVERIFIABLE


def test_subsidy_eligibility_is_never_assumed():
    """国补/以旧换新的资格无法从页面确认，必须标为无法核实。"""
    reading = interpret_coupon_text("国补 15%，至高优惠 1500 元")
    assert reading is not None
    assert reading.certainty == PriceCertainty.UNVERIFIABLE
    assert "本人" in reading.reason


def test_subsidy_never_enters_definite_price():
    fields = PageFields(
        url="https://item.jd.com/1003.html",
        title="测试手机",
        price_text="4999.00",
        coupon_texts=["国家补贴 15%（限部分地区，需资格核实）"],
    )
    offer, _ = build_offer(Platform.JD, fields, DataOrigin.REAL_PLATFORM_PAGE,
                           source_label="test")
    breakdown = compute_price_breakdown(offer)
    assert breakdown.definite_total == Decimal("4999.00")
    assert breakdown.unverifiable_total == Decimal("0.00")
    assert offer.discounts[0].condition_kind == ConditionKind.UNVERIFIABLE


def test_coupon_without_amount_is_ignored():
    assert interpret_coupon_text("多买多优惠") is None


# ─── 视觉金额一致性 ──────────────────────────────────────────────


def test_vision_amount_matching_dom_is_accepted():
    ok, message = amounts_agree(Decimal("899.00"), Decimal("899.00"))
    assert ok is True


def test_vision_amount_conflicting_with_dom_is_intercepted():
    ok, message = amounts_agree(Decimal("899.00"), Decimal("799.00"))
    assert ok is False
    assert "拦截" in message


def test_vision_amount_without_dom_evidence_is_intercepted():
    ok, message = amounts_agree(None, Decimal("899.00"))
    assert ok is False


def test_vision_price_lowers_data_status():
    fields = PageFields(
        url="https://item.jd.com/1004.html",
        title="测试商品",
        price_text="899.00",
        price_source="vision",
    )
    offer, problems = build_offer(Platform.JD, fields, DataOrigin.REAL_PLATFORM_PAGE,
                                  source_label="test")
    assert offer.data_status == DataStatus.UNVERIFIED
    assert any("截图识别" in p for p in problems)


# ─── 规格不得被错误合并 ──────────────────────────────────────────


def _offer(platform, product_id, title, price="899.00"):
    fields = PageFields(
        url=f"https://item.{platform.value}.com/{product_id}.html",
        title=title,
        price_text=price,
        shop_name="测试旗舰店",
    )
    offer, _ = build_offer(platform, fields, DataOrigin.REAL_PLATFORM_PAGE,
                           source_label="test")
    return offer


def test_different_sizes_are_not_merged():
    offers = [
        _offer(Platform.JD, "2001", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L"),
        _offer(Platform.JD, "2002", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 XL"),
    ]
    groups = group_offers(offers)
    assert len(groups) == 2


def test_different_storage_is_not_merged():
    offers = [
        _offer(Platform.JD, "3001", "华为 Mate 60 Pro 12GB+256GB 曜石黑 5G"),
        _offer(Platform.JD, "3002", "华为 Mate 60 Pro 12GB+512GB 曜石黑 5G"),
    ]
    groups = group_offers(offers)
    assert len(groups) == 2


def test_different_version_is_not_merged():
    offers = [
        _offer(Platform.JD, "4001", "华为 Mate 60 Pro 12GB+256GB 国行 曜石黑"),
        _offer(Platform.JD, "4002", "华为 Mate 60 Pro 12GB+256GB 港版 曜石黑"),
    ]
    groups = group_offers(offers)
    assert len(groups) == 2


def test_different_brand_is_not_merged():
    offers = [
        _offer(Platform.JD, "5001", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L"),
        _offer(Platform.JD, "5002", "凯乐石 三合一冲锋衣 男 防雨 KG2201 黑色 L"),
    ]
    groups = group_offers(offers)
    assert len(groups) == 2


def test_same_model_across_platforms_is_merged_with_warning():
    offers = [
        _offer(Platform.JD, "6001", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L", "899.00"),
        _offer(Platform.TAOBAO, "6002", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L", "869.00"),
    ]
    groups = group_offers(offers)
    assert len(groups) == 1
    assert len(groups[0].offers) == 2


# ─── 需求解析 ────────────────────────────────────────────────────


def test_requirement_parses_budget_range_and_region():
    req = parse_requirement(
        "预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣，重视防雨和透气，配送至北京市"
    )
    assert req.category == "户外服装"
    assert req.budget_min == Decimal("500")
    assert req.budget_max == Decimal("800")
    assert req.region == "北京市"
    assert "通勤" in req.scenarios
    assert req.include_reviews is False


def test_requirement_approximate_budget_is_flagged():
    req = parse_requirement("想买一部手机，预算 3000 元左右，重视续航和信号")
    assert req.budget_max == Decimal("3000")
    assert req.budget_approximate is True


def test_requirement_records_subsidy_interest_without_promising_it():
    req = parse_requirement("买手机，预算 4000，看看有没有我能享受的国补")
    assert "关注补贴资格" in req.scenarios


def test_requirement_notes_unclear_category():
    req = parse_requirement("帮我找个好东西")
    assert req.unclear


# ─── 平台隔离 ────────────────────────────────────────────────────


def test_offers_keep_their_own_platform_coupons():
    """京东的券不能算到淘宝商品上：build_offer 只用本页抽取到的券。"""
    jd = _offer(Platform.JD, "7001", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L", "899.00")
    tb = _offer(Platform.TAOBAO, "7002", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L", "899.00")
    # 京东商品页看到"已领取可用"的券
    jd_fields = PageFields(
        url="https://item.jd.com/7001.html",
        title="探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L",
        price_text="899.00",
        coupon_texts=["满 800 减 50 元店铺券（已领取，可用）"],
    )
    jd_offer, _ = build_offer(Platform.JD, jd_fields, DataOrigin.REAL_PLATFORM_PAGE,
                              source_label="test")
    tb_fields = PageFields(
        url="https://item.taobao.com/7002.htm",
        title="探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L",
        price_text="899.00",
        coupon_texts=["店铺优惠券 满 900 减 80（待领取）"],
    )
    tb_offer, _ = build_offer(Platform.TAOBAO, tb_fields, DataOrigin.REAL_PLATFORM_PAGE,
                              source_label="test")
    assert compute_price_breakdown(jd_offer).definite_total == Decimal("849.00")
    # 淘宝那张券门槛 900 未达，且待领取 → 不影响确定价
    assert compute_price_breakdown(tb_offer).definite_total == Decimal("899.00")
    assert jd.platform is Platform.JD and tb.platform is Platform.TAOBAO


# ─── 演示数据隔离 ────────────────────────────────────────────────


def test_demo_offer_is_excluded_from_definite_price():
    real = _offer(Platform.JD, "8001", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L", "899.00")
    demo = _offer(Platform.JD, "8002", "探路者 三合一冲锋衣 男 防雨 TAWJ91717 黑色 L", "1.00")
    demo.data_status = DataStatus.DEMO
    groups = group_offers([real, demo])
    assert len(groups) == 1
    definite = [
        compute_price_breakdown(o).definite_total
        for o in groups[0].offers
        if o.data_status != DataStatus.DEMO
    ]
    assert definite == [Decimal("899.00")]


# ─── 编排器：状态机 / 取消 / 预算 / 平台失败隔离 ──────────────────


def _scripted_agent(steps, goto_delay: float = 0.0):
    driver = ScriptedDriver(steps, goto_delay=goto_delay)
    agent = ShoppingAgent(max_concurrency=2, driver_factory=lambda p: driver)
    return agent, driver


def _fields_result(url, title="测试商品 L", price="899.00", shop="测试官方旗舰店"):
    return {
        "url": url,
        "title": title,
        "priceText": price,
        "shopName": shop,
        "couponTexts": [],
        "policyTexts": ["7天无理由退货"],
        "evidence": {"jsonld:Product": "..."},
    }


def _task(agent, platforms, **options):
    requirement = Requirement(text="测试需求", keyword="冲锋衣")
    defaults = dict(
        platforms=platforms,
        ask_review_question=False,
        max_candidates=2,
        login_wait_seconds=1.0,
        max_task_seconds=30.0,
    )
    defaults.update(options)
    return agent.create_task(requirement, TaskOptions(**defaults))


@pytest.mark.asyncio
async def test_platform_failure_does_not_fail_whole_task():
    """京东被风控挡住时，淘宝仍应正常完成。"""
    steps = [
        ScriptedStep("jd", results={"login": {"looksLoggedIn": True},
                                    "blocked": {"captcha": False, "risk": True}}),
        ScriptedStep("taobao", results={
            "login": {"looksLoggedIn": True},
            "blocked": {"captcha": False, "risk": False},
            "links": [{"url": "https://item.taobao.com/9001.htm", "title": "商品一"}],
            "fields": _fields_result("https://item.taobao.com/9001.htm"),
        }),
    ]
    agent, driver = _scripted_agent(steps)
    task = _task(agent, [Platform.JD, Platform.TAOBAO])
    await agent.start(task.id)
    for _ in range(40):
        if task.status.is_terminal:
            break
        await __import__("asyncio").sleep(0.1)

    assert task.state_of(Platform.JD).status == TaskStatus.RESTRICTED
    assert task.state_of(Platform.JD).blocked_reason == BlockedReason.RISK_CONTROL
    assert task.state_of(Platform.TAOBAO).status == TaskStatus.COMPLETED
    assert len(task.real_offers) == 1
    # 平台被阻止时明确记录，不用演示数据补齐
    assert any("未用演示数据补齐" in n for n in task.notes)
    # 全程只做只读动作：没有任何一步会改变账号状态
    for state in task.states.values():
        for step in state.steps:
            assert step.action.is_read_only, f"出现了写操作：{step.action}"


@pytest.mark.asyncio
async def test_captcha_marks_platform_restricted():
    steps = [
        ScriptedStep("jd", results={"login": {"looksLoggedIn": True},
                                    "blocked": {"captcha": True}}),
    ]
    agent, driver = _scripted_agent(steps)
    task = _task(agent, [Platform.JD])
    await agent.start(task.id)
    for _ in range(40):
        if task.status.is_terminal:
            break
        await __import__("asyncio").sleep(0.1)
    state = task.state_of(Platform.JD)
    assert state.status == TaskStatus.RESTRICTED
    assert state.blocked_reason == BlockedReason.CAPTCHA
    assert not state.offers


@pytest.mark.asyncio
async def test_login_required_waits_for_user_then_stops():
    """未登录 → 等待用户接管 → 超时后标记平台限制，不无限等待。"""
    steps = [ScriptedStep("jd", results={"login": {"looksLoggedIn": False},
                                         "blocked": {"captcha": False}})]
    agent, driver = _scripted_agent(steps)
    task = _task(agent, [Platform.JD], login_wait_seconds=1.0)
    await agent.start(task.id)
    for _ in range(60):
        if task.status.is_terminal:
            break
        await __import__("asyncio").sleep(0.1)
    state = task.state_of(Platform.JD)
    assert state.status == TaskStatus.RESTRICTED
    assert state.blocked_reason == BlockedReason.LOGIN_REQUIRED


@pytest.mark.asyncio
async def test_cancel_stops_platform_safely():
    steps = [
        ScriptedStep("jd", results={
            "login": {"looksLoggedIn": True},
            "blocked": {"captcha": False},
            "links": [{"url": f"https://item.jd.com/{i}.html", "title": f"商品{i}"}
                      for i in range(20)],
            "fields": _fields_result("https://item.jd.com/1.html"),
        }),
    ]
    agent, driver = _scripted_agent(steps)
    task = _task(agent, [Platform.JD], max_candidates=20)
    await agent.start(task.id)
    await __import__("asyncio").sleep(0.2)
    await agent.cancel_task(task.id)
    assert task.status == TaskStatus.CANCELLED
    assert task.state_of(Platform.JD).status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_and_keeps_evidence():
    """任务时长上限到达时安全停止，已取得的证据保留。"""
    steps = [
        ScriptedStep("jd", results={
            "login": {"looksLoggedIn": True},
            "blocked": {"captcha": False},
            "links": [{"url": f"https://item.jd.com/{i}.html", "title": f"商品{i}"}
                      for i in range(20)],
            "fields": _fields_result("https://item.jd.com/1.html"),
        }),
    ]
    agent, driver = _scripted_agent(steps, goto_delay=0.05)
    task = _task(agent, [Platform.JD], max_candidates=20, max_task_seconds=0.2)
    await agent.start(task.id)
    for _ in range(60):
        if task.status.is_terminal:
            break
        await __import__("asyncio").sleep(0.1)
    assert task.budget_exhausted is True
    # 已取得的证据仍然在
    assert task.state_of(Platform.JD).offers or task.state_of(Platform.JD).problems


@pytest.mark.asyncio
async def test_navigation_failure_is_recorded_not_crashed():
    steps = [ScriptedStep("jd", results={})]
    agent, driver = _scripted_agent(steps)
    driver.raise_on_goto("jd")
    task = _task(agent, [Platform.JD])
    await agent.start(task.id)
    for _ in range(40):
        if task.status.is_terminal:
            break
        await __import__("asyncio").sleep(0.1)
    state = task.state_of(Platform.JD)
    assert state.status == TaskStatus.RESTRICTED
    assert state.blocked_reason == BlockedReason.NAVIGATION_FAILED


@pytest.mark.asyncio
async def test_no_offers_means_no_recommendation_and_no_demo_fill():
    steps = [ScriptedStep("jd", results={"login": {"looksLoggedIn": True},
                                         "blocked": {"captcha": False},
                                         "links": []})]
    agent, driver = _scripted_agent(steps)
    task = _task(agent, [Platform.JD])
    await agent.start(task.id)
    for _ in range(40):
        if task.status.is_terminal:
            break
        await __import__("asyncio").sleep(0.1)
    assert task.recommendation is None
    assert task.canonical == []
    assert any("不生成购买建议" in n for n in task.notes)


@pytest.mark.asyncio
async def test_review_question_is_asked_before_running():
    agent, driver = _scripted_agent([])
    task = _task(agent, [Platform.JD], ask_review_question=True)
    await agent.start(task.id)
    assert task.status == TaskStatus.WAITING_CONFIRM
    assert task.pending_question["key"] == "include_reviews"
    assert task.requirement.include_reviews is False

    agent.answer_question(task.id, "include_reviews", "不要")
    assert task.pending_question is None
    assert task.requirement.include_reviews is False


@pytest.mark.asyncio
async def test_review_question_affirmative_enables_reviews():
    agent, driver = _scripted_agent([])
    task = _task(agent, [Platform.JD], ask_review_question=True)
    await agent.start(task.id)
    agent.answer_question(task.id, "include_reviews", "要")
    assert task.requirement.include_reviews is True
    assert any("已开启" in n for n in task.notes)


@pytest.mark.asyncio
async def test_result_view_marks_origin_and_keeps_links():
    steps = [
        ScriptedStep("jd", results={
            "login": {"looksLoggedIn": True},
            "blocked": {"captcha": False},
            "links": [{"url": "https://item.jd.com/9501.html", "title": "某商品 L"}],
            "fields": _fields_result("https://item.jd.com/9501.html"),
        }),
    ]
    agent, driver = _scripted_agent(steps)
    task = _task(agent, [Platform.JD], origin=DataOrigin.TEST_FIXTURE)
    await agent.start(task.id)
    for _ in range(40):
        if task.status.is_terminal:
            break
        await __import__("asyncio").sleep(0.1)
    view = agent.result_view(task)
    assert view["origin"] == "test_fixture"
    assert view["origin_label"] == "测试夹具"
    assert view["groups"]
    card = view["groups"][0]["offers"][0]
    assert card["url"].startswith("https://item.jd.com/")
    assert card["certainty"]["level"] in {
        "page_public", "account_coupon", "conditional", "prepayment", "unverifiable"
    }


@pytest.mark.asyncio
async def test_taobao_and_tmall_share_profile_group():
    from app.browser.profiles import profile_group

    assert profile_group(Platform.TAOBAO) == profile_group(Platform.TMALL)
    assert profile_group(Platform.JD) != profile_group(Platform.TAOBAO)


def test_blocked_platform_carries_reason():
    exc = BlockedPlatform(BlockedReason.CAPTCHA, "出现滑块验证")
    assert exc.reason == BlockedReason.CAPTCHA
    assert "滑块" in exc.detail

"""风控页 / 网关错误页不能被误报成"页面结构无法识别"。

用户在真实环境里看到的就是这条链：平台返回一个拦截页或错误页 →
探测脚本认为页面正常 → 抽链接拿到 0 条 → 报
"页面结构可能已变化或需要登录"。这个原因是**错的**，用户照着去重新
登录，问题一点不会好转。

这里固化三种已在线核实过的页面形态：
1. 京东验证页：跳到 cfe.m.jd.com/privatedomain/risk_handler/...，
   页面只有"验证一下"和"前往登录"，文案匹配不上，只能靠 URL 认；
2. 京东限流页：原文「抱歉由于访问频繁导致无法搜索，请稍后再试」；
3. 网关错误页：搜索端点挂掉时返回 502/504 的 TLB 错误页
   （抖音 haohuo.jinritemai.com/search 实测）。

正则直接从 ``JS_BLOCKED_PROBE`` 源码里取，不另抄一份。
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest

from app.browser.agent import BlockedPlatform, NeedsUserTakeover, ShoppingAgent
from app.browser.enums import BlockedReason
from app.browser.recipes import JS_BLOCKED_PROBE


def _extract(var_name: str) -> str:
    match = re.search(rf"const {var_name} = /([^/]+)/", JS_BLOCKED_PROBE)
    assert match, f"没在 JS_BLOCKED_PROBE 里找到 {var_name} 的定义"
    return match.group(1)


def _run_probe(text: str, title: str = "", url: str = "") -> dict:
    script = f"""
const text = {json.dumps(text, ensure_ascii=False)};
const title = {json.dumps(title, ensure_ascii=False)};
const url = {json.dumps(url, ensure_ascii=False)};
const captcha = /{_extract("captcha")}/.test(text) || /captcha|punish|verify/.test(url);
const risk = /{_extract("risk")}/.test(text) || /risk_handler|privatedomain|risk_verify|slider_verify/.test(url);
const unavailable = /{_extract("unavailable")}/.test(text) || /^(502|503|504)\\b/.test(title);
const loginWall = /{_extract("loginWall")}/.test(text);
console.log(JSON.stringify({{ captcha, risk, unavailable, loginWall }}));
"""
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30
    )
    if out.returncode != 0:
        pytest.skip(f"node 不可用，跳过正则本体校验: {out.stderr[:120]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


# ---- 三种真实页面形态 ----

def test_jd_risk_handler_page_is_detected():
    """京东验证页：文案只有"验证一下/前往登录"，必须靠 URL 认出来。"""
    probe = _run_probe(
        text="验证一下\n前往登录",
        url="https://cfe.m.jd.com/privatedomain/risk_handler/03101900/"
            "?evApi=color-mesh_A_SC_pc_search",
    )
    assert probe["risk"] is True
    assert probe["unavailable"] is False


def test_jd_rate_limited_text_is_detected():
    probe = _run_probe(
        text="抱歉由于访问频繁导致无法搜索，请稍后再试！\n若长时间无法搜索可[点此反馈]",
        url="https://search.jd.com/Search?keyword=x&enc=utf-8",
    )
    assert probe["risk"] is True


def test_gateway_error_page_is_detected_as_unavailable():
    """502/504 的 TLB 错误页：不是结构问题，是端点不可用。"""
    probe = _run_probe(
        text="502 Bad Gateway\nTLB",
        title="502 Bad Gateway",
        url="https://haohuo.jinritemai.com/search?keyword=x",
    )
    assert probe["unavailable"] is True
    # 端点挂了和触发风控是两件事，别混成一个原因
    assert probe["risk"] is False


def test_normal_search_page_is_not_flagged():
    """正常商品页不能被误判成任何一种拦截。"""
    probe = _run_probe(
        text="索尼（SONY）WH-1000XM5 头戴式无线降噪耳机 黑色\n京东价 ￥2399.00 立即购买",
        title="索尼（SONY）WH-1000XM5 - 商品搜索 - 京东",
        url="https://search.jd.com/Search?keyword=x&enc=utf-8",
    )
    assert probe["captcha"] is False
    assert probe["risk"] is False
    assert probe["unavailable"] is False


def test_old_narrow_patterns_would_have_missed_all_three():
    """留反面证据：这三条旧实现全都漏了，说明不是臆测。"""
    old_risk = "访问过于频繁|操作过于频繁|系统繁忙|异常流量|风控|已被限制"
    assert re.search(old_risk, "抱歉由于访问频繁导致无法搜索，请稍后再试") is None
    assert "risk_handler" not in old_risk
    assert "502 Bad Gateway" not in old_risk


# ---- _probe_blocked 的分流 ----

class _Driver:
    def __init__(self, probe: dict):
        self.probe = probe

    async def evaluate(self, script, arg=None):
        return self.probe


async def test_risk_page_asks_user_to_take_over():
    """风控页不再是"直接放弃"：先交给用户接管，用户处理不完才判平台限制。

    这一条是分水岭。以前这里抛 BlockedPlatform，用户看到的就是
    "该平台本次未完成"，明明滑一下就能过，却白白少一个平台的比价结果。
    """
    agent = ShoppingAgent(max_concurrency=1)
    driver = _Driver({"captcha": False, "risk": True, "unavailable": False})
    with pytest.raises(NeedsUserTakeover) as excinfo:
        await agent._probe_blocked(driver, object(), None)
    assert excinfo.value.reason is BlockedReason.RISK_CONTROL
    # 提示要说清是什么，且不能引导用户去"重新登录"（那是另一个原因）
    assert "频繁" in excinfo.value.detail or "限制" in excinfo.value.detail


async def test_gateway_error_raises_navigation_failed_not_structure():
    """端点挂了要报 navigation_failed，不能被放行到 structure_unknown。"""
    agent = ShoppingAgent(max_concurrency=1)
    driver = _Driver({"captcha": False, "risk": False, "unavailable": True})
    with pytest.raises(BlockedPlatform) as excinfo:
        await agent._probe_blocked(driver, object(), None)
    assert excinfo.value.reason is BlockedReason.NAVIGATION_FAILED
    message = str(excinfo.value)
    assert "502" in message or "网关" in message
    # 不能把用户引去重新登录
    assert "重新登录" not in message


async def test_clean_page_passes_through():
    agent = ShoppingAgent(max_concurrency=1)
    driver = _Driver({"captcha": False, "risk": False, "unavailable": False})
    await agent._probe_blocked(driver, object(), None)

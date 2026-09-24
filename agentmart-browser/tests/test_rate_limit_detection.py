"""限流页不能被误报成"页面结构无法识别"。

京东限流时的页面原文是「抱歉由于访问频繁导致无法搜索，请稍后再试」。
旧的 ``JS_BLOCKED_PROBE`` 只匹配「访问过于频繁」，匹配不上这条，
于是 ``_probe_blocked`` 放行，最后在抽链接那步报
``structure_unknown``——告诉用户"页面结构可能已变化或需要登录"，
这是一个**错误的原因**。用户照着去重新登录，问题一点不会好转。

这里固化：
- 限流文案要能被 ``risk`` 命中（正则直接从 ``JS_BLOCKED_PROBE`` 里取，
  不另抄一份，避免测试和实现各说各话）；
- 命中之后 ``_probe_blocked`` 抛 RISK_CONTROL，而不是放行到后面；
- 正常商品页不该被误判成限流。
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest

from app.browser.agent import BlockedPlatform, ShoppingAgent
from app.browser.enums import BlockedReason
from app.browser.recipes import JS_BLOCKED_PROBE

# 京东限流页的真实文案（来自线上诊断，不是编的）
JD_RATE_LIMITED_TEXT = (
    "京东首页\n切换企业版\n同款搜低价\n购物车 我的订单 我的京东\n"
    "全部商品\n新品\n店铺\n配送至\n传统模式\n简洁模式\n"
    "抱歉由于访问频繁导致无法搜索，请稍后再试！\n"
    "若长时间无法搜索可[点此反馈]，平台将尽快处理\n"
)

NORMAL_SEARCH_TEXT = (
    "索尼（SONY）WH-1000XM5 头戴式无线降噪耳机 黑色\n"
    "京东价 ￥2399.00 满1999减200 加入购物车 立即购买\n"
)


def _extract(var_name: str) -> str:
    """从 JS_BLOCKED_PROBE 源码里取出某个正则字面量，保证测的是真实现。"""
    match = re.search(rf"const {var_name} = /([^/]+)/", JS_BLOCKED_PROBE)
    assert match, f"没在 JS_BLOCKED_PROBE 里找到 {var_name} 的定义"
    return match.group(1)


def _run_probe(text: str) -> dict:
    """在 Node 里按 JS_BLOCKED_PROBE 的原样逻辑跑一遍。"""
    script = f"""
const text = {json.dumps(text, ensure_ascii=False)};
const url = 'https://search.jd.com/Search?keyword=x&enc=utf-8';
const captcha = /{_extract("captcha")}/.test(text)
  || /captcha|punish|verify/.test(url);
const risk = /{_extract("risk")}/.test(text);
const loginWall = /{_extract("loginWall")}/.test(text);
console.log(JSON.stringify({{ captcha, risk, loginWall }}));
"""
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30
    )
    if out.returncode != 0:
        pytest.skip(f"node 不可用，跳过正则本体校验: {out.stderr[:120]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_jd_rate_limited_text_is_detected_as_risk():
    probe = _run_probe(JD_RATE_LIMITED_TEXT)
    assert probe["risk"] is True
    assert probe["captcha"] is False


def test_normal_search_page_is_not_flagged_as_risk():
    probe = _run_probe(NORMAL_SEARCH_TEXT)
    assert probe["risk"] is False
    assert probe["captcha"] is False


def test_old_narrow_pattern_would_have_missed_it():
    """留一个反面证据：旧的窄正则确实匹配不上，说明这个 bug 是真的。"""
    old = "访问过于频繁|操作过于频繁|系统繁忙|异常流量|风控|已被限制"
    assert re.search(old, JD_RATE_LIMITED_TEXT) is None


class _Driver:
    def __init__(self, probe: dict):
        self.probe = probe

    async def evaluate(self, script, arg=None):
        return self.probe


async def test_probe_blocked_raises_risk_control_for_rate_limit():
    """限流页要抛 RISK_CONTROL，不能被放行到"识别不到商品链接"那一步。"""
    agent = ShoppingAgent(max_concurrency=1)
    driver = _Driver({"captcha": False, "risk": True, "loginWall": False})
    with pytest.raises(BlockedPlatform) as excinfo:
        await agent._probe_blocked(driver, object(), None)
    assert excinfo.value.reason is BlockedReason.RISK_CONTROL
    # 文案要说清"被限制"，不能把用户引去重新登录
    message = str(excinfo.value)
    assert "访问过于频繁" in message or "限制" in message
    assert "重新登录" not in message


async def test_probe_blocked_passes_through_a_clean_page():
    """干净页面不该被误判，正常往下走。"""
    agent = ShoppingAgent(max_concurrency=1)
    driver = _Driver({"captcha": False, "risk": False, "loginWall": False})
    await agent._probe_blocked(driver, object(), None)

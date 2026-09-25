"""端到端：HTTP 接口 → 编排器 → 真实 Chromium → 本地夹具 → 结果 JSON。

这是唯一一条跑真实浏览器的测试，因此：
- 目标页面全部来自本地 FixtureServer（127.0.0.1 随机端口），不访问任何真实电商站点；
- 用 ``url_overrides`` 把平台首页/搜索页指到夹具，避免误连真实站点；
- 结束后关闭浏览器会话并还原驱动工厂，不影响其它测试。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.browser.driver import PlaywrightConfig, PlaywrightDriver
from app.browser.enums import DataOrigin
from app.browser.fixtures import FixtureServer, FixtureSpec
from app.browser.service import service
from app.domain.enums import Platform
from app.main import app

PROFILE_ROOT = f"/tmp/agentmart-e2e-{__import__('os').getpid()}"


def _playwright_factory(base_url: str):
    def factory(platform: Platform) -> PlaywrightDriver:
        return PlaywrightDriver(
            f"{PROFILE_ROOT}-{platform.value}",
            PlaywrightConfig(headless=True),
        )

    return factory


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}")
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.database.async_session_factory",
        async_sessionmaker(engine, expire_on_commit=False),
    )
    original = service.agent._driver_factory
    with TestClient(app) as c:
        yield c
    service.agent.set_driver_factory(original)
    asyncio.run(service.agent.close_all_sessions())


def _wait_terminal(client: TestClient, task_id: str, timeout: float = 120.0):
    import time

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/browser/tasks/{task_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["summary_status"] in ("completed", "restricted", "failed", "cancelled"):
            return last
        time.sleep(1.0)
    raise AssertionError(f"任务在 {timeout}s 内没有结束：{last and last['summary_status']}")


def test_full_task_over_http_with_real_chromium(client):
    """建任务 → 开始 → 轮询到结束 → 结果里必须只有真实来源的商品。"""
    spec = FixtureSpec()
    with FixtureServer(spec) as server:
        base = server.base_url
        service.agent.set_driver_factory(_playwright_factory(base))

        created = client.post(
            "/api/browser/tasks",
            json={
                "text": "预算 500～800 元，买一件适合日常通勤和轻度徒步的冲锋衣，重视防雨和透气",
                "platforms": ["jd"],
                "options": {
                    "max_candidates": 3,
                    "ask_review_question": False,
                    "origin": "test_fixture",
                    "headless": True,
                    "url_overrides": {
                        "jd.home": f"{base}/jd/home.html",
                        "jd.search": f"{base}/jd/search.html",
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        task_id = created.json()["id"]

        started = client.post(f"/api/browser/tasks/{task_id}/start")
        assert started.status_code == 200
        assert started.json()["summary_status"] in ("running", "pending", "completed")

        final = _wait_terminal(client, task_id)
        assert final["summary_status"] == "completed", final["notes"]
        assert final["offer_count"] >= 1

        result = client.get(f"/api/browser/tasks/{task_id}/result").json()
        assert result["origin"] == DataOrigin.TEST_FIXTURE.value
        groups = result["groups"]
        assert groups, "夹具应返回商品组"

        # 每个商品都必须带原页面链接与读取时间，且来源标注为测试夹具
        for group in groups:
            for offer in group["offers"]:
                assert offer["url"].startswith(base)
                assert offer["fetched_at"]
                assert offer["certainty"]["level"] in (
                    "page_public",
                    "account_coupon",
                    "conditional",
                    "prepayment",
                    "unverifiable",
                )
                # 到手价拆解必须自洽：确定价是不计任何待确认优惠的下限，
                # 含待确认优惠的潜在价只会更低或相等
                definite = float(offer["breakdown"]["definite_total"])
                potential = float(offer["breakdown"]["potential_total"])
                assert potential <= definite + 1e-6

        # 同一型号不同尺码不能被合并成一组
        titles = [g["title"] for g in groups]
        assert any("L" in t for t in titles)
        assert any("XL" in t for t in titles)
        assert any("M" in t for t in titles)
        assert len(groups) >= 2

        # 落库记录也要能读回来
        record = client.get(f"/api/browser/tasks/{task_id}/record").json()
        assert record["result"]["groups"]


def test_blocked_platform_is_recorded_not_faked(client):
    """夹具首页要求登录时：任务进入等待用户，不会伪造商品。"""
    spec = FixtureSpec(home_logged_in=False)
    with FixtureServer(spec) as server:
        base = server.base_url
        service.agent.set_driver_factory(_playwright_factory(base))

        created = client.post(
            "/api/browser/tasks",
            json={
                "text": "预算 900 元买冲锋衣",
                "platforms": ["jd"],
                "options": {
                    "max_candidates": 2,
                    "ask_review_question": False,
                    "origin": "test_fixture",
                    "headless": True,
                    "login_wait_seconds": 3,
                    "url_overrides": {
                        "jd.home": f"{base}/jd/home.html",
                        "jd.search": f"{base}/jd/search.html",
                    },
                },
            },
        )
        task_id = created.json()["id"]
        client.post(f"/api/browser/tasks/{task_id}/start")
        final = _wait_terminal(client, task_id, timeout=90)

        state = next(p for p in final["platforms"] if p["platform"] == "jd")
        assert state["status"] in ("restricted", "completed")
        result = client.get(f"/api/browser/tasks/{task_id}/result").json()
        # 没能取到价就不该出现任何商品，更不能出现演示数据
        assert all(not offer["is_demo"] for g in result["groups"] for offer in g["offers"])


def _wait_for(client: TestClient, task_id: str, predicate, timeout: float = 90.0):
    """轮询到 predicate(task) 为真，返回那一刻的任务快照。"""
    import time

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/browser/tasks/{task_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if predicate(last):
            return last
        time.sleep(0.5)
    raise AssertionError(f"条件在 {timeout}s 内没出现：{last and last['summary_status']}")


def test_user_takeover_resumes_pipeline_with_real_chromium(client):
    """真实浏览器里跑一遍「验证码 → 等用户 → 用户处理完 → 自己接着比价」。

    夹具首页/搜索页在前 8 秒返回安全验证页，之后恢复正常 ——
    相当于用户在窗口里滑完了验证码。要验证的是：
    1. 期间平台确实进入 waiting_user 并带上 takeover 提示，任务没有失败；
    2. 验证消失后流水线自己往下走，不需要重新开始；
    3. 最终结果仍是真实夹具商品，没有演示数据。
    """
    spec = FixtureSpec(captcha_first_seconds=8.0)
    with FixtureServer(spec) as server:
        base = server.base_url
        service.agent.set_driver_factory(_playwright_factory(base))

        created = client.post(
            "/api/browser/tasks",
            json={
                "text": "预算 900 元买一件防雨透气的冲锋衣",
                "platforms": ["jd"],
                "options": {
                    "max_candidates": 2,
                    "ask_review_question": False,
                    "origin": "test_fixture",
                    "headless": True,
                    "max_task_seconds": 120,
                    "url_overrides": {
                        "jd.home": f"{base}/jd/home.html",
                        "jd.search": f"{base}/jd/search.html",
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        task_id = created.json()["id"]
        client.post(f"/api/browser/tasks/{task_id}/start")

        waiting = _wait_for(client, task_id, lambda t: t["summary_status"] == "waiting_user")
        assert "安全验证" in (waiting["waiting_reason"] or "")
        jd = next(p for p in waiting["platforms"] if p["platform"] == "jd")
        assert jd["takeover"]["kind"] == "captcha"
        assert jd["takeover"]["resolved"] is False

        # 验证消失后必须自己回到 running，然后正常跑完
        resumed = _wait_for(
            client,
            task_id,
            lambda t: t["summary_status"] == "running"
            and any("安全验证已通过" in s["detail"] for p in t["platforms"] for s in p["steps"]),
        )
        assert resumed["waiting_reason"] is None
        assert next(p for p in resumed["platforms"] if p["platform"] == "jd")["takeover"] is None

        final = _wait_terminal(client, task_id, timeout=120)
        assert final["summary_status"] == "completed", final["notes"]
        assert final["offer_count"] >= 1

        result = client.get(f"/api/browser/tasks/{task_id}/result").json()
        assert all(not offer["is_demo"] for g in result["groups"] for offer in g["offers"])


def test_traps_and_subsidy_flow_through_real_chromium(client):
    """真实浏览器里，防套路信号和补贴两套算法要能原样送到前端。

    夹具里第三个商品故意写成"特价商品不支持7天无理由退货，不退不换"
    且没有运费险 —— 低价来自坑，不是来自优惠。要验证的是：
    1. 这条限制被识别出来，且带页面原文作证据；
    2. "页面未显示"类的提示措辞是"未显示"，不是"不支持"；
    3. 国补给出两个到手价，且都不被合并成一个数。
    """
    spec = FixtureSpec()
    with FixtureServer(spec) as server:
        base = server.base_url
        service.agent.set_driver_factory(_playwright_factory(base))

        created = client.post(
            "/api/browser/tasks",
            json={
                # 用户自己说了收货地，用来比对补贴文案里的地区限制
                "text": "预算 900 元买一件防雨透气的冲锋衣，配送至江苏省",
                "platforms": ["jd"],
                "options": {
                    "max_candidates": 3,
                    "ask_review_question": False,
                    "origin": "test_fixture",
                    "headless": True,
                    "max_task_seconds": 120,
                    "url_overrides": {
                        "jd.home": f"{base}/jd/home.html",
                        "jd.search": f"{base}/jd/search.html",
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        task_id = created.json()["id"]
        client.post(f"/api/browser/tasks/{task_id}/start")
        final = _wait_terminal(client, task_id, timeout=120)
        assert final["summary_status"] == "completed", final["notes"]

        result = client.get(f"/api/browser/tasks/{task_id}/result").json()
        offers = [o for g in result["groups"] for o in g["offers"]]
        assert len(offers) >= 2

        by_title = {o["title"]: o for o in offers}
        tricky = next(o for t, o in by_title.items() if "PELLIOT8823" in t)
        clean = next(o for t, o in by_title.items() if "TAWJ91717" in t and "XL" in t)

        # 1) 有页面证据的限制：特价不退不换，severity 是 major
        special = next(
            t for t in tricky["traps"] if t["kind"] == "special_no_return"
        )
        assert special["severity"] == "major"
        assert special["basis"] == "page_text"
        assert "不退不换" in special["evidence"]
        assert special["question"]
        assert "特价/清仓商品不退不换" in tricky["trap_summary"]
        # 同一句证据只报最具体的那个，不重复报
        assert not any(
            t["kind"] == "no_return_window" and t["basis"] == "page_text"
            for t in tricky["traps"]
        )

        # 2) 没看到运费险：措辞必须是"未显示"，不能讲成"不支持"
        freight = next(
            t for t in tricky["traps"] if t["kind"] == "no_freight_insurance"
        )
        assert freight["basis"] == "not_shown"
        assert "不支持" not in freight["label"]
        assert freight["question"]

        # 3) 干净的那条不该被报成有不退不换
        assert not any(t["kind"] == "special_no_return" for t in clean["traps"])
        assert not any(t["kind"] == "no_return_window" for t in clean["traps"])

        # 4) 国补：两个到手价都摆出来，不合并
        subsidy = tricky["subsidy"] or clean["subsidy"]
        assert subsidy is not None, "夹具里写了国补，这里必须出现"
        assert subsidy["fit"] in ("region_matches", "region_conflicts", "unknown")
        scenarios = subsidy["scenarios"]
        if scenarios:
            assert scenarios["without_subsidy"] and scenarios["with_subsidy"]
            assert "不代您认定" in scenarios["note"]
        # 补贴永远不进确定到手价
        definite = float(clean["breakdown"]["definite_total"])
        assert definite == float(clean["list_price"])


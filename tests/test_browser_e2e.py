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

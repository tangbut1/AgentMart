"""「商品链接/口令直接对比」模式。

为什么值得单独测：这是从"全网搜词"转向"精准单品对决"的那一步。
用户手里有的是商品详情页链接，不是搜索词 —— 链接认错平台、或者
解析失败被静默丢掉，比价就跑偏了。

覆盖：
- 链接解析服务（文本 / 数组两种输入）；
- 建任务时 direct_links 按平台分组落进 TaskOptions；
- 认不出链接时 422 说清楚缺什么，不建空任务；
- 只贴一条主链接时，先打开它提炼型号，再拿去别的平台搜同款；
- 提炼不出型号时不瞎搜，如实记录原因。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.browser.agent import Requirement, ShoppingAgent, TaskOptions
from app.browser.driver import ScriptedDriver, ScriptedStep
from app.browser.service import _parse_direct_links, parse_links_preview, service
from app.domain.enums import Platform
from app.main import app


# ─── 服务层解析 ──────────────────────────────────────────────────

def test_parse_direct_links_from_text_blob():
    grouped = _parse_direct_links(
        "京东 https://item.jd.com/1.html 淘宝 https://item.taobao.com/item.htm?id=2"
    )
    assert grouped == {
        Platform.JD: ["https://item.jd.com/1.html"],
        Platform.TAOBAO: ["https://item.taobao.com/item.htm?id=2"],
    }


def test_parse_direct_links_from_list():
    grouped = _parse_direct_links(
        [
            "https://item.jd.com/1.html",
            "https://detail.tmall.com/item.htm?id=3",
            "https://item.jd.com/1.html?utm_source=x",  # 去跟踪参数后是同一条
        ]
    )
    assert grouped == {
        Platform.JD: ["https://item.jd.com/1.html"],
        Platform.TMALL: ["https://detail.tmall.com/item.htm?id=3"],
    }


def test_parse_direct_links_ignores_unusable_entries():
    """首页/登录页收进来也抽不到商品，宁可不带出去。"""
    grouped = _parse_direct_links(
        "https://www.jd.com https://item.jd.com/1.html https://login.taobao.com/x"
    )
    assert grouped == {Platform.JD: ["https://item.jd.com/1.html"]}


def test_parse_direct_links_rejects_non_text():
    with pytest.raises(ValueError):
        _parse_direct_links(12345)


def test_parse_links_preview_reports_problems():
    data = parse_links_preview("https://item.jd.com/1.html ¥aB3xK9z¥")
    assert data["usable"] == 1
    assert data["problems"] and "复制链接" in data["problems"][0]


def test_links_for_returns_a_copy():
    """links_for 返回副本：调用方改列表不能污染任务选项。"""
    options = TaskOptions(
        direct_links={Platform.JD: ["https://item.jd.com/1.html"]}
    )
    options.links_for(Platform.JD).append("https://evil.example")
    assert options.direct_links[Platform.JD] == ["https://item.jd.com/1.html"]
    assert options.links_for(Platform.PDD) == []


# ─── 接口层 ──────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'links.db'}")
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.database.async_session_factory",
        async_sessionmaker(engine, expire_on_commit=False),
    )
    with TestClient(app) as c:
        yield c


def test_parse_links_endpoint(client):
    resp = client.post(
        "/api/browser/parse-links",
        json={"links": "https://item.jd.com/1.html\nhttps://m.tb.cn/h.abc"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["usable"] == 2
    assert data["by_platform"] == {"jd": 1, "taobao": 1}


def test_parse_links_endpoint_accepts_array(client):
    resp = client.post(
        "/api/browser/parse-links", json={"links": ["https://item.jd.com/1.html"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["usable"] == 1


def test_parse_links_endpoint_rejects_empty(client):
    resp = client.post("/api/browser/parse-links", json={"links": "   "})
    assert resp.status_code == 422


def test_create_task_with_direct_links(client):
    resp = client.post(
        "/api/browser/tasks",
        json={
            "text": "",
            "platforms": ["jd", "taobao"],
            "options": {"direct_links": "https://item.jd.com/1.html"},
        },
    )
    assert resp.status_code == 200, resp.text
    options = resp.json()["options"]
    assert options["direct_links"] == {"jd": ["https://item.jd.com/1.html"]}
    # 默认去别的平台搜同款
    assert options["expand_from_primary"] is True


def test_create_task_can_disable_expand_from_primary(client):
    resp = client.post(
        "/api/browser/tasks",
        json={
            "text": "",
            "platforms": ["jd"],
            "options": {
                "direct_links": ["https://item.jd.com/1.html"],
                "expand_from_primary": False,
            },
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["options"]["expand_from_primary"] is False


def test_create_task_with_unusable_links_explains_why(client):
    """认不出链接要说清楚缺什么，不能建一个注定跑不出结果的任务。"""
    resp = client.post(
        "/api/browser/tasks",
        json={
            "text": "",
            "platforms": ["jd"],
            "options": {"direct_links": "¥aB3xK9z¥"},
        },
    )
    assert resp.status_code == 422, resp.text
    assert "复制链接" in resp.json()["detail"]


# ─── 主链接型号提取 ──────────────────────────────────────────────

def _scripted(title: str) -> ScriptedDriver:
    return ScriptedDriver(
        [
            ScriptedStep(
                "item.jd.com",
                results={
                    "login": {"looksLoggedIn": True},
                    "blocked": {"captcha": False, "risk": False},
                    "fields": {
                        "url": "https://item.jd.com/100012043978.html",
                        "title": title,
                        "priceText": "¥2499.00",
                    },
                },
            )
        ]
    )


def _task_with_primary_link(agent: ShoppingAgent, keyword: str = "") -> "object":
    return agent.create_task(
        Requirement(text="", keyword=keyword),
        TaskOptions(
            platforms=[Platform.JD, Platform.TAOBAO],
            direct_links={Platform.JD: ["https://item.jd.com/100012043978.html"]},
            max_task_seconds=30.0,
        ),
    )


async def test_primary_link_yields_search_keyword():
    agent = ShoppingAgent(max_concurrency=1, driver_factory=lambda p: _scripted(
        "索尼（SONY）WH-1000XM5 头戴式无线降噪耳机 黑色 标配"
    ))
    task = _task_with_primary_link(agent)
    await agent._extract_primary_model(task)
    assert task.requirement.keyword == "索尼 WH-1000XM5"
    assert any("索尼 WH-1000XM5" in note for note in task.notes)


async def test_primary_link_skipped_when_user_gave_keyword():
    """用户自己填了型号就不覆盖 —— 表单优先。"""
    agent = ShoppingAgent(max_concurrency=1, driver_factory=lambda p: _scripted("x"))
    task = _task_with_primary_link(agent, keyword="我自己填的型号")
    await agent._extract_primary_model(task)
    assert task.requirement.keyword == "我自己填的型号"


async def test_primary_link_without_model_says_so_instead_of_guessing():
    """标题里提炼不出型号 → 记一条问题，不拿品牌名去瞎搜。"""
    agent = ShoppingAgent(max_concurrency=1, driver_factory=lambda p: _scripted(
        "波司登羽绒服男2024冬季新款90绒短款加厚保暖外套"
    ))
    task = _task_with_primary_link(agent)
    await agent._extract_primary_model(task)
    assert task.requirement.keyword == ""
    assert any("跳过其它平台的同款搜索" in p for p in task.states[Platform.JD].problems)


async def test_primary_link_pick_first_platform_with_links():
    agent = ShoppingAgent(max_concurrency=1, driver_factory=lambda p: _scripted("x"))
    task = agent.create_task(
        Requirement(text=""),
        TaskOptions(
            platforms=[Platform.PDD, Platform.JD],
            direct_links={
                Platform.PDD: ["https://mobile.yangkeduo.com/goods.html?id=9"],
                Platform.JD: ["https://item.jd.com/1.html"],
            },
        ),
    )
    # 平台顺序以用户选择的顺序为准，Pdd 排在前就先用它
    assert agent._primary_link(task) == (
        Platform.PDD,
        "https://mobile.yangkeduo.com/goods.html?id=9",
    )


async def test_primary_link_without_links_is_noop():
    agent = ShoppingAgent(max_concurrency=1, driver_factory=lambda p: _scripted("x"))
    task = agent.create_task(Requirement(text=""), TaskOptions(platforms=[Platform.JD]))
    assert agent._primary_link(task) == (None, "")
    await agent._extract_primary_model(task)
    assert task.requirement.keyword == ""


async def test_search_same_model_without_keyword_returns_empty():
    """没型号就不搜：搜回来的多半不是同款。"""
    agent = ShoppingAgent(max_concurrency=1, driver_factory=lambda p: _scripted("x"))
    task = agent.create_task(Requirement(text=""), TaskOptions(platforms=[Platform.TMALL]))
    state = task.states[Platform.TMALL]
    driver = _scripted("x")
    links = await agent._search_same_model(
        task, Platform.TMALL, state, driver, asyncio.Event()
    )
    assert links == []
    assert any("未能从" in p for p in state.problems)
    # 没有型号时连搜索页都不该打开
    assert driver.goto_calls == []


def test_service_singleton_exists():
    """路由用的就是模块级单例，测试里操作的是同一个编排器。"""
    assert service.agent is not None

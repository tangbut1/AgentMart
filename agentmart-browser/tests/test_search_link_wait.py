"""搜索结果页「等渲染」的逻辑：不能把还没渲染完误判成结构不认识。

用户在京东上遇到的真实形态：搜索页是客户端渲染的，``goto`` 返回的瞬间
商品锚点还没挂上。旧代码立刻抽取，拿到 0 条就把平台报成
``structure_unknown``（"页面结构无法识别"），比价一次都没做成。

这里覆盖：
- 第一轮为空、稍后出现商品 → 要等到并返回，不能提前放弃；
- 一直为空 → 等满预算后如实返回空，由调用方报 structure_unknown；
- 任务被取消 → 立刻返回，不拖满预算；
- 真的等到了，要在执行记录里说明"页面是动态加载的"。
"""
from __future__ import annotations

import asyncio

from app.browser import agent as agent_module
from app.browser.agent import Requirement, ShoppingAgent, TaskOptions
from app.browser.driver import ScriptedDriver, ScriptedStep
from app.browser.enums import ActionKind


def _agent(steps) -> ShoppingAgent:
    return ShoppingAgent(max_concurrency=1, driver_factory=lambda p: steps)


class _DelayedLinks:
    """前 ``empty_rounds`` 次返回空，之后返回商品链接。"""

    def __init__(self, empty_rounds: int):
        self.empty_rounds = empty_rounds
        self.calls = 0

    async def evaluate(self, script, arg=None):
        self.calls += 1
        if self.calls <= self.empty_rounds:
            return []
        return [{"url": "https://item.jd.com/100012043978.html", "title": "测试商品耳机"}]


class _State:
    def __init__(self):
        self.logs = []

    def log(self, kind, detail, url=None):
        self.logs.append((kind, detail))


def _task(agent: ShoppingAgent):
    return agent.create_task(
        Requirement(text="预算 2500 的降噪耳机", keyword="降噪耳机"), TaskOptions()
    )


async def test_waits_for_links_that_render_late(monkeypatch):
    """第一轮抽不到、后面渲染出来了 → 必须等到，不能提前判死刑。"""
    monkeypatch.setattr(agent_module, "_LINK_WAIT_SECONDS", 5.0)
    monkeypatch.setattr(agent_module, "_LINK_POLL_SECONDS", 0.01)

    driver = _DelayedLinks(empty_rounds=3)
    agent = _agent(driver)
    task = _task(agent)
    state = _State()

    links = await agent._collect_links(driver, state, task)

    assert len(links) == 1
    assert links[0]["url"].startswith("https://item.jd.com/")
    # 说明它确实多轮重试过，不是第一次就拿到
    assert driver.calls >= 4
    # 等到了要留一句说明，用户才知道为什么慢
    assert any(kind is ActionKind.READ and "动态加载" in d for kind, d in state.logs)


async def test_gives_up_after_budget_and_reports_nothing(monkeypatch):
    """一直抽不到 → 等满预算后返回空，不猜不补。"""
    monkeypatch.setattr(agent_module, "_LINK_WAIT_SECONDS", 0.08)
    monkeypatch.setattr(agent_module, "_LINK_POLL_SECONDS", 0.01)

    class _Never:
        def __init__(self):
            self.calls = 0

        async def evaluate(self, script, arg=None):
            self.calls += 1
            return []

    driver = _Never()
    agent = _agent(driver)
    task = _task(agent)
    state = _State()

    started = asyncio.get_running_loop().time()
    links = await agent._collect_links(driver, state, task)
    elapsed = asyncio.get_running_loop().time() - started

    assert links == []
    # 等过，但不会无限等
    assert driver.calls > 1
    assert elapsed >= 0.07
    assert elapsed < 2.0
    # 没等到就不该写"已渲染出来"
    assert not any("动态加载" in d for _, d in state.logs)


async def test_cancelled_task_returns_immediately(monkeypatch):
    """任务被取消 → 立刻返回，不拖满等待预算。"""
    monkeypatch.setattr(agent_module, "_LINK_WAIT_SECONDS", 30.0)
    monkeypatch.setattr(agent_module, "_LINK_POLL_SECONDS", 0.01)

    class _Never:
        async def evaluate(self, script, arg=None):
            return []

    agent = _agent(_Never())
    task = _task(agent)
    state = _State()
    agent._cancel_events[task.id].set()

    started = asyncio.get_running_loop().time()
    links = await agent._collect_links(_Never(), state, task)
    elapsed = asyncio.get_running_loop().time() - started

    assert links == []
    assert elapsed < 1.0


async def test_driver_error_is_treated_as_no_links(monkeypatch):
    """抽取报错不当异常抛出去，按"没有链接"继续走，让调用方如实报错。"""
    monkeypatch.setattr(agent_module, "_LINK_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(agent_module, "_LINK_POLL_SECONDS", 0.01)

    class _Boom:
        async def evaluate(self, script, arg=None):
            raise RuntimeError("页面已关闭")

    agent = _agent(_Boom())
    task = _task(agent)
    links = await agent._collect_links(_Boom(), _State(), task)
    assert links == []


async def test_scripted_driver_links_still_flow_through(monkeypatch):
    """夹具驱动的链接要能原样透过这一层，不能被等渲染逻辑吃掉。"""
    monkeypatch.setattr(agent_module, "_LINK_WAIT_SECONDS", 1.0)
    monkeypatch.setattr(agent_module, "_LINK_POLL_SECONDS", 0.01)

    driver = ScriptedDriver(
        [
            ScriptedStep(
                "jd",
                results={
                    "login": {"looksLoggedIn": True},
                    "blocked": {"captcha": False, "risk": False},
                    "links": [
                        {"url": "https://item.jd.com/100012043978.html", "title": "索尼降噪耳机"}
                    ],
                },
            )
        ]
    )
    agent = _agent(driver)
    task = _task(agent)
    # 和真实流程一致：先打开搜索页，再抽链接
    assert await driver.goto("https://search.jd.com/Search?keyword=%E9%99%8D%E5%99%AA%E8%80%B3%E6%9C%BA")
    links = await agent._collect_links(driver, _State(), task)
    assert [l["url"] for l in links] == ["https://item.jd.com/100012043978.html"]

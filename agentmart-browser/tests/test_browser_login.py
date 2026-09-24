"""手动登录窗口的回归测试。

覆盖：
- 点「登录」会弹出一个**可见**窗口，并跳到平台首页；
- 探测脚本只读 DOM，不读账号/cookie/输入框；
- 探测到已登录 → 状态变 logged_in，窗口仍留给用户自己关；
- 用户把窗口关了 → 状态变 closed，不会一直挂着；
- 登录窗口和比价任务对同一个 profile 组互斥（两边都验证）；
- 关窗 / 关所有窗口后 profile 目录不被删（登录态要留着）；
- 探测不到登录时不谎报已登录。
"""
from __future__ import annotations

import asyncio

import pytest

from app.browser.agent import ShoppingAgent
from app.browser.driver import ScriptedDriver, ScriptedStep
from app.browser.enums import TaskStatus
from app.browser.login import CLOSED, LOGGED_IN, WAITING_LOGIN, LoginUnavailable
from app.browser.agent import TaskOptions
from app.domain.enums import Platform


def _driver(steps):
    return ScriptedDriver(steps)


def _agent(steps):
    driver = _driver(steps)
    return ShoppingAgent(max_concurrency=2, driver_factory=lambda p: driver), driver


def _login_agent(logged_in: bool):
    steps = [
        ScriptedStep("jd", results={
            "login": {"looksLoggedIn": logged_in},
            "blocked": {"captcha": False, "risk": False},
        }),
    ]
    agent, _ = _agent(steps)
    return agent


def _task(agent, platforms=(Platform.JD,)):
    from app.browser.agent import Requirement

    return agent.create_task(
        Requirement(text="测试需求", keyword="冲锋衣"),
        TaskOptions(
            platforms=list(platforms),
            ask_review_question=False,
            max_candidates=1,
            login_wait_seconds=0.5,
            max_task_seconds=20.0,
        ),
    )


async def _wait_status(agent, group, wanted, timeout=8.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        session = agent.logins.get(group)
        if session is not None and session.status == wanted:
            return session
        await asyncio.sleep(0.05)
    session = agent.logins.get(group)
    raise AssertionError(
        f"登录窗口状态没有变成 {wanted}，当前是 {session.status if session else None}"
    )


# ─── 开窗 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_login_window_uses_visible_browser_and_home_page():
    agent = _login_agent(logged_in=False)
    session = await agent.open_login_window("jd")
    assert session.platform is Platform.JD
    assert session.status == WAITING_LOGIN
    # 打开的必须是用户能看见的窗口，并跳到平台首页
    assert session.driver.current_url == "https://www.jd.com"
    assert session.driver.goto_calls == ["https://www.jd.com"]
    assert "请你自己完成登录" in session.message
    # 同一个组重复点「登录」复用同一个窗口，不重复弹
    again = await agent.open_login_window("jd")
    assert again is session
    await agent.close_login_window("jd")


@pytest.mark.asyncio
async def test_unknown_group_is_rejected():
    agent = _login_agent(logged_in=False)
    with pytest.raises(LoginUnavailable):
        await agent.open_login_window("not-a-platform")


@pytest.mark.asyncio
async def test_login_probe_only_reads_dom():
    """探测脚本里不能出现读取账号、cookie、输入框的写法。"""
    from app.browser.recipes import JS_LOGIN_PROBE

    forbidden = ["cookie", "localStorage", "value", "password", "input[", "credential"]
    for token in forbidden:
        assert token not in JS_LOGIN_PROBE, f"登录探测脚本里出现了 {token}"


@pytest.mark.asyncio
async def test_detects_logged_in_and_keeps_window_open():
    agent = _login_agent(logged_in=True)
    session = await agent.open_login_window("jd")
    await _wait_status(agent, "jd", LOGGED_IN)
    assert "已登录" in session.message
    # 探到登录也不替用户关窗，窗口仍然归用户控制
    assert agent.logins.is_busy("jd")
    await agent.close_login_window("jd")


@pytest.mark.asyncio
async def test_not_logged_in_stays_waiting():
    agent = _login_agent(logged_in=False)
    await agent.open_login_window("jd")
    await asyncio.sleep(0.3)
    session = agent.logins.get("jd")
    assert session.status == WAITING_LOGIN
    assert "请你自己完成登录" in session.message
    await agent.close_login_window("jd")


@pytest.mark.asyncio
async def test_closing_window_keeps_login_state_on_disk():
    """关窗口只是关浏览器，不能把登录态目录删掉。"""
    agent = _login_agent(logged_in=True)
    await agent.open_login_window("jd")
    result = await agent.close_login_window("jd")
    assert result["closed"] is True
    assert "登录态仍保留" in result["message"]
    session = agent.logins.get("jd")
    assert session.status == CLOSED
    assert agent.logins.is_busy("jd") is False


# ─── 互斥 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_cannot_start_while_login_window_open():
    """登录窗口开着时任务不能抢同一个 profile 目录。"""
    agent = _login_agent(logged_in=False)
    await agent.open_login_window("jd")
    task = _task(agent, (Platform.JD,))
    await agent.start(task.id)
    for _ in range(60):
        if task.status.is_terminal:
            break
        await asyncio.sleep(0.05)

    state = task.state_of(Platform.JD)
    assert state.status in (TaskStatus.RESTRICTED, TaskStatus.FAILED)
    assert "登录窗口正开着" in (state.blocked_detail or "")
    # 整个任务不该因此崩掉，只是这个平台没跑成
    assert task.real_offers == []
    await agent.close_login_window("jd")


@pytest.mark.asyncio
async def test_login_window_refuses_while_task_running():
    """任务正占用该组时，登录窗口要拒绝打开并说清原因。"""
    steps = [
        ScriptedStep("jd", results={
            "login": {"looksLoggedIn": True},
            "blocked": {"captcha": False, "risk": False},
            "links": [{"url": "https://item.jd.com/1.html", "title": "商品一"}],
            "fields": {
                "url": "https://item.jd.com/1.html",
                "title": "商品一",
                "priceText": "899.00",
                "shopName": "测试店",
                "couponTexts": [],
                "policyTexts": [],
                "evidence": {},
            },
        }),
    ]
    agent, driver = _agent(steps)
    driver.goto_delay = 0.4  # 让任务在首页多停一会，确保会话已占用
    task = _task(agent, (Platform.JD,))
    await agent.start(task.id)
    await asyncio.sleep(0.1)  # 让任务先把会话占上

    with pytest.raises(LoginUnavailable) as exc:
        await agent.open_login_window("jd")
    assert "正在执行比价任务" in str(exc.value)

    for _ in range(60):
        if task.status.is_terminal:
            break
        await asyncio.sleep(0.05)
    assert task.state_of(Platform.JD).status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_close_all_sessions_also_closes_login_windows():
    """服务关闭时不能残留登录窗口进程。"""
    agent = _login_agent(logged_in=False)
    await agent.open_login_window("jd")
    assert agent.logins.is_busy("jd")
    await agent.close_all_sessions()
    assert agent.logins.is_busy("jd") is False
    assert agent.logins.get("jd").status == CLOSED


@pytest.mark.asyncio
async def test_login_status_lists_every_group():
    agent = _login_agent(logged_in=False)
    status = agent.login_window_status()
    groups = {item["group"] for item in status}
    assert groups == {"jd", "taobao", "pdd", "douyin"}
    # 没开过窗口的组是 idle，不是假装开着
    idle = [i for i in status if i["status"] == "idle"]
    assert len(idle) == 4
    # 淘宝与天猫同组，窗口只按组算一个
    taobao = next(i for i in status if i["group"] == "taobao")
    assert set(taobao["platforms"]) == {"taobao", "tmall"}


@pytest.mark.asyncio
async def test_login_state_is_honest_about_directory_vs_login():
    """目录存在不等于已登录：服务层要分开报。"""
    from app.browser.service import _login_state

    assert _login_state(False, {"status": "logged_in"})[0] == "logged_in"
    assert _login_state(True, {"status": "waiting_login"})[0] == "waiting_login"
    # 关键：目录在、但没探到登录 → 不能报"已登录"
    assert _login_state(True, {"status": "idle"})[0] == "saved_unverified"
    assert _login_state(False, {"status": "idle"})[0] == "none"
